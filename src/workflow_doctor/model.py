"""Domain model plus the few graph helpers every other module shares."""

from __future__ import annotations

import json
import re
from datetime import datetime
from importlib import resources
from typing import Any, Literal

from pydantic import BaseModel, Field

from .triggers import TRIGGER_MAP


class CatalogNode(BaseModel):
    node_type: str
    kind: Literal["trigger", "action", "condition"]
    required_params: list[str] = Field(default_factory=list)
    optional_params: list[str] = Field(default_factory=list)
    outputs: list[str] = Field(default_factory=list)
    # Closed value sets (e.g. task status); anything else is rejected by the engine.
    allowed_values: dict[str, list[str]] = Field(default_factory=dict)


Catalog = dict[str, CatalogNode]


def load_catalog() -> Catalog:
    raw = resources.files("workflow_doctor").joinpath("catalog.json").read_text()
    return {n["node_type"]: CatalogNode(**n) for n in json.loads(raw)}


VARIABLE_SYNTAX = "{{ref.field}}"


def catalog_summary(catalog: Catalog) -> str:
    """Everything the extractor is grounded in, so it cannot invent nodes, values or syntax.

    The model sees: the nodes it may use (with closed value sets), the condition allow-list,
    each trigger's payload fields, trigger phrases, and the variable syntax. Anything else it
    wants must be reported as unsupported."""
    lines = ["Nodes you may use (anything else is unsupported):"]
    for n in catalog.values():
        line = f"{n.node_type} [{n.kind}] required={n.required_params} optional={n.optional_params}"
        if n.allowed_values:
            line += f" allowed_values={n.allowed_values}"
        if n.kind == "trigger":
            line += f" payload_fields={n.outputs}"
        elif n.outputs:
            line += f" outputs={n.outputs}"
        lines.append(line)
    conditions = [n.node_type for n in catalog.values() if n.kind == "condition"]
    lines.append(f"Condition allow-list (the only nodes that may branch TRUE/FALSE): {', '.join(conditions)}")
    lines.append(
        f"Variable syntax: reference an earlier step's output as {VARIABLE_SYNTAX}, where ref is that "
        "step's ref or 'trigger' for the trigger payload. Never invent ids."
    )
    lines.append("Trigger phrases:")
    lines += [f"  '{phrase}' -> {t}" for phrase, t in TRIGGER_MAP.items() if t in catalog]
    return "\n".join(lines)


class Step(BaseModel):
    id: str
    node_type: str
    params: dict[str, Any] = Field(default_factory=dict)
    next: str | None = None
    on_true: str | None = None
    on_false: str | None = None

    def targets(self) -> list[str]:
        return [t for t in (self.next, self.on_true, self.on_false) if t]


class Provenance(BaseModel):
    """What the builder produced and what it was asked, kept for later drift checks and revert."""

    source_text: str
    source_ref: str | None = None  # document reference when the request came from a document
    as_built_params: dict[str, dict[str, Any]] = Field(default_factory=dict)
    # Full as-built graph (trigger included). Optional so older records still load; without it
    # drift cannot see node-type or pointer changes and revert is unavailable.
    as_built_steps: dict[str, Step] = Field(default_factory=dict)
    as_built_trigger_id: str | None = None


class Workflow(BaseModel):
    id: str
    name: str
    status: Literal["draft", "active", "paused", "published"] = "draft"
    trigger: Step | None = None
    steps: dict[str, Step] = Field(default_factory=dict)
    built_from: Provenance | None = None

    def nodes(self) -> list[Step]:
        return ([self.trigger] if self.trigger else []) + list(self.steps.values())

    def index(self) -> dict[str, Step]:
        idx = dict(self.steps)
        if self.trigger:
            idx[self.trigger.id] = self.trigger
        return idx

    def walk(self) -> list[str]:
        """BFS from the trigger over next, on_true and on_false: the reachable ids in run order."""
        if not self.trigger:
            return []
        idx, order, queue = self.index(), [self.trigger.id], [self.trigger.id]
        while queue:
            for t in idx[queue.pop(0)].targets():
                if t in idx and t not in order:
                    order.append(t)
                    queue.append(t)
        return order


class Run(BaseModel):
    run_id: str
    started_at: datetime
    status: Literal["succeeded", "failed"]
    failed_step_id: str | None = None
    error: str | None = None
    executed_step_ids: list[str] = Field(default_factory=list)


_VAR = re.compile(r"\{\{\s*([\w-]+)\.([\w.-]+)\s*\}\}")


def variable_refs(params: dict[str, Any]) -> list[tuple[str, str]]:
    """(param, producer_id) for every {{producer.field}} in top-level string params."""
    return [(k, m[1]) for k, v in params.items() if isinstance(v, str) for m in _VAR.finditer(v)]


def rewrite_variables(text: str, mapping: dict[str, str]) -> str:
    return _VAR.sub(lambda m: f"{{{{{mapping[m[1]]}.{m[2]}}}}}" if m[1] in mapping else m[0], text)


def is_empty(value: Any) -> bool:
    """0 and False are real values; None, blank strings and empty containers are not."""
    if isinstance(value, str):
        return not value.strip()
    return value is None or value == [] or value == {}
