"""Optional narrative layer. Findings stand alone; the narrator only makes them readable."""

from __future__ import annotations

import logging
from typing import Protocol

from pydantic import BaseModel

from .diagnose import Diagnosis

log = logging.getLogger(__name__)


class Card(BaseModel):
    root_cause: str
    evidence: list[str]
    fix: list[str]  # numbered by the renderer
    impact: str


class Narrator(Protocol):
    async def narrate(self, diagnosis: Diagnosis) -> list[Card]: ...


class FakeNarrator:
    def __init__(self, scripted: list[Card]) -> None:
        self.scripted = scripted

    async def narrate(self, diagnosis: Diagnosis) -> list[Card]:
        return self.scripted


_IMPACT = {
    "high": "Runs fail or never start until this is fixed.",
    "medium": "Parts of the workflow misbehave or never run.",
    "low": "Harmless today, but the workflow is not doing what it looks like it does.",
}


def fallback_cards(d: Diagnosis) -> list[Card]:
    """Deterministic text built straight from the findings: the answer never depends on an LLM."""
    cards = []
    for f in d.findings:
        evidence = [f"check {f.code}" + (f" on step {f.step_id}" if f.step_id else "")]
        evidence += [x.explanation for x in d.recent_failures if f.step_id and x.step_id == f.step_id]
        cards.append(Card(root_cause=f.message, evidence=evidence, fix=[f.fix], impact=_IMPACT[f.severity]))
    return cards


async def narrate(d: Diagnosis, narrator: Narrator | None = None) -> list[Card]:
    if narrator is not None:
        try:
            if cards := await narrator.narrate(d):
                return cards
        except Exception:  # any narrator failure must not lose the diagnosis
            log.warning("narrator failed, using deterministic fallback", exc_info=True)
    return fallback_cards(d)
