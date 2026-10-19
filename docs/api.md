# API reference

All names import from `workflow_doctor`. Functions marked **called by the agent** are the pure operations a
conversational agent (such as the companion [agent-kit](https://github.com/Tayyab-Bilal/agent-kit) repo) uses as tools. They never ask for
confirmation and never save. Confirm-before-write, consent checking and run-history SQLite handling live in
agent-kit. Examples: [usage.md](usage.md).

```python
import workflow_doctor

print(len(workflow_doctor.__all__), "public names")
```

## Models

| Name | Description |
|---|---|
| `Workflow(id, name, status, trigger, steps, built_from)` | `status` is `draft`, `active`, `paused` or `published`. `steps` is a dict keyed by id. Methods: `nodes()`, `index()`, `walk()` (BFS over `next`, `on_true`, `on_false`). |
| `Step(id, node_type, params, next, on_true, on_false)` | One node. `targets()` lists its pointers. |
| `Run(run_id, started_at, status, failed_step_id, error, executed_step_ids)` | One execution. |
| `Provenance` | `source_text`, `source_ref`, `as_built_params`, `as_built_steps`, `as_built_trigger_id`. Recorded at build; used by drift and revert. |
| `CatalogNode` | `node_type`, `kind` (`trigger`/`action`/`condition`), `required_params`, `optional_params`, `outputs`, `allowed_values`. |
| `load_catalog() -> dict[str, CatalogNode]` | The bundled Acme catalog (28 nodes, 12 triggers). |
| `catalog_summary(catalog) -> str` (`workflow_doctor.model`) | Extractor grounding text: nodes, allowed values, condition allow-list, trigger payload fields, trigger phrases, variable syntax. |
| `TRIGGER_MAP`, `resolve_trigger(phrase) -> str \| None` | Natural phrase to trigger type. Pinned to the catalog by a test. |

## Build

| Signature | Description |
|---|---|
| `async build(text, extractor, catalog, source_ref=None) -> BuildResult` | Extract, assemble, validate. Always a draft. |
| `BuildResult(workflow, gaps, unsupported, errors)` | `gaps`: `Gap(step_id, param)`. `errors`: `Issue(code, step_id, message)`. |
| `async build_from_document(doc_ref, reader, extractor, catalog) -> BuildResult` | `build` on the reader's text; keeps `doc_ref` as `source_ref`. |
| `validate(workflow, catalog) -> ValidationResult` | `errors` block, `gaps` do not. Codes: `NO_TRIGGER`, `DUPLICATE_ID`, `DANGLING_POINTER`, `CONDITION_MISSING_BRANCH`, `CYCLE`. |
| `Extractor` (Protocol) | `async extract(text, catalog_summary) -> Intent`. |
| `FakeExtractor(scripted_intent)` | Returns the scripted `Intent`; records `calls`. |
| `Intent(trigger, steps, unsupported)` / `NodeIntent(ref, node_type, params, then, if_true, if_false)` | What the model returns. Any `id` it adds is dropped. |
| `DocumentReader` (Protocol) | `async read(doc_ref) -> str`. |
| `FakeDocumentReader(docs: dict[str, str])` | Serves text from a dict. |

## Diagnose

| Signature | Description |
|---|---|
| `diagnose(workflow, catalog, runs) -> Diagnosis` | Pure. 15 checks, risk, chain, orphans, failures, drift. |
| `Diagnosis` | `findings`, `risk` (`high`/`medium`/`low`/`none`), `step_chain_in_run_order`, `orphans`, `recent_failures` (`RunFailure(run_id, step_id, explanation)`), `drift`, `drift_report`. |
| `Finding` (`workflow_doctor.doctor.checks`) | `code`, `severity`, `step_id`, `message`, `fix`. |
| `CHECK_GROUPS`, `ALL_CHECKS` (`workflow_doctor.doctor.checks`) | The 15 checks in 4 groups: `trigger`, `step_parameter`, `flow`, `execution_health`. |
| `async narrate(diagnosis, narrator=None) -> list[Card]` | Cards with `root_cause`, `evidence`, `fix`, `impact`. Falls back to deterministic cards. |
| `Narrator` (Protocol), `FakeNarrator(cards)` | `async narrate(diagnosis) -> list[Card]`. |
| `DriftReport` | `steps_added`, `steps_removed`, `steps_changed` (`StepChange(node_type, params, pointers)`, each change is `Change(as_built, live)`), `intent_mismatches`, `clean`. |
| `async intent_drift(workflow, judge=None) -> DriftReport` | Adds the judge's mismatches to the as-built comparison. |
| `IntentJudge` (Protocol), `FakeIntentJudge(mismatches)` | `async judge(source_text, live_summary) -> list[str]`. |

## Store

| Signature | Description |
|---|---|
| `WorkflowStore` (Protocol) | `catalog()`, `list_workflows()`, `get_workflow(id)`, `get_runs(id)`, `create(wf)`, `save(wf)`. |
| `InMemoryStore(workflows=None, runs=None, catalog=None)` | Fake engine. `create` always stores a draft. Extra: `add_run(workflow_id, run)`. |
| `analyse(store, workflow_id) -> Diagnosis` | The "analyse by id" call: loads workflow, runs and catalog, then `diagnose`. |
| `async build_and_store(store, text, extractor, source_ref=None) -> BuildResult` | The "build" call: creates a draft with provenance unless there are blocking errors. |

## Agent operations (called by the agent)

| Signature | Description |
|---|---|
| `find_by_name(store, name) -> FindResult` | `outcome` is `one` (proceed, `workflow_id` set), `several` (ask the user, see `candidates`) or `none`. Exact name wins; otherwise substring. |
| `copy_workflow(wf, edits=None, name=None) -> Workflow` | New draft: new ids for the workflow and every step, links and `{{variables}}` rewired, edits (against source ids) applied in the same call, provenance kept. |
| `apply_edit(wf, edit) -> Workflow` | Edited copy. Raises `PublishedWorkflowError` for published workflows and `EditError` for an unknown step. |
| `Edit(step_id, set_params, set_pointers)` | Set params and/or pointers (`next`, `on_true`, `on_false`) on one step; a pointer of `None` clears it. |
| `drift_edits(wf) -> list[Edit]` | Proposed fix for param drift: set each drifted key back to its as-built value. |
| `publish(wf, catalog) -> Workflow` | Status `published`. Raises `PublishRefused` if there are errors or gaps. |
| `revert(wf) -> Workflow` | Restores the last as-built graph. Raises `RevertUnavailable` without a snapshot and `PublishedWorkflowError` if published. |

There is no delete operation by design.

## Exceptions

`EditError` (base), `PublishedWorkflowError(EditError)`, `PublishRefused`, `RevertUnavailable`.
