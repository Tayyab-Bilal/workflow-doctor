"""Three-way drift: live workflow vs as-built (deterministic) and vs the original request (judge)."""

from __future__ import annotations

from typing import Any, Protocol

from pydantic import BaseModel, Field

from ..model import Workflow

POINTERS = ("next", "on_true", "on_false")


class Change(BaseModel):
    as_built: Any
    live: Any


class StepChange(BaseModel):
    node_type: Change | None = None
    params: dict[str, Change] = Field(default_factory=dict)
    pointers: dict[str, Change] = Field(default_factory=dict)


class DriftReport(BaseModel):
    steps_added: list[str] = Field(default_factory=list)
    steps_removed: list[str] = Field(default_factory=list)
    steps_changed: dict[str, StepChange] = Field(default_factory=dict)
    intent_mismatches: list[str] = Field(default_factory=list)  # filled by the judge only

    @property
    def clean(self) -> bool:
        return not (self.steps_added or self.steps_removed or self.steps_changed or self.intent_mismatches)


def detect_drift_report(wf: Workflow) -> DriftReport:
    """Live vs as-built, with the as-built values. Params are compared only on keys the builder
    set: keys the engine added later (defaults, backfill) are not drift, and flagging them
    would be a false finding. Type and pointer changes need the as-built graph snapshot."""
    if not wf.built_from:
        return DriftReport()
    idx, built = wf.index(), wf.built_from
    report = DriftReport(
        steps_added=[sid for sid in idx if sid not in built.as_built_params],
        steps_removed=[sid for sid in built.as_built_params if sid not in idx],
    )
    for sid, params in built.as_built_params.items():
        if sid not in idx:
            continue
        live, change = idx[sid], StepChange()
        change.params = {k: Change(as_built=v, live=live.params.get(k)) for k, v in params.items()
                         if live.params.get(k) != v}
        if (snap := built.as_built_steps.get(sid)) is not None:
            if snap.node_type != live.node_type:
                change.node_type = Change(as_built=snap.node_type, live=live.node_type)
            change.pointers = {p: Change(as_built=getattr(snap, p), live=getattr(live, p)) for p in POINTERS
                               if getattr(snap, p) != getattr(live, p)}
        if change.node_type or change.params or change.pointers:
            report.steps_changed[sid] = change
    return report


def detect_drift(wf: Workflow) -> dict[str, list[str]]:
    """Changed param keys per step: the compact form `Diagnosis.drift` carries."""
    return {sid: list(c.params) for sid, c in detect_drift_report(wf).steps_changed.items() if c.params}


def describe_workflow(wf: Workflow) -> str:
    """Plain-text rendering of the live workflow in run order, for the intent judge."""
    idx, lines = wf.index(), []
    for sid in wf.walk():
        s = idx[sid]
        edges = ", ".join(f"{p}={getattr(s, p)}" for p in POINTERS if getattr(s, p))
        lines.append(f"{sid}: {s.node_type} params={s.params} {edges}".rstrip())
    return "\n".join(lines)


class IntentJudge(Protocol):
    """The LLM leg of drift: does the live workflow still do what the user originally asked?
    Returns one sentence per mismatch, or an empty list."""

    async def judge(self, source_text: str, live_summary: str) -> list[str]: ...


class FakeIntentJudge:
    """Returns scripted mismatches and records what it was asked."""

    def __init__(self, mismatches: list[str] | None = None) -> None:
        self.mismatches = mismatches or []
        self.calls: list[tuple[str, str]] = []

    async def judge(self, source_text: str, live_summary: str) -> list[str]:
        self.calls.append((source_text, live_summary))
        return list(self.mismatches)


async def intent_drift(wf: Workflow, judge: IntentJudge | None = None) -> DriftReport:
    """All three legs. Without a judge, or without a recorded source request, only the
    deterministic as-built comparison runs."""
    report = detect_drift_report(wf)
    if judge is not None and wf.built_from and wf.built_from.source_text:
        report.intent_mismatches = await judge.judge(wf.built_from.source_text, describe_workflow(wf))
    return report
