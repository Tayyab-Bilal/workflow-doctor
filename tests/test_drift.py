from helpers import CATALOG, S, W
from workflow_doctor import FakeIntentJudge, diagnose, intent_drift
from workflow_doctor.model import Provenance


def built_wf():
    """Built as: trigger -> condition (TRUE s1, FALSE s2). Then edited below."""
    wf = W(S("t1", "TaskCreated", next="c"),
           S("c", "FieldEquals", {"field": "priority", "value": "high"}, on_true="s1", on_false="s2"),
           S("s1", "Notify", {"user": "lead", "message": "m"}),
           S("s2", "Delay", {"minutes": 5}))
    wf.built_from = Provenance(
        source_text="notify the lead about high priority tasks, otherwise wait five minutes",
        as_built_params={sid: dict(s.params) for sid, s in wf.index().items()},
        as_built_steps={sid: s.model_copy(deep=True) for sid, s in wf.index().items()},
        as_built_trigger_id="t1",
    )
    return wf


def test_step_removed_added_and_changed_with_as_built_values():
    wf = built_wf()
    del wf.steps["s1"]
    wf.steps["c"].on_true = None
    wf.steps["s9"] = S("s9", "Notify", {"user": "x", "message": "y"})
    wf.steps["s2"] = wf.steps["s2"].model_copy(update={"node_type": "Notify", "params": {"minutes": 5}})
    r = diagnose(wf, CATALOG, []).drift_report
    assert r.steps_removed == ["s1"] and r.steps_added == ["s9"]
    assert r.steps_changed["c"].pointers["on_true"].as_built == "s1"
    assert r.steps_changed["c"].pointers["on_true"].live is None
    assert (r.steps_changed["s2"].node_type.as_built, r.steps_changed["s2"].node_type.live) == ("Delay", "Notify")


def test_drift_on_the_false_branch_is_found():
    wf = built_wf()
    wf.steps["s2"].params["minutes"] = 0
    ch = diagnose(wf, CATALOG, []).drift_report.steps_changed["s2"].params["minutes"]
    assert (ch.as_built, ch.live) == (5, 0)


def test_engine_backfill_is_not_structural_drift():
    wf = built_wf()
    wf.steps["s2"].params["retries"] = 3
    assert diagnose(wf, CATALOG, []).drift_report.clean


def test_steps_of_the_same_type_are_told_apart_by_id():
    wf = W(S("t1", "TaskCreated", next="a"), S("a", "Notify", {"user": "u", "message": "m"}, next="b"),
           S("b", "Notify", {"user": "u", "message": "m"}))
    wf.built_from = Provenance(source_text="x", as_built_params={sid: dict(s.params) for sid, s in wf.index().items()})
    wf.steps["b"].params["message"] = "changed"
    assert list(diagnose(wf, CATALOG, []).drift_report.steps_changed) == ["b"]


async def test_intent_judge_compares_live_workflow_to_original_request():
    wf = built_wf()
    judge = FakeIntentJudge(["The request says wait five minutes, but the live workflow never waits."])
    r = await intent_drift(wf, judge)
    source, live = judge.calls[0]
    assert source.startswith("notify the lead") and "Delay" in live and "FieldEquals" in live
    assert r.intent_mismatches == judge.mismatches and not r.clean


async def test_without_a_judge_or_source_only_the_deterministic_legs_run():
    wf = built_wf()
    assert (await intent_drift(wf)).intent_mismatches == []
    wf.built_from = None
    judge = FakeIntentJudge(["x"])
    assert (await intent_drift(wf, judge)).clean and judge.calls == []
