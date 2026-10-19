"""The only LLM-facing step: text in, structure out. Never ids, never wiring."""

from __future__ import annotations

from typing import Any, Protocol

from pydantic import BaseModel, Field


class NodeIntent(BaseModel):
    """A node as the model describes it. `ref` is a throwaway label; extra keys such as an
    `id` the model hallucinated are dropped by pydantic's default extra="ignore"."""

    ref: str
    node_type: str
    params: dict[str, Any] = Field(default_factory=dict)
    then: str | None = None
    if_true: str | None = None
    if_false: str | None = None


class Intent(BaseModel):
    trigger: NodeIntent
    steps: list[NodeIntent] = Field(default_factory=list)
    unsupported: list[str] = Field(default_factory=list)


class Extractor(Protocol):
    async def extract(self, text: str, catalog_summary: str) -> Intent: ...


class FakeExtractor:
    """Returns a scripted Intent and records what it was asked, so tests can inspect the prompt."""

    def __init__(self, scripted: Intent) -> None:
        self.scripted = scripted
        self.calls: list[tuple[str, str]] = []

    async def extract(self, text: str, catalog_summary: str) -> Intent:
        self.calls.append((text, catalog_summary))
        return self.scripted
