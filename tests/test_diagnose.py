from helpers import CATALOG, R, S, W, load_golden, ok_wf
from workflow_doctor import Card, FakeNarrator, diagnose, narrate
from workflow_doctor.doctor.narrate import fallback_cards

ZERO = W(S("t1", "TaskCreated", next="s1"), S("s1", "Delay", {"minutes": 0}))
FAILED = R("rf", "failed", 0, failed_step_id="s1", error="x")
OK = R("ro", "succeeded", 1)


def risk(wf, runs=()):
    return diagnose(wf, CATALOG, list(runs)).risk


def test_failed_before_any_step():
    wf, runs, _ = load_golden("onboarding_broken")
    d = diagnose(wf, CATALOG, runs)
    by_run = {f.run_id: f for f in d.recent_failures}
    assert by_run["r3"].explanation == "failed before any step ran: trigger payload rejected"
    assert by_run["r3"].step_id is None


def test_failure_names_exact_step():
    wf, runs, _ = load_golden("onboarding_broken")
    by_run = {f.run_id: f for f in diagnose(wf, CATALOG, runs).recent_failures}
    assert by_run["r1"].step_id == "s2"
    assert "step s2 (SendEmail)" in by_run["r1"].explanation
    assert [f.run_id for f in diagnose(wf, CATALOG, runs).recent_failures] == ["r3", "r2", "r1"]


def test_risk_level_derivation():
    assert risk(ok_wf()) == "none"
    assert risk(ZERO) == "low"
    unreachable = W(S("t1", "TaskCreated", next="s1"), S("s1", "Delay", {"minutes": 5}), S("s2", "Delay", {"minutes": 5}))
    assert risk(unreachable) == "medium"
    assert risk(W(S("t1", "TaskCreated", next="ghost"))) == "high"
    # run health: a failure in history bumps low->medium and medium->high
    assert risk(ZERO, [FAILED, OK]) == "medium"
    assert risk(unreachable, [FAILED, OK]) == "high"
    # ...but never invents risk for a clean workflow
    assert risk(ok_wf(), [FAILED, OK]) == "none"


def test_orphans_and_chain():
    wf = W(S("t1", "TaskCreated", next="s1"), S("s1", "Delay", {"minutes": 5}), S("s2", "Delay", {"minutes": 5}))
    d = diagnose(wf, CATALOG, [])
    assert d.orphans == ["s2"] and d.step_chain_in_run_order == ["t1", "s1"]


class ExplodingNarrator:
    async def narrate(self, diagnosis):
        raise RuntimeError("llm down")


async def test_narrator_failure_falls_back():
    wf, runs, _ = load_golden("onboarding_broken")
    d = diagnose(wf, CATALOG, runs)
    cards = await narrate(d, ExplodingNarrator())
    assert cards == fallback_cards(d) and len(cards) == len(d.findings) > 0
    assert all(c.fix and c.impact and c.evidence for c in cards)


async def test_narrator_output_used_when_it_works():
    wf, runs, _ = load_golden("onboarding_broken")
    d = diagnose(wf, CATALOG, runs)
    scripted = [Card(root_cause="r", evidence=["e"], fix=["f"], impact="i")]
    assert await narrate(d, FakeNarrator(scripted)) == scripted


async def test_no_narrator_uses_deterministic_text():
    d = diagnose(ZERO, CATALOG, [])
    assert (await narrate(d))[0].root_cause == d.findings[0].message
