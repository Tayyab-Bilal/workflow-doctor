"""Two tiers: errors block the build, gaps are values the user can still fill in."""

from __future__ import annotations

from collections import Counter

from pydantic import BaseModel, Field

from ..model import Catalog, Workflow, is_empty


class Issue(BaseModel):
    code: str
    step_id: str | None = None
    message: str


class Gap(BaseModel):
    step_id: str
    param: str


class ValidationResult(BaseModel):
    errors: list[Issue] = Field(default_factory=list)
    gaps: list[Gap] = Field(default_factory=list)


def _find_cycle(wf: Workflow) -> str | None:
    """3-colour DFS. A node is in a cycle only if we meet a GREY (on-stack) node again;
    meeting a BLACK (finished) node is just a diamond, not a cycle."""
    idx = wf.index()
    colour: dict[str, int] = {}  # absent = white, 1 = grey, 2 = black

    def visit(sid: str) -> str | None:
        colour[sid] = 1
        for t in idx[sid].targets():
            if t not in idx:
                continue
            if colour.get(t) == 1:
                return t
            if t not in colour and (hit := visit(t)):
                return hit
        colour[sid] = 2
        return None

    for sid in idx:
        if sid not in colour and (hit := visit(sid)):
            return hit
    return None


def validate(wf: Workflow, catalog: Catalog) -> ValidationResult:
    res = ValidationResult()
    if wf.trigger is None:
        res.errors.append(Issue(code="NO_TRIGGER", message="workflow has no trigger"))
    for sid, n in Counter(s.id for s in wf.nodes()).items():
        if n > 1:
            res.errors.append(Issue(code="DUPLICATE_ID", step_id=sid, message=f"id {sid} used {n} times"))
    idx = wf.index()
    for s in wf.nodes():
        for t in s.targets():
            if t not in idx:
                res.errors.append(
                    Issue(code="DANGLING_POINTER", step_id=s.id, message=f"{s.id} points at missing step {t}")
                )
        node = catalog.get(s.node_type)
        if node is None:
            continue
        if node.kind == "condition" and not (s.on_true and s.on_false):
            res.errors.append(
                Issue(code="CONDITION_MISSING_BRANCH", step_id=s.id, message=f"{s.id} needs both branches")
            )
        res.gaps += [Gap(step_id=s.id, param=p) for p in node.required_params if is_empty(s.params.get(p))]
    if (at := _find_cycle(wf)) is not None:
        res.errors.append(Issue(code="CYCLE", step_id=at, message=f"cycle through step {at}"))
    return res
