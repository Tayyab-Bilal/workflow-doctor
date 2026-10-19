from __future__ import annotations

from pydantic import BaseModel

from ..model import Catalog, Workflow, catalog_summary
from .assembler import assemble
from .extract import Extractor
from .validator import Gap, Issue, validate


class BuildResult(BaseModel):
    workflow: Workflow
    gaps: list[Gap]
    unsupported: list[str]
    errors: list[Issue]


async def build(
    text: str, extractor: Extractor, catalog: Catalog, source_ref: str | None = None
) -> BuildResult:
    """Always returns a draft. Missing values are reported as gaps, never guessed."""
    intent = await extractor.extract(text, catalog_summary(catalog))
    wf, unsupported = assemble(intent, catalog, text, source_ref)
    v = validate(wf, catalog)
    return BuildResult(workflow=wf, gaps=v.gaps, unsupported=unsupported, errors=v.errors)
