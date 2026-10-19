"""One minimal broken workflow per check code. Each must raise exactly that code and nothing else."""

import pytest

from helpers import CATALOG, R, S, W, codes, load_golden, ok_wf
from workflow_doctor import Run, diagnose
from workflow_doctor.model import Provenance

P = {"user": "u", "message": "m"}


def test_no_trigger():
    assert codes(W(None)) == ["NO_TRIGGER"]


def test_trigger_not_in_catalog():
    assert codes(W(S("t1", "Bogus", next="s1"), S("s1", "Notify", P))) == ["TRIGGER_NOT_IN_CATALOG"]


def test_action_used_as_trigger_not_in_catalog():
    wf = W(S("t1", "Notify", P, next="s1"), S("s1", "Notify", P))
    assert codes(wf) == ["TRIGGER_NOT_IN_CATALOG"]


def test_trigger_leads_nowhere():
    assert codes(W(S("t1", "TaskCreated"))) == ["TRIGGER_DEAD_END"]


def test_step_node_removed():
    assert codes(W(S("t1", "TaskCreated", next="s1"), S("s1", "Gone"))) == ["STEP_NODE_REMOVED"]


def test_empty_required_param():
    wf = W(S("t1", "TaskCreated", next="s1"), S("s1", "SendEmail", {"to": " ", "subject": "s", "body": "b"}))
    assert codes(wf) == ["EMPTY_REQUIRED_PARAM"]


def test_invalid_status_param():
    wf = W(S("t1", "TaskCreated", next="s1"), S("s1", "UpdateTaskStatus", {"task_id": "1", "status": "finished"}))
    assert codes(wf) == ["INVALID_STATUS_PARAM"]


def test_valid_status_value_is_fine():
    wf = W(S("t1", "TaskCreated", next="s1"), S("s1", "UpdateTaskStatus", {"task_id": "1", "status": "done"}))
    assert codes(wf) == []


def test_dangling_ref():
    assert codes(W(S("t1", "TaskCreated", next="ghost"))) == ["BROKEN_POINTER"]


def test_branch_leads_nowhere():
    wf = W(S("t1", "TaskCreated", next="c"),
           S("c", "FieldEquals", {"field": "f", "value": "v"}, on_true="s1"), S("s1", "Notify", P))
    assert codes(wf) == ["CONDITION_DEAD_END"]


def test_condition_not_allowed():
    wf = W(S("t1", "TaskCreated", next="s1"),
           S("s1", "Notify", P, on_true="s2", on_false="s2"), S("s2", "Notify", P))
    assert codes(wf) == ["CONDITION_NOT_ALLOWED"]


def test_zero_delay():
    wf = W(S("t1", "TaskCreated", next="s1"), S("s1", "Delay", {"minutes": 0}))
    assert codes(wf) == ["ZERO_DELAY"]


def test_unreachable_step():
    wf = W(S("t1", "TaskCreated", next="s1"), S("s1", "Notify", P), S("s2", "Notify", P))
    assert codes(wf) == ["UNREACHABLE_STEP"]


def test_reachability_follows_both_branches():
    wf = W(S("t1", "TaskCreated", next="c"),
           S("c", "FieldEquals", {"field": "f", "value": "v"}, on_true="a", on_false="only_false"),
           S("a", "Notify", P), S("only_false", "Notify", P))
    assert codes(wf) == []
    assert diagnose(wf, CATALOG, []).orphans == []


def test_all_runs_failed():
    runs = [R("r1", "failed", 0, failed_step_id="s1", error="x"), R("r2", "failed", 1, failed_step_id="s1", error="x")]
    assert codes(ok_wf(status="active"), runs) == ["ALL_RUNS_FAILED"]


def test_last_run_failed():
    runs = [R("r1", "succeeded", 0), R("r2", "failed", 1, failed_step_id="s1", error="boom")]
    assert codes(ok_wf(status="active"), runs) == ["LAST_RUN_FAILED"]


def test_old_failure_with_recent_success_is_not_last_run_failed():
    runs = [R("r1", "failed", 0, failed_step_id="s1", error="boom"), R("r2", "succeeded", 1)]
    assert codes(ok_wf(status="active"), runs) == []


def test_active_never_ran():
    assert codes(ok_wf(status="active")) == ["ACTIVE_NEVER_RAN"]


def test_draft_never_ran_is_fine():
    assert codes(ok_wf(status="draft")) == []


def test_dead_variable():
    wf = W(S("t1", "TaskCreated", next="s1"), S("s1", "Notify", {"user": "u", "message": "{{ghost.x}}"}))
    assert codes(wf) == ["DEAD_VARIABLE"]


def test_variable_from_downstream_step_is_dead():
    wf = W(S("t1", "TaskCreated", next="s1"),
           S("s1", "Notify", {"user": "u", "message": "{{s2.task_id}}"}, next="s2"),
           S("s2", "CreateTask", {"title": "t", "project_id": "p"}))
    assert codes(wf) == ["DEAD_VARIABLE"]


def test_variable_from_trigger_and_earlier_step_is_alive():
    wf = W(S("t1", "TaskCreated", next="s1"),
           S("s1", "CreateTask", {"title": "{{t1.task_title}}", "project_id": "p"}, next="s2"),
           S("s2", "Notify", {"user": "u", "message": "{{s1.task_id}}"}))
    assert codes(wf) == []


def test_gap_matches_exact_step():
    mail = {"subject": "s", "body": "b"}
    wf = W(S("t1", "TaskCreated", next="s1"), S("s1", "SendEmail", {**mail, "to": "a@b.c"}, next="s2"),
           S("s2", "SendEmail", {**mail, "to": ""}))
    findings = diagnose(wf, CATALOG, []).findings
    assert [(f.code, f.step_id) for f in findings] == [("EMPTY_REQUIRED_PARAM", "s2")]


def test_engine_backfill_is_not_drift():
    wf = ok_wf()
    wf.built_from = Provenance(source_text="x", as_built_params={"s1": {"user": "u", "message": "m"}})
    wf.steps["s1"].params["retries"] = 3  # engine added a default
    assert diagnose(wf, CATALOG, []).drift == {}


def test_changed_builder_key_is_drift():
    wf = ok_wf()
    wf.built_from = Provenance(source_text="x", as_built_params={"s1": {"user": "u", "message": "m"}})
    wf.steps["s1"].params["message"] = "edited"
    assert diagnose(wf, CATALOG, []).drift == {"s1": ["message"]}


def test_key_removed_since_build_is_drift():
    wf = ok_wf()
    wf.built_from = Provenance(source_text="x", as_built_params={"s1": {"user": "u", "message": "m"}})
    del wf.steps["s1"].params["user"]
    assert diagnose(wf, CATALOG, []).drift == {"s1": ["user"]}


@pytest.mark.parametrize("name", ["healthy", "onboarding_broken", "dead_variable"])
def test_golden_workflows(name):
    wf, runs, expected = load_golden(name)
    assert sorted(codes(wf, runs)) == sorted(expected)


def test_healthy_workflow_has_no_findings():
    wf, runs, _ = load_golden("healthy")
    d = diagnose(wf, CATALOG, runs)
    assert d.findings == [] and d.risk == "none" and d.orphans == []
    assert d.step_chain_in_run_order == ["t1", "c1", "s_email", "s_delay", "s_notify"]


def test_every_check_code_is_covered_by_a_test():
    from workflow_doctor.doctor.checks import ALL_CHECKS
    assert len(ALL_CHECKS) == 15
    assert isinstance(R("x"), Run)
