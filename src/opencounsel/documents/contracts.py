from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from opencounsel.work_product.ir import FilingIR, WorkProductIR


@dataclass(frozen=True, slots=True)
class WordTemplateRef:
    template_id: str
    version: str
    path: Path
    sha256: str


class WordProjector(Protocol):
    def render(self, work_product: WorkProductIR, template: WordTemplateRef) -> bytes: ...

    def reconcile(self, reviewed_docx: bytes, baseline: WorkProductIR) -> FilingIR: ...


class FilingPublisher(Protocol):
    def to_latex(self, filing: FilingIR) -> str: ...

    def to_pdf(self, latex: str) -> bytes: ...

