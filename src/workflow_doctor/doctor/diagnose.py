from __future__ import annotations

from typing import Literal

from pydantic import BaseModel

from ..model import Catalog, Run, Workflow
from .checks import ALL_CHECKS, Finding
from .drift import DriftReport, detect_drift_report
from .forensics import RunFailure, run_failures

Risk = Literal["high", "medium", "low", "none"]
_LEVELS: list[Risk] = ["none", "low", "medium", "high"]


class Diagnosis(BaseModel):
    findings: list[Finding]
    risk: Risk
    step_chain_in_run_order: list[str]
    orphans: list[str]
    recent_failures: list[RunFailure]
    drift: dict[str, list[str]]  # changed param keys per step (compact)
    drift_report: DriftReport  # added/removed/changed steps with as-built values


def derive_risk(findings: list[Finding], runs: list[Run]) -> Risk:
    """Worst finding sets the level. A history of failed runs proves the problem is live,
    so it bumps low/medium up one notch."""
    level = max((_LEVELS.index(f.severity) for f in findings), default=0)
    if 0 < level < 3 and any(r.status == "failed" for r in runs):
        level += 1
    return _LEVELS[level]


def diagnose(wf: Workflow, catalog: Catalog, runs: list[Run]) -> Diagnosis:
    findings = [f for check in ALL_CHECKS for f in check(wf, catalog, runs)]
    chain = wf.walk()
    report = detect_drift_report(wf)
    return Diagnosis(
        findings=findings,
        risk=derive_risk(findings, runs),
        step_chain_in_run_order=chain,
        orphans=[sid for sid in wf.steps if sid not in chain] if wf.trigger else [],
        recent_failures=run_failures(wf, runs)[:5],
        drift={sid: list(c.params) for sid, c in report.steps_changed.items() if c.params},
        drift_report=report,
    )
