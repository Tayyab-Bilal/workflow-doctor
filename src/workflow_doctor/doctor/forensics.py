from __future__ import annotations

from pydantic import BaseModel

from ..model import Run, Workflow


class RunFailure(BaseModel):
    run_id: str
    step_id: str | None
    explanation: str


def run_failures(wf: Workflow, runs: list[Run]) -> list[RunFailure]:
    """Newest first. Names the exact step each failed run died on."""
    idx = wf.index()
    out = []
    for r in sorted(runs, key=lambda r: r.started_at, reverse=True):
        if r.status != "failed":
            continue
        step_id = r.failed_step_id or (r.executed_step_ids[-1] if r.executed_step_ids else None)
        if step_id is None:
            out.append(RunFailure(run_id=r.run_id, step_id=None,
                                  explanation=f"failed before any step ran: {r.error}"))
            continue
        step = idx.get(step_id)
        what = step.node_type if step else "step no longer in workflow"
        out.append(RunFailure(run_id=r.run_id, step_id=step_id,
                              explanation=f"died on step {step_id} ({what}): {r.error}"))
    return out
