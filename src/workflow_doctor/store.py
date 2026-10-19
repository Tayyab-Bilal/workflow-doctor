"""The seam to the workflow engine. Production talks to its REST API; tests use the in-memory fake."""

from __future__ import annotations

import uuid
from typing import Protocol

from .builder.build import BuildResult, build
from .builder.extract import Extractor
from .doctor.diagnose import Diagnosis, diagnose
from .model import Catalog, Run, Workflow, load_catalog


class WorkflowStore(Protocol):
    # Simplification: synchronous calls; a real HTTP-backed store would be async.
    def catalog(self) -> Catalog: ...
    def list_workflows(self) -> list[Workflow]: ...
    def get_workflow(self, workflow_id: str) -> Workflow: ...
    def get_runs(self, workflow_id: str) -> list[Run]: ...
    def create(self, wf: Workflow) -> Workflow: ...
    def save(self, wf: Workflow) -> Workflow: ...


class InMemoryStore:
    """Fake engine. `create` always stores a draft, as the real endpoints do."""

    def __init__(self, workflows: list[Workflow] | None = None, runs: dict[str, list[Run]] | None = None,
                 catalog: Catalog | None = None) -> None:
        self._catalog = catalog or load_catalog()
        self._workflows = {w.id: w.model_copy(deep=True) for w in workflows or []}
        self._runs = {k: list(v) for k, v in (runs or {}).items()}

    def catalog(self) -> Catalog:
        return self._catalog

    def list_workflows(self) -> list[Workflow]:
        return [w.model_copy(deep=True) for w in self._workflows.values()]

    def get_workflow(self, workflow_id: str) -> Workflow:
        return self._workflows[workflow_id].model_copy(deep=True)

    def get_runs(self, workflow_id: str) -> list[Run]:
        return list(self._runs.get(workflow_id, []))

    def create(self, wf: Workflow) -> Workflow:
        stored = wf.model_copy(deep=True, update={"status": "draft", "id": wf.id or str(uuid.uuid4())})
        self._workflows[stored.id] = stored
        return stored.model_copy(deep=True)

    def save(self, wf: Workflow) -> Workflow:
        if wf.id not in self._workflows:
            raise KeyError(wf.id)
        self._workflows[wf.id] = wf.model_copy(deep=True)
        return wf

    def add_run(self, workflow_id: str, run: Run) -> None:
        self._runs.setdefault(workflow_id, []).append(run)


def analyse(store: WorkflowStore, workflow_id: str) -> Diagnosis:
    """The 'analyse by workflow id' endpoint: load workflow, run history and catalog, then diagnose."""
    return diagnose(store.get_workflow(workflow_id), store.catalog(), store.get_runs(workflow_id))


async def build_and_store(
    store: WorkflowStore, text: str, extractor: Extractor, source_ref: str | None = None
) -> BuildResult:
    """The 'build' endpoint: extract, assemble, validate, and create a draft with its provenance.
    Blocking errors mean nothing is created; gaps do not (the user can still fill them)."""
    result = await build(text, extractor, store.catalog(), source_ref)
    if not result.errors:
        result.workflow = store.create(result.workflow)
    return result
