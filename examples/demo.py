"""End-to-end story with fakes: build a workflow from a sentence, then diagnose a broken one."""

import asyncio
import json
from pathlib import Path

from workflow_doctor import (
    Card,
    Edit,
    FakeExtractor,
    FakeIntentJudge,
    FakeNarrator,
    InMemoryStore,
    Intent,
    NodeIntent,
    PublishedWorkflowError,
    PublishRefused,
    Run,
    Workflow,
    analyse,
    apply_edit,
    build,
    build_and_store,
    copy_workflow,
    diagnose,
    drift_edits,
    find_by_name,
    intent_drift,
    load_catalog,
    narrate,
    publish,
    revert,
)

CATALOG = load_catalog()
SENTENCE = ("when a task becomes overdue, if priority is high email the owner, otherwise wait 1 day "
            "and notify the project lead, and also DM the owner on Slack")


def scripted_intent() -> Intent:
    """What a real model would extract: structure and intent only, no ids."""
    n = NodeIntent
    return Intent(
        trigger=n(ref="trig", node_type="TaskOverdue", then="check"),
        steps=[
            n(ref="check", node_type="FieldEquals", params={"field": "priority", "value": "high"},
              if_true="mail", if_false="wait"),
            n(ref="mail", node_type="SendEmail",
              params={"to": "{{trigger.owner_email}}", "subject": "Overdue: {{trigger.task_title}}"}),
            n(ref="wait", node_type="Delay", params={"minutes": 1440}, then="ping"),
            n(ref="ping", node_type="Notify",
              params={"user": "{{trigger.project_lead}}", "message": "{{trigger.task_title}} is still overdue"}),
        ],
        unsupported=["send a Slack DM (no such node in the catalog)"],
    )


def show_build() -> None:
    print("=== 1. BUILD ===")
    print(f"request: {SENTENCE}\n")
    res = asyncio.run(build(SENTENCE, FakeExtractor(scripted_intent()), CATALOG))
    wf = res.workflow
    label = {s.id: f"{s.id[:8]} {s.node_type}" for s in wf.nodes()}
    print(f"status: {wf.status}")
    for sid in wf.walk():
        s = wf.index()[sid]
        edges = [f"{k} -> {label[v]}" for k, v in (("next", s.next), ("TRUE", s.on_true), ("FALSE", s.on_false)) if v]
        print(f"  {label[sid]:<28} {'; '.join(edges) or '(end)'}")
    print("\ngaps (fill these):", [f"{label[g.step_id]}.{g.param}" for g in res.gaps])
    print("unsupported:", res.unsupported)
    print("blocking errors:", [e.code for e in res.errors] or "none")


def show_diagnosis() -> None:
    print("\n=== 2. DIAGNOSE 'Onboarding' ===")
    data = json.loads((Path(__file__).parent.parent / "tests/golden/onboarding_broken.json").read_text())
    wf, runs = Workflow(**data["workflow"]), [Run(**r) for r in data["runs"]]
    d = diagnose(wf, CATALOG, runs)
    print(f"risk: {d.risk.upper()}   chain: {' -> '.join(d.step_chain_in_run_order)}   orphans: {d.orphans}")
    print("\nfindings:")
    for f in d.findings:
        print(f"  [{f.severity:<6}] {f.code:<22} {f.step_id or '-':<3} {f.message}")
    print("\nwhere each run died:")
    for r in d.recent_failures:
        print(f"  {r.run_id}: {r.explanation}")
    print("\ndrift since build (builder-set keys only; the engine's extra 'retries' key is ignored):")
    print(" ", d.drift)

    cards = [Card(
        root_cause="Every run dies at s2 (SendEmail): its 'to' setting was blanked after the workflow was built.",
        evidence=["r1 and r2 died on step s2: recipient address is empty", "'to' drifted from {{t1.owner_email}} to ''"],
        fix=["Open step s2 (SendEmail).", "Set 'to' back to {{t1.owner_email}}.",
             "Set 'minutes' on step s3 (Delay) above 0, and 'status' on s4 to 'done'."],
        impact="Until fixed, the welcome email never sends and r3-style runs keep failing.",
    )]
    print("\nfix cards (fake narrator; swap in a real one without touching anything else):")
    for c in asyncio.run(narrate(d, FakeNarrator(cards))):
        print(f"\n  CAUSE:    {c.root_cause}")
        print("  EVIDENCE: " + "\n            ".join(c.evidence))
        print("  FIX:      " + "\n            ".join(f"{i}. {s}" for i, s in enumerate(c.fix, 1)))
        print(f"  IMPACT:   {c.impact}")


def show_agent_surface() -> None:
    print("\n=== 3. WHAT A CONVERSATIONAL AGENT CALLS (pure functions; the agent adds confirmation) ===")
    store = InMemoryStore()
    built = asyncio.run(build_and_store(store, SENTENCE, FakeExtractor(scripted_intent())))
    wf = built.workflow
    print(f"stored as {wf.status!r}; as-built snapshot recorded: {bool(wf.built_from.as_built_steps)}")

    print("\nfind 'overdue':", find_by_name(store, "overdue").outcome, "| find 'payroll':", find_by_name(store, "payroll").outcome)

    delay = next(s for s in wf.steps.values() if s.node_type == "Delay")
    cp = copy_workflow(wf, [Edit(step_id=delay.id, set_params={"minutes": 60})], name="Escalate overdue (copy)")
    print(f"copy: {len(cp.index())} steps, all ids new: {not set(cp.index()) & set(wf.index())}, wait is now "
          f"{next(s for s in cp.steps.values() if s.node_type == 'Delay').params['minutes']} min")

    broken = apply_edit(wf, Edit(step_id=delay.id, set_params={"minutes": 0}))
    store.save(broken)
    print("after a bad edit the Doctor says:", [f.code for f in analyse(store, wf.id).findings])
    d = analyse(store, wf.id).drift_report.steps_changed[delay.id].params["minutes"]
    print(f"drift keeps the as-built value: minutes was {d.as_built}, is now {d.live}")
    print("proposed fix:", drift_edits(broken)[0].set_params)
    print("revert restores the as-built graph:", revert(broken).model_dump() == wf.model_dump())

    try:
        publish(wf, CATALOG)
    except PublishRefused as e:
        print("publish refused while a required setting is empty:", str(e).split(": ", 1)[1].split(".")[-1], "is missing")
    mail = next(s for s in wf.steps.values() if s.node_type == "SendEmail")
    live = publish(apply_edit(wf, Edit(step_id=mail.id, set_params={"body": "Please take a look."})), CATALOG)
    try:
        apply_edit(live, Edit(step_id=delay.id, set_params={"minutes": 1}))
    except PublishedWorkflowError as e:
        print("published workflows are immutable:", e)

    judge = FakeIntentJudge(["The request says DM the owner on Slack; the workflow does not (unsupported at build time)."])
    report = asyncio.run(intent_drift(wf, judge))
    print("intent mismatches vs the original request:", report.intent_mismatches)


if __name__ == "__main__":
    show_build()
    show_diagnosis()
    show_agent_surface()
