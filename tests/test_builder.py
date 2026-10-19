import uuid

from helpers import CATALOG
from workflow_doctor import FakeExtractor, Intent, NodeIntent, build


def N(ref, node_type, params=None, **kw):
    return NodeIntent(ref=ref, node_type=node_type, params=params or {}, **kw)


def by_type(wf, node_type):
    return next(s for s in wf.steps.values() if s.node_type == node_type)


async def run_build(intent):
    return await build("some request", FakeExtractor(intent), CATALOG)


async def test_llm_never_sets_ids():
    raw = {"ref": "t", "node_type": "TaskCreated", "id": "LLM-MADE-UP", "then": "a"}
    intent = Intent(
        trigger=NodeIntent.model_validate(raw),
        steps=[NodeIntent.model_validate({"ref": "a", "node_type": "Notify", "id": "LLM-STEP",
                                          "params": {"user": "u", "message": "m"}})],
    )
    wf = (await run_build(intent)).workflow
    ids = [wf.trigger.id, *wf.steps]
    assert len(set(ids)) == 2
    for i in ids:
        uuid.UUID(i)  # raises unless the engine side minted it
    assert not {"LLM-MADE-UP", "LLM-STEP", "t", "a"} & set(ids)


async def test_branches_wired_from_refs():
    intent = Intent(
        trigger=N("t", "TaskOverdue", then="c"),
        steps=[
            N("c", "FieldEquals", {"field": "priority", "value": "high"}, if_true="mail", if_false="wait"),
            N("mail", "SendEmail", {"to": "a@b.c", "subject": "s", "body": "b"}),
            N("wait", "Delay", {"minutes": 5}, then="ping"),
            N("ping", "Notify", {"user": "u", "message": "m"}),
        ],
    )
    res = await run_build(intent)
    wf = res.workflow
    cond = by_type(wf, "FieldEquals")
    assert cond.on_true == by_type(wf, "SendEmail").id
    assert cond.on_false == by_type(wf, "Delay").id
    assert by_type(wf, "Delay").next == by_type(wf, "Notify").id
    assert wf.trigger.next == cond.id
    assert res.errors == []


async def test_variables_rewritten_to_step_ids():
    intent = Intent(
        trigger=N("t", "TaskCreated", then="mk"),
        steps=[
            N("mk", "CreateTask", {"title": "{{trigger.task_title}}", "project_id": "p"}, then="cm"),
            N("cm", "AddComment", {"task_id": "{{mk.task_id}}", "text": "hi {{t.owner_email}}"}),
        ],
    )
    wf = (await run_build(intent)).workflow
    tid, mk = wf.trigger.id, by_type(wf, "CreateTask")
    assert mk.params["title"] == f"{{{{{tid}.task_title}}}}"
    cm = by_type(wf, "AddComment")
    assert cm.params["task_id"] == f"{{{{{mk.id}.task_id}}}}"
    assert cm.params["text"] == f"hi {{{{{tid}.owner_email}}}}"


async def test_unknown_node_goes_to_unsupported():
    intent = Intent(
        trigger=N("t", "TaskCreated", then="x"),
        steps=[N("x", "TeleportPizza", then="n"), N("n", "Notify", {"user": "u", "message": "m"})],
    )
    res = await run_build(intent)
    assert any("TeleportPizza" in u for u in res.unsupported)
    assert all(s.node_type != "TeleportPizza" for s in res.workflow.steps.values())


async def test_unknown_condition_not_faked():
    intent = Intent(
        trigger=N("t", "TaskCreated", then="c"),
        steps=[
            N("c", "FieldMatchesRegex", {"field": "title"}, if_true="a", if_false="a"),
            N("a", "Notify", {"user": "u", "message": "m"}),
        ],
    )
    res = await run_build(intent)
    assert any("condition" in u and "FieldMatchesRegex" in u for u in res.unsupported)
    kinds = {CATALOG[s.node_type].kind for s in res.workflow.steps.values()}
    assert "condition" not in kinds
    assert not any(s.on_true or s.on_false for s in res.workflow.steps.values())


async def test_missing_required_param_is_gap_not_error():
    intent = Intent(
        trigger=N("t", "TaskCreated", then="m"),
        steps=[N("m", "SendEmail", {"subject": "s", "body": "b"})],
    )
    res = await run_build(intent)
    mail = by_type(res.workflow, "SendEmail")
    assert [(g.step_id, g.param) for g in res.gaps] == [(mail.id, "to")]
    assert res.errors == []


async def test_built_as_draft():
    res = await run_build(Intent(trigger=N("t", "TaskCreated")))
    assert res.workflow.status == "draft"
    assert res.workflow.built_from.source_text == "some request"


async def test_provenance_records_params_as_built():
    intent = Intent(trigger=N("t", "TaskCreated", then="n"),
                    steps=[N("n", "Notify", {"user": "u", "message": "{{trigger.task_title}}"})])
    wf = (await run_build(intent)).workflow
    step = by_type(wf, "Notify")
    assert wf.built_from.as_built_params[step.id] == step.params


async def test_extractor_is_grounded_in_catalog():
    fake = FakeExtractor(Intent(trigger=N("t", "TaskCreated")))
    await build("x", fake, CATALOG)
    assert "SendEmail" in fake.calls[0][1] and "FieldEquals" in fake.calls[0][1]


async def test_unknown_trigger_leaves_no_trigger_error():
    res = await run_build(Intent(trigger=N("t", "Nope")))
    assert res.workflow.trigger is None
    assert any("Nope" in u for u in res.unsupported)
    assert [e.code for e in res.errors] == ["NO_TRIGGER"]
