"""Pure workflow operations an agent calls as tools: find, copy, edit, publish, revert.

Nothing here asks for confirmation and nothing talks to a backend. The conversational agent (see
the sibling agent-kit repo) owns confirm-before-write, user consent and run-history handling; it
calls these functions only after the user said yes. There is deliberately no delete operation.
"""

from __future__ import annotations

import copy
import uuid
from typing import Any, Literal

from pydantic import BaseModel, Field

from .builder.validator import validate
from .doctor.drift import detect_drift_report
from .model import Catalog, Provenance, Step, Workflow, rewrite_variables
from .store import WorkflowStore


class EditError(ValueError):
    """The edit cannot be applied (unknown step, published workflow, ...)."""


class PublishedWorkflowError(EditError):
    """Published workflows are immutable; copy one to change it."""


class PublishRefused(ValueError):
    """The workflow still has blocking errors or empty required settings."""


class RevertUnavailable(ValueError):
    """No as-built snapshot was recorded, so there is nothing to go back to."""


# --- find ---------------------------------------------------------------------------------

class Candidate(BaseModel):
    id: str
    name: str
    status: str


class FindResult(BaseModel):
    """one: proceed with `candidates[0]`. several: ask the user which. none: say so."""

    outcome: Literal["one", "several", "none"]
    candidates: list[Candidate] = Field(default_factory=list)

    @property
    def workflow_id(self) -> str | None:
        return self.candidates[0].id if self.outcome == "one" else None


def find_by_name(store: WorkflowStore, name: str) -> FindResult:
    """Exact name (case-insensitive) wins; otherwise any name containing the text. Never guesses
    between several: the caller must ask."""
    wanted = " ".join(name.lower().split())
    all_wfs = store.list_workflows()
    hits = [w for w in all_wfs if " ".join(w.name.lower().split()) == wanted]
    hits = hits or [w for w in all_wfs if wanted and wanted in w.name.lower()]
    cands = [Candidate(id=w.id, name=w.name, status=w.status) for w in hits]
    return FindResult(outcome="none" if not cands else "one" if len(cands) == 1 else "several", candidates=cands)


# --- edit ---------------------------------------------------------------------------------

class Edit(BaseModel):
    """Set params and/or pointers on one step. A pointer value of None clears it."""

    step_id: str
    set_params: dict[str, Any] = Field(default_factory=dict)
    set_pointers: dict[Literal["next", "on_true", "on_false"], str | None] = Field(default_factory=dict)


def _apply(wf: Workflow, edit: Edit) -> Workflow:
    out = wf.model_copy(deep=True)
    step = out.index().get(edit.step_id)
    if step is None:
        raise EditError(f"no step {edit.step_id} in workflow {wf.id}")
    step.params.update(copy.deepcopy(edit.set_params))
    for pointer, target in edit.set_pointers.items():
        setattr(step, pointer, target)
    return out


def apply_edit(wf: Workflow, edit: Edit) -> Workflow:
    """Returns an edited copy. Refuses published workflows. The caller saves the result."""
    if wf.status == "published":
        raise PublishedWorkflowError(f"workflow {wf.id} is published and cannot be edited")
    return _apply(wf, edit)


def drift_edits(wf: Workflow) -> list[Edit]:
    """A proposed fix for param drift: set each drifted key back to its as-built value."""
    return [Edit(step_id=sid, set_params={k: c.as_built for k, c in change.params.items()})
            for sid, change in detect_drift_report(wf).steps_changed.items() if change.params]


# --- copy ---------------------------------------------------------------------------------

def _clone_step(step: Step, ids: dict[str, str]) -> Step:
    """New id, pointers and {{variable}} references all moved to the new ids. A pointer to an id
    that does not exist stays as is: a copy of a broken workflow is equally broken, not silently fixed."""
    return step.model_copy(update={
        "id": ids[step.id],
        "params": {k: rewrite_variables(v, ids) if isinstance(v, str) else copy.deepcopy(v) for k, v in step.params.items()},
        **{p: ids.get(t, t) if (t := getattr(step, p)) else None for p in ("next", "on_true", "on_false")},
    })


def copy_workflow(wf: Workflow, edits: list[Edit] | None = None, name: str | None = None) -> Workflow:
    """A new draft with fresh ids for the workflow and every step, links and variables rewired,
    and `edits` (written against the source's ids) applied in the same call. Provenance is kept
    (same source request, as-built values moved to the new ids), so edits show up as drift."""
    ids = {sid: str(uuid.uuid4()) for sid in wf.index()}
    clone = Workflow(
        id=str(uuid.uuid4()),
        name=name or f"Copy of {wf.name}",
        status="draft",
        trigger=_clone_step(wf.trigger, ids) if wf.trigger else None,
        steps={ids[sid]: _clone_step(s, ids) for sid, s in wf.steps.items()},
    )
    if (b := wf.built_from) is not None:
        clone.built_from = Provenance(
            source_text=b.source_text,
            source_ref=b.source_ref,
            as_built_params={ids.get(sid, sid): {k: rewrite_variables(v, ids) if isinstance(v, str) else copy.deepcopy(v)
                                                 for k, v in p.items()} for sid, p in b.as_built_params.items()},
            as_built_steps={ids[sid]: _clone_step(s, ids) for sid, s in b.as_built_steps.items() if sid in ids},
            as_built_trigger_id=ids.get(b.as_built_trigger_id or ""),
        )
    for e in edits or []:
        if e.step_id not in ids:
            raise EditError(f"no step {e.step_id} in workflow {wf.id}")
        clone = _apply(clone, Edit(
            step_id=ids[e.step_id],
            set_params={k: rewrite_variables(v, ids) if isinstance(v, str) else v for k, v in e.set_params.items()},
            set_pointers={p: ids.get(t, t) if t else None for p, t in e.set_pointers.items()},
        ))
    return clone


# --- publish / revert ---------------------------------------------------------------------

def publish(wf: Workflow, catalog: Catalog) -> Workflow:
    """Marks the workflow published, but only if it validates: no structural errors, no empty
    required settings."""
    res = validate(wf, catalog)
    if res.errors or res.gaps:
        problems = [e.code for e in res.errors] + [f"EMPTY:{g.step_id}.{g.param}" for g in res.gaps]
        raise PublishRefused(f"cannot publish {wf.id}: {', '.join(problems)}")
    return wf.model_copy(deep=True, update={"status": "published"})


def revert(wf: Workflow) -> Workflow:
    """Restores the last as-built graph (types, params, pointers). Refuses published workflows."""
    if wf.status == "published":
        raise PublishedWorkflowError(f"workflow {wf.id} is published and cannot be edited")
    b = wf.built_from
    if b is None or not b.as_built_steps or b.as_built_trigger_id is None:
        raise RevertUnavailable(f"workflow {wf.id} has no as-built snapshot")
    snap = {sid: s.model_copy(deep=True) for sid, s in b.as_built_steps.items()}
    trigger = snap.pop(b.as_built_trigger_id)
    return wf.model_copy(deep=True, update={"trigger": trigger, "steps": snap})
