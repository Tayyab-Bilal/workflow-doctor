import pytest

from helpers import CATALOG, S, W, load_golden
from workflow_doctor import (
    Edit,
    EditError,
    InMemoryStore,
    PublishedWorkflowError,
    PublishRefused,
    RevertUnavailable,
    Workflow,
    apply_edit,
    copy_workflow,
    diagnose,
    drift_edits,
    find_by_name,
    publish,
    revert,
)
from workflow_doctor.builder.build import build
from workflow_doctor.builder.extract import FakeExtractor, Intent, NodeIntent
from workflow_doctor.model import variable_refs


def named(id: str, name: str, status: str = "draft") -> Workflow:
    return Workflow(id=id, name=name, status=status)


def test_find_by_name_one_several_none():
    store = InMemoryStore([named("1", "Onboarding"), named("2", "Onboarding (old)"), named("3", "Escalate overdue"),
                           named("4", "Escalate overdue tasks")])
    one = find_by_name(store, "  onboarding ")  # exact match wins over the longer name
    assert one.outcome == "one" and one.workflow_id == "1"
    several = find_by_name(store, "escalate")
    assert several.outcome == "several" and [c.id for c in several.candidates] == ["3", "4"]
    assert several.workflow_id is None  # the caller must ask, never guess
    assert find_by_name(store, "payroll").outcome == "none"
    assert find_by_name(store, "").outcome == "none"


async def built() -> Workflow:
    n = lambda ref, t, p=None, **kw: NodeIntent(ref=ref, node_type=t, params=p or {}, **kw)  # noqa: E731
    intent = Intent(trigger=n("t", "TaskOverdue", then="c"), steps=[
        n("c", "FieldEquals", {"field": "priority", "value": "high"}, if_true="m", if_false="w"),
        n("m", "SendEmail", {"to": "{{trigger.owner_email}}", "subject": "Overdue {{t.task_title}}", "body": "b"}),
        n("w", "Delay", {"minutes": 5}, then="p"),
        n("p", "Notify", {"user": "{{trigger.project_lead}}", "message": "{{w.nothing}}"}),
    ])
    return (await build("escalate overdue", FakeExtractor(intent), CATALOG)).workflow


async def test_copy_gets_new_ids_and_rewires_every_link_and_variable():
    src = await built()
    cp = copy_workflow(src)
    assert cp.id != src.id and cp.status == "draft"
    src_ids, new_ids = set(src.index()), set(cp.index())
    assert not src_ids & new_ids and len(new_ids) == len(src_ids)
    for s in cp.nodes():
        assert all(t in new_ids for t in s.targets())
        assert all(producer in new_ids for _, producer in variable_refs(s.params))
    assert [CATALOG[s.node_type].kind for s in cp.nodes()] == [CATALOG[s.node_type].kind for s in src.nodes()]
    # same structure, so the Doctor says the same thing about both (ids differ, codes do not)
    assert [f.code for f in diagnose(cp, CATALOG, []).findings] == [f.code for f in diagnose(src, CATALOG, []).findings]


async def test_copy_applies_edits_in_the_same_save_and_leaves_source_alone():
    src = await built()
    delay = next(s for s in src.steps.values() if s.node_type == "Delay")
    mail = next(s for s in src.steps.values() if s.node_type == "SendEmail")
    before = src.model_dump()
    cp = copy_workflow(src, [Edit(step_id=delay.id, set_params={"minutes": 60}),
                             Edit(step_id=mail.id, set_params={"to": f"{{{{{src.trigger.id}.project_lead}}}}"})],
                       name="Escalate (project Y)")
    new_delay = next(s for s in cp.steps.values() if s.node_type == "Delay")
    new_mail = next(s for s in cp.steps.values() if s.node_type == "SendEmail")
    assert cp.name == "Escalate (project Y)" and new_delay.params["minutes"] == 60
    assert new_mail.params["to"] == f"{{{{{cp.trigger.id}.project_lead}}}}"  # edit's reference rewired too
    assert src.model_dump() == before


async def test_copy_keeps_provenance_so_edits_show_as_drift():
    src = await built()
    delay = next(s for s in src.steps.values() if s.node_type == "Delay")
    cp = copy_workflow(src, [Edit(step_id=delay.id, set_params={"minutes": 60})])
    assert cp.built_from.source_text == "escalate overdue"
    assert set(cp.built_from.as_built_params) == set(cp.index())
    d = diagnose(cp, CATALOG, [])
    new_delay = next(s.id for s in cp.steps.values() if s.node_type == "Delay")
    assert d.drift == {new_delay: ["minutes"]}
    assert d.drift_report.steps_changed[new_delay].params["minutes"].as_built == 5


async def test_copy_with_unknown_step_edit_is_an_error():
    with pytest.raises(EditError):
        copy_workflow(await built(), [Edit(step_id="nope", set_params={"x": 1})])


def test_copy_of_workflow_without_provenance_has_none():
    wf, _, _ = load_golden("healthy")
    assert copy_workflow(wf).built_from is None


async def test_apply_edit_returns_a_copy():
    src = await built()
    delay = next(s for s in src.steps.values() if s.node_type == "Delay")
    out = apply_edit(src, Edit(step_id=delay.id, set_params={"minutes": 9}, set_pointers={"next": None}))
    assert out.steps[delay.id].params["minutes"] == 9 and out.steps[delay.id].next is None
    assert src.steps[delay.id].params["minutes"] == 5


def test_apply_edit_refuses_published_workflow():
    wf = W(S("t1", "TaskCreated", next="s1"), S("s1", "Notify", {"user": "u", "message": "m"}), status="published")
    with pytest.raises(PublishedWorkflowError):
        apply_edit(wf, Edit(step_id="s1", set_params={"message": "x"}))
    assert wf.steps["s1"].params["message"] == "m"


def test_apply_edit_unknown_step():
    with pytest.raises(EditError):
        apply_edit(W(S("t1", "TaskCreated")), Edit(step_id="zzz"))


async def test_publish_requires_a_valid_workflow_and_then_blocks_edits():
    src = await built()
    pub = publish(src, CATALOG)
    assert pub.status == "published" and src.status == "draft"
    with pytest.raises(PublishedWorkflowError):
        apply_edit(pub, Edit(step_id=next(iter(pub.steps)), set_params={"a": 1}))
    with pytest.raises(PublishRefused):
        publish(W(S("t1", "TaskCreated", next="s1"), S("s1", "SendEmail", {"subject": "s", "body": "b"})), CATALOG)
    with pytest.raises(PublishRefused):
        publish(W(None), CATALOG)


async def test_revert_restores_last_as_built():
    src = await built()
    delay = next(s for s in src.steps.values() if s.node_type == "Delay")
    mail = next(s for s in src.steps.values() if s.node_type == "SendEmail")
    broken = apply_edit(apply_edit(src, Edit(step_id=delay.id, set_params={"minutes": 0})),
                        Edit(step_id=mail.id, set_params={"to": ""}, set_pointers={"next": "ghost"}))
    del broken.steps[delay.id]
    assert diagnose(broken, CATALOG, []).findings
    fixed = revert(broken)
    assert fixed.model_dump() == src.model_dump()


def test_revert_unavailable_without_snapshot_and_refuses_published():
    wf, _, _ = load_golden("healthy")
    with pytest.raises(RevertUnavailable):
        revert(wf)
    with pytest.raises(PublishedWorkflowError):
        revert(wf.model_copy(update={"status": "published"}))


async def test_drift_edits_propose_putting_as_built_values_back():
    src = await built()
    delay = next(s for s in src.steps.values() if s.node_type == "Delay")
    drifted = apply_edit(src, Edit(step_id=delay.id, set_params={"minutes": 0}))
    (proposal,) = drift_edits(drifted)
    assert proposal == Edit(step_id=delay.id, set_params={"minutes": 5})
    assert drift_edits(apply_edit(drifted, proposal)) == []
