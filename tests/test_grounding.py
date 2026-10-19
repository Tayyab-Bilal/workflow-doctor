from workflow_doctor import TRIGGER_MAP, load_catalog, resolve_trigger
from workflow_doctor.doctor.checks import ALL_CHECKS, CHECK_GROUPS
from workflow_doctor.model import catalog_summary

CATALOG = load_catalog()
SUMMARY = catalog_summary(CATALOG)


def test_summary_lists_allowed_values_of_closed_sets():
    assert "allowed_values={'status': ['todo', 'in_progress', 'done', 'blocked']}" in SUMMARY
    assert "'priority': ['low', 'medium', 'high']" in SUMMARY


def test_summary_states_the_condition_allow_list():
    line = next(x for x in SUMMARY.splitlines() if x.startswith("Condition allow-list"))
    assert all(c in line for c in ("FieldEquals", "FieldGreaterThan", "FieldContains"))
    assert "SendEmail" not in line


def test_summary_gives_trigger_payload_fields():
    line = next(x for x in SUMMARY.splitlines() if x.startswith("TaskOverdue"))
    assert "payload_fields=['task_id', 'task_title', 'owner_email', 'project_lead', 'priority', 'days_overdue']" in line


def test_summary_states_the_variable_syntax():
    assert "{{ref.field}}" in SUMMARY and "'trigger'" in SUMMARY


def test_summary_includes_trigger_phrases():
    assert "'a task becomes overdue' -> TaskOverdue" in SUMMARY


def test_catalog_has_about_twelve_triggers():
    assert sum(n.kind == "trigger" for n in CATALOG.values()) == 12


def test_every_mapped_trigger_exists_in_the_catalog():
    for phrase, t in TRIGGER_MAP.items():
        assert t in CATALOG and CATALOG[t].kind == "trigger", phrase


def test_every_catalog_trigger_is_mapped():
    triggers = {n.node_type for n in CATALOG.values() if n.kind == "trigger"}
    assert triggers == set(TRIGGER_MAP.values())


def test_resolve_trigger_ignores_case_and_spacing():
    assert resolve_trigger("  A Task  is CREATED ") == "TaskCreated"
    assert resolve_trigger("the moon is full") is None


def test_fifteen_checks_in_four_groups():
    assert list(CHECK_GROUPS) == ["trigger", "step_parameter", "flow", "execution_health"]
    assert [len(g) for g in CHECK_GROUPS.values()] == [3, 5, 4, 3]
    assert len(ALL_CHECKS) == 15 and len(set(ALL_CHECKS)) == 15
