import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

from workflow_doctor import Run, Step, Workflow, diagnose, load_catalog

CATALOG = load_catalog()


def S(id: str, node_type: str, params: dict | None = None, **pointers) -> Step:
    return Step(id=id, node_type=node_type, params=params or {}, **pointers)


def W(trigger: Step | None, *steps: Step, status: str = "draft", built_from=None) -> Workflow:
    return Workflow(id="wf", name="t", status=status, trigger=trigger,
                    steps={s.id: s for s in steps}, built_from=built_from)


def ok_wf(**kw) -> Workflow:
    """Smallest healthy workflow: every broken-workflow test starts from a tweak of this."""
    return W(S("t1", "TaskCreated", next="s1"), S("s1", "Notify", {"user": "u", "message": "m"}), **kw)


def R(run_id: str, status: str = "succeeded", day: int = 0, **kw) -> Run:
    return Run(run_id=run_id, started_at=datetime(2026, 3, 1, tzinfo=UTC) + timedelta(days=day), status=status, **kw)


def codes(wf: Workflow, runs: list[Run] | None = None) -> list[str]:
    return [f.code for f in diagnose(wf, CATALOG, runs or []).findings]


def load_golden(name: str) -> tuple[Workflow, list[Run], list[str]]:
    d = json.loads((Path(__file__).parent / "golden" / f"{name}.json").read_text())
    return Workflow(**d["workflow"]), [Run(**r) for r in d["runs"]], d["expected_codes"]
