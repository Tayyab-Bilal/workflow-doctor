"""Document ingestion seam: any file becomes text, and the text goes through the normal build."""

from __future__ import annotations

from typing import Protocol

from .builder.build import BuildResult, build
from .builder.extract import Extractor
from .model import Catalog


class DocumentReader(Protocol):
    """Turns a document reference into plain text. Production plugs in an OCR vendor for PDFs and
    images, office and text extractors, and speech-to-text for audio."""

    async def read(self, doc_ref: str) -> str: ...


class FakeDocumentReader:
    """Serves text from a dict, so tests and the demo need no files or vendors."""

    def __init__(self, docs: dict[str, str]) -> None:
        self.docs = docs

    async def read(self, doc_ref: str) -> str:
        return self.docs[doc_ref]


async def build_from_document(doc_ref: str, reader: DocumentReader, extractor: Extractor, catalog: Catalog) -> BuildResult:
    """Same pipeline as `build`: the extracted text is the request, and the reference is kept as provenance."""
    return await build(await reader.read(doc_ref), extractor, catalog, source_ref=doc_ref)
