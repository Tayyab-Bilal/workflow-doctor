import pytest

from helpers import CATALOG, load_golden
from workflow_doctor import (
    FakeDocumentReader,
    FakeExtractor,
    InMemoryStore,
    Intent,
    NodeIntent,
    analyse,
    build_and_store,
    build_from_document,
)


def intent(*, missing_to: bool = False, unknown_trigger: bool = False) -> Intent:
    mail = {"subject": "s", "body": "b"} | ({} if missing_to else {"to": "{{trigger.owner_email}}"})
    return Intent(trigger=NodeIntent(ref="t", node_type="Nope" if unknown_trigger else "TaskCreated", then="m"),
                  steps=[NodeIntent(ref="m", node_type="SendEmail", params=mail)])


async def test_build_and_store_creates_a_draft_with_provenance():
    store = InMemoryStore()
    res = await build_and_store(store, "email the owner", FakeExtractor(intent()))
    stored = store.get_workflow(res.workflow.id)
    assert stored.status == "draft" and stored.built_from.source_text == "email the owner"
    assert stored.built_from.as_built_steps


async def test_store_forces_draft_even_if_caller_says_active():
    store = InMemoryStore()
    wf = (await build_and_store(store, "x", FakeExtractor(intent()))).workflow.model_copy(update={"status": "active"})
    assert store.create(wf).status == "draft"


async def test_gaps_still_create_but_errors_block_creation():
    store = InMemoryStore()
    gappy = await build_and_store(store, "x", FakeExtractor(intent(missing_to=True)))
    assert [g.param for g in gappy.gaps] == ["to"] and len(store.list_workflows()) == 1
    bad = await build_and_store(store, "x", FakeExtractor(intent(unknown_trigger=True)))
    assert [e.code for e in bad.errors] == ["NO_TRIGGER"] and len(store.list_workflows()) == 1


def test_analyse_loads_workflow_runs_and_catalog_by_id():
    wf, runs, expected = load_golden("onboarding_broken")
    store = InMemoryStore([wf], {wf.id: runs})
    d = analyse(store, wf.id)
    assert sorted(f.code for f in d.findings) == sorted(expected)
    assert {f.run_id for f in d.recent_failures} == {"r1", "r2", "r3"}
    with pytest.raises(KeyError):
        analyse(store, "missing")


async def test_build_from_document_feeds_extracted_text_into_the_same_pipeline():
    reader = FakeDocumentReader({"policy.txt": "When a task is created, email the owner."})
    fake = FakeExtractor(intent())
    res = await build_from_document("policy.txt", reader, fake, CATALOG)
    assert fake.calls[0][0] == "When a task is created, email the owner."
    assert res.workflow.status == "draft"
    assert res.workflow.built_from.source_ref == "policy.txt"
    assert res.workflow.built_from.source_text == "When a task is created, email the owner."
