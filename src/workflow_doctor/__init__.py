"""Build workflows from plain language and diagnose why they fail."""

from .builder.build import BuildResult, build
from .builder.extract import FakeExtractor, Intent, NodeIntent
from .builder.validator import validate
from .doctor.diagnose import Diagnosis, diagnose
from .doctor.drift import DriftReport, FakeIntentJudge, IntentJudge, intent_drift
from .doctor.narrate import Card, FakeNarrator, narrate
from .documents import DocumentReader, FakeDocumentReader, build_from_document
from .model import Run, Step, Workflow, load_catalog
from .ops import (
    Edit,
    EditError,
    PublishedWorkflowError,
    PublishRefused,
    RevertUnavailable,
    apply_edit,
    copy_workflow,
    drift_edits,
    find_by_name,
    publish,
    revert,
)
from .store import InMemoryStore, WorkflowStore, analyse, build_and_store
from .triggers import TRIGGER_MAP, resolve_trigger

__all__ = [
    "BuildResult", "Card", "Diagnosis", "DocumentReader", "DriftReport", "Edit", "EditError",
    "FakeDocumentReader", "FakeExtractor", "FakeIntentJudge", "FakeNarrator", "InMemoryStore", "Intent",
    "IntentJudge", "NodeIntent", "PublishRefused", "PublishedWorkflowError", "RevertUnavailable", "Run",
    "Step", "TRIGGER_MAP", "Workflow", "WorkflowStore", "analyse", "apply_edit", "build", "build_and_store",
    "build_from_document", "copy_workflow", "diagnose", "drift_edits", "find_by_name", "intent_drift",
    "load_catalog", "narrate", "publish", "resolve_trigger", "revert", "validate",
]
