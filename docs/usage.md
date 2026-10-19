# Usage guide

Every example here is executed by `tests/test_docs.py`, in order, sharing one namespace per file.
Reference for each name is in [api.md](api.md).

## 1. Build a workflow from text

`build` needs three things: the request, an `Extractor` (the LLM seam) and the catalog. This guide uses the
scripted `FakeExtractor`; a real one implements `async extract(text, catalog_summary) -> Intent`.

```python
import asyncio

from workflow_doctor import (
    Edit, FakeExtractor, InMemoryStore, Intent, NodeIntent, Run,
    analyse, apply_edit, build, build_and_store, diagnose, load_catalog,
)

catalog = load_catalog()
N = NodeIntent

intent = Intent(
    trigger=N(ref="t", node_type="TaskOverdue", then="check"),
    steps=[
        N(ref="check", node_type="FieldEquals", params={"field": "priority", "value": "high"},
          if_true="mail", if_false="wait"),
        N(ref="mail", node_type="SendEmail", params={"to": "{{trigger.owner_email}}", "subject": "Overdue"}),
        N(ref="wait", node_type="Delay", params={"minutes": 1440}, then="ping"),
        N(ref="ping", node_type="Notify", params={"user": "{{trigger.project_lead}}", "message": "Still overdue"}),
        N(ref="slack", node_type="SlackDM"),
    ],
    unsupported=["DM the owner on chat"],
)
text = "when a task is overdue: if high priority email the owner, otherwise wait a day and notify the lead"
result = asyncio.run(build(text, FakeExtractor(intent), catalog))

print(result.workflow.status)                      # draft, always
print([g.param for g in result.gaps])              # ['body']: the email has no body yet
print(result.unsupported)                          # what could not be built, in plain words
print([e.code for e in result.errors])             # blocking problems; empty here
```

Read the result like this. `errors` mean do not create the workflow. `gaps` mean it can be created and the user
fills the values in. `unsupported` is shown to the user so nothing is silently dropped. The model's refs
(`t`, `check`) are thrown away; every id in `result.workflow` is a fresh UUID.

## 2. Ground a real extractor

A real `Extractor` puts `catalog_summary` in its prompt. It lists the nodes, closed value sets, the condition
allow-list, each trigger's payload fields, trigger phrases and the variable syntax.

```python
from workflow_doctor import TRIGGER_MAP, resolve_trigger
from workflow_doctor.model import catalog_summary

summary = catalog_summary(catalog)
assert "Condition allow-list" in summary and "{{ref.field}}" in summary
print(resolve_trigger("A task becomes overdue"))   # TaskOverdue
print(len(TRIGGER_MAP), "phrases ->", len(set(TRIGGER_MAP.values())), "trigger types")
```

## 3. Build from a document

`build_from_document` is `build` with a reader in front. The reader turns a reference into text; the reference
is kept on the workflow's provenance.

```python
from workflow_doctor import FakeDocumentReader, build_from_document

reader = FakeDocumentReader({"onboarding-policy.txt": text})
doc_result = asyncio.run(build_from_document("onboarding-policy.txt", reader, FakeExtractor(intent), catalog))
print(doc_result.workflow.built_from.source_ref)
```

A real reader would call an OCR vendor for PDFs and images, an extractor for office files, and
speech-to-text for audio, then return the text.

## 4. Diagnose a workflow

`diagnose(workflow, catalog, runs)` is pure. Give it the workflow, the catalog and the run history.

```python
from datetime import datetime, UTC

wf = result.workflow
mail = next(s for s in wf.steps.values() if s.node_type == "SendEmail")
broken = apply_edit(wf, Edit(step_id=mail.id, set_params={"to": "", "body": "Please take a look."}))
runs = [Run(run_id="r1", started_at=datetime(2026, 3, 1, tzinfo=UTC), status="failed",
            failed_step_id=mail.id, error="recipient address is empty",
            executed_step_ids=[wf.trigger.id, wf.trigger.next])]

d = diagnose(broken, catalog, runs)
print(d.risk, [f.code for f in d.findings])
print(d.recent_failures[0].explanation)            # names the exact step the run died on
print(d.drift)                                     # {step id: [changed keys]}
print(d.drift_report.steps_changed[mail.id].params["to"].as_built)   # the value to put back
```

`Diagnosis` carries `findings` (each with a `fix` naming the step and setting), `risk`,
`step_chain_in_run_order`, `orphans`, `recent_failures`, `drift` and `drift_report`.

The 15 checks are grouped in `CHECK_GROUPS` (trigger, step and parameter, flow, execution health):

```python
from workflow_doctor.doctor.checks import CHECK_GROUPS

print({group: [c.__name__ for c in checks] for group, checks in CHECK_GROUPS.items()}["execution_health"])
```

## 5. Explain it

`narrate` always returns cards. Without a narrator, or when it raises, it builds them from the findings.

```python
from workflow_doctor import narrate

for card in asyncio.run(narrate(d)):
    print(card.root_cause, "|", card.fix[0], "|", card.impact)
```

Swap in your own `Narrator` (`async narrate(diagnosis) -> list[Card]`) to write nicer prose. The findings do not change.

## 6. Use a store: analyse by id, build as a draft

`WorkflowStore` is the seam to the engine. `InMemoryStore` is the fake. `analyse` is the "analyse by workflow id"
call; `build_and_store` is the "build" call.

```python
store = InMemoryStore()
created = asyncio.run(build_and_store(store, text, FakeExtractor(intent)))
wf_id = created.workflow.id
store.add_run(wf_id, runs[0])
print(store.get_workflow(wf_id).status)            # draft
print([f.code for f in analyse(store, wf_id).findings])
```

## 7. Calls for a conversational agent

An agent finds a workflow, diagnoses it, proposes a fix and, only after the user says yes, writes it. These
functions are the pure parts. They return new objects and never save; the caller saves. The confirm gate, consent
checking and run-history handling live in the companion [agent-kit](https://github.com/Tayyab-Bilal/agent-kit) repo.

```python
from workflow_doctor import (
    PublishedWorkflowError, copy_workflow, drift_edits, find_by_name, publish, revert,
)

found = find_by_name(store, "overdue")
print(found.outcome, [c.name[:20] for c in found.candidates])   # one: proceed; several: ask which; none: say so

wf = store.get_workflow(found.workflow_id)
mail = next(s for s in wf.steps.values() if s.node_type == "SendEmail")
store.save(apply_edit(wf, Edit(step_id=mail.id, set_params={"body": "Please take a look.", "to": ""})))
drifted = store.get_workflow(wf_id)

(proposal,) = drift_edits(drifted)                 # propose: put drifted values back
print(proposal.set_params)
fixed = apply_edit(drifted, proposal)              # done only after the user confirms

print(revert(drifted).model_dump() == wf.model_dump())   # True: back to the as-built graph

twin = copy_workflow(fixed, [Edit(step_id=mail.id, set_params={"subject": "Overdue (copy)"})])
print(twin.name, twin.status)                      # new ids, links and variables rewired, edit applied
live = publish(apply_edit(twin, Edit(step_id=next(s.id for s in twin.steps.values() if s.node_type == "SendEmail"),
                                     set_params={"to": "owner@acme.example"})), catalog)
try:
    apply_edit(live, Edit(step_id=live.trigger.id))
except PublishedWorkflowError as e:
    print("refused:", e)
```

Notes. `copy_workflow` takes edits written against the source's ids and rewrites them for the copy. It keeps the
provenance, so edits on a copy show up as drift. `publish` refuses a workflow that still has errors or gaps.
`revert` needs an as-built snapshot, which every build records. Nothing here deletes a workflow.

## 8. Intent drift against the original request

Deterministic drift tells you what changed since the build. Whether the workflow still does what the user asked
needs an LLM, so it sits behind `IntentJudge`.

```python
from workflow_doctor import FakeIntentJudge, intent_drift

judge = FakeIntentJudge(["The request says notify the lead, but the notify step was removed."])
report = asyncio.run(intent_drift(drifted, judge))
print(report.steps_changed.keys() == {mail.id}, report.intent_mismatches)
print(judge.calls[0][0][:30])                      # the original request the judge was shown
```

A real judge implements `async judge(source_text, live_summary) -> list[str]`, one sentence per mismatch.

## Running the whole story

```bash
.venv/bin/python examples/demo.py
```
