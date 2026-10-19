from helpers import CATALOG, S, W, ok_wf
from workflow_doctor import validate


def err_codes(wf):
    return [e.code for e in validate(wf, CATALOG).errors]


def test_valid_workflow_has_no_errors_or_gaps():
    res = validate(ok_wf(), CATALOG)
    assert res.errors == [] and res.gaps == []


def test_cycle_detected_dfs():
    wf = W(S("t1", "TaskCreated", next="a"), S("a", "Notify", {"user": "u", "message": "m"}, next="b"),
           S("b", "Notify", {"user": "u", "message": "m"}, next="a"))
    assert err_codes(wf) == ["CYCLE"]


def test_self_loop_is_a_cycle():
    wf = W(S("t1", "TaskCreated", next="a"), S("a", "Notify", {"user": "u", "message": "m"}, next="a"))
    assert err_codes(wf) == ["CYCLE"]


def test_diamond_is_not_a_cycle():
    p = {"user": "u", "message": "m"}
    wf = W(S("t1", "TaskCreated", next="c"),
           S("c", "FieldEquals", {"field": "f", "value": "v"}, on_true="a", on_false="b"),
           S("a", "Notify", p, next="d"), S("b", "Notify", p, next="d"), S("d", "Notify", p))
    assert err_codes(wf) == []


def test_duplicate_ids_rejected():
    p = {"user": "u", "message": "m"}
    wf = W(S("t1", "TaskCreated", next="a"), S("a", "Notify", p))
    wf.steps["b"] = S("a", "Notify", p)  # second step reusing id "a"
    assert err_codes(wf) == ["DUPLICATE_ID"]


def test_dangling_pointer():
    wf = W(S("t1", "TaskCreated", next="ghost"))
    assert err_codes(wf) == ["DANGLING_POINTER"]


def test_missing_trigger_and_missing_branch():
    assert err_codes(W(None)) == ["NO_TRIGGER"]
    wf = W(S("t1", "TaskCreated", next="c"),
           S("c", "FieldEquals", {"field": "f", "value": "v"}, on_true="t1"))
    assert "CONDITION_MISSING_BRANCH" in err_codes(wf)
