"""15 deterministic checks. Each is (workflow, catalog, runs) -> findings, so each is testable alone."""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Callable
from typing import Literal

from pydantic import BaseModel

from ..builder.validator import validate
from ..model import Catalog, Run, Step, Workflow, is_empty, variable_refs

Severity = Literal["high", "medium", "low"]


class Finding(BaseModel):
    code: str
    severity: Severity
    step_id: str | None = None
    message: str
    fix: str


Check = Callable[[Workflow, Catalog, list[Run]], list[Finding]]


def _steps_of_kind(wf: Workflow, catalog: Catalog, kind: str) -> list[Step]:
    return [s for s in wf.steps.values() if s.node_type in catalog and catalog[s.node_type].kind == kind]


def no_trigger(wf, catalog, runs):
    if wf.trigger:
        return []
    return [Finding(code="NO_TRIGGER", severity="high", message="The workflow has no trigger, so nothing can start it.",
                    fix="Add a trigger step (for example TaskCreated) and point its next at the first step.")]


def trigger_not_in_catalog(wf, catalog, runs):
    t = wf.trigger
    if not t or (t.node_type in catalog and catalog[t.node_type].kind == "trigger"):
        return []
    return [Finding(code="TRIGGER_NOT_IN_CATALOG", severity="high", step_id=t.id,
                    message=f"Trigger {t.node_type} is not a trigger in the engine catalog.",
                    fix=f"Replace trigger {t.id} with a catalog trigger such as TaskCreated or TaskOverdue.")]


def trigger_leads_nowhere(wf, catalog, runs):
    t = wf.trigger
    if not t or t.next:
        return []
    return [Finding(code="TRIGGER_DEAD_END", severity="high", step_id=t.id,
                    message="The trigger fires but has no next step, so every run does nothing.",
                    fix=f"Set next on trigger {t.id} to the id of the first step.")]


def step_node_removed(wf, catalog, runs):
    return [Finding(code="STEP_NODE_REMOVED", severity="high", step_id=s.id,
                    message=f"Step {s.id} uses node {s.node_type}, which no longer exists in the catalog.",
                    fix=f"Replace step {s.id} with a current node, or delete it and re-link its neighbours.")
            for s in wf.steps.values() if s.node_type not in catalog]


def empty_required_param(wf, catalog, runs):
    return [Finding(code="EMPTY_REQUIRED_PARAM", severity="high", step_id=g.step_id,
                    message=f"Step {g.step_id} has no value for required setting '{g.param}'.",
                    fix=f"Set '{g.param}' on step {g.step_id}.")
            for g in validate(wf, catalog).gaps]


def invalid_status_param(wf, catalog, runs):
    out = []
    for s in wf.nodes():
        node = catalog.get(s.node_type)
        for param, allowed in (node.allowed_values.items() if node else []):
            v = s.params.get(param)
            if not is_empty(v) and v not in allowed and "{{" not in str(v):
                out.append(Finding(code="INVALID_STATUS_PARAM", severity="medium", step_id=s.id,
                                   message=f"Step {s.id} sets {param}='{v}', which {s.node_type} rejects.",
                                   fix=f"Change '{param}' on step {s.id} to one of: {', '.join(allowed)}."))
    return out


def dangling_ref(wf, catalog, runs):
    idx = wf.index()
    return [Finding(code="BROKEN_POINTER", severity="high", step_id=s.id,
                    message=f"Step {s.id} points at {t}, which does not exist.",
                    fix=f"Re-point step {s.id} at an existing step, or clear the pointer.")
            for s in wf.nodes() for t in s.targets() if t not in idx]


def branch_leads_nowhere(wf, catalog, runs):
    out = []
    for s in _steps_of_kind(wf, catalog, "condition"):
        for branch in ("on_true", "on_false"):
            if not getattr(s, branch):
                out.append(Finding(code="CONDITION_DEAD_END", severity="high", step_id=s.id,
                                   message=f"Condition {s.id} has no {branch.upper()} branch; runs stop there.",
                                   fix=f"Set {branch} on step {s.id} to the step that should run next."))
    return out


def condition_not_allowed(wf, catalog, runs):
    """Branching is only valid on allow-listed condition nodes."""
    return [Finding(code="CONDITION_NOT_ALLOWED", severity="high", step_id=s.id,
                    message=f"Step {s.id} branches on TRUE/FALSE but {s.node_type} is not an allowed condition.",
                    fix=f"Insert a FieldEquals or FieldGreaterThan condition before step {s.id}'s branches.")
            for s in wf.steps.values()
            if s.node_type in catalog and catalog[s.node_type].kind != "condition" and (s.on_true or s.on_false)]


def zero_delay(wf, catalog, runs):
    return [Finding(code="ZERO_DELAY", severity="low", step_id=s.id,
                    message=f"Delay step {s.id} waits 0 minutes, so it does nothing.",
                    fix=f"Set 'minutes' on step {s.id} above 0, or remove the step.")
            for s in wf.steps.values() if s.node_type == "Delay" and s.params.get("minutes") == 0]


def unreachable_step(wf, catalog, runs):
    if not wf.trigger:
        return []  # without a trigger everything is unreachable; NO_TRIGGER already says so
    seen = set(wf.walk())
    return [Finding(code="UNREACHABLE_STEP", severity="medium", step_id=sid,
                    message=f"Step {sid} cannot be reached from the trigger.",
                    fix=f"Link step {sid} from a reachable step's next/on_true/on_false, or delete it.")
            for sid in wf.steps if sid not in seen]


def all_runs_failed(wf, catalog, runs):
    if len(runs) < 2 or any(r.status == "succeeded" for r in runs):
        return []
    return [Finding(code="ALL_RUNS_FAILED", severity="high",
                    message=f"All {len(runs)} recorded runs failed; the workflow has never worked.",
                    fix="Fix the failing step named in the recent failures, then re-run.")]


def last_run_failed(wf, catalog, runs):
    ordered = sorted(runs, key=lambda r: r.started_at)
    if not ordered or ordered[-1].status != "failed" or all_runs_failed(wf, catalog, runs):
        return []
    last = ordered[-1]
    return [Finding(code="LAST_RUN_FAILED", severity="medium", step_id=last.failed_step_id,
                    message=f"The most recent run ({last.run_id}) failed: {last.error}.",
                    fix="Fix the failing step named in the recent failures; earlier runs worked, so check what changed.")]


def active_never_ran(wf, catalog, runs):
    if wf.status != "active" or runs:
        return []
    return [Finding(code="ACTIVE_NEVER_RAN", severity="low",
                    message="The workflow is active but has never run.",
                    fix="Check the trigger's conditions and fire a test event.")]


def dead_variable(wf, catalog, runs):
    preds: dict[str, set[str]] = defaultdict(set)
    for s in wf.nodes():
        for t in s.targets():
            preds[t].add(s.id)

    def upstream(sid: str) -> set[str]:
        seen, queue = set(), [sid]
        while queue:
            for p in preds[queue.pop()]:
                if p not in seen:
                    seen.add(p)
                    queue.append(p)
        return seen

    out = []
    for s in wf.nodes():
        up = upstream(s.id)
        for param, producer in variable_refs(s.params):
            if producer not in up:
                out.append(Finding(code="DEAD_VARIABLE", severity="high", step_id=s.id,
                                   message=f"'{param}' on step {s.id} reads a variable from {producer}, which no upstream step produces.",
                                   fix=f"Replace the placeholder in '{param}' on step {s.id} with a value from the trigger or an earlier step."))
    return out


# The four groups the Doctor reports in. dead_variable was added with the conversational agent;
# the other fourteen are the original endpoint checks.
CHECK_GROUPS: dict[str, list[Check]] = {
    "trigger": [no_trigger, trigger_not_in_catalog, trigger_leads_nowhere],
    "step_parameter": [step_node_removed, empty_required_param, invalid_status_param, dangling_ref, dead_variable],
    "flow": [branch_leads_nowhere, condition_not_allowed, zero_delay, unreachable_step],
    "execution_health": [all_runs_failed, last_run_failed, active_never_ran],
}

ALL_CHECKS: list[Check] = [c for group in CHECK_GROUPS.values() for c in group]
