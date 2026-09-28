from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path
from zipfile import BadZipFile

from docx import Document
from docx.opc.exceptions import PackageNotFoundError


class WordTemplateError(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class WordTemplateInspection:
    sha256: str
    size_bytes: int
    section_count: int
    style_names: tuple[str, ...]


def inspect_word_template(path: Path) -> WordTemplateInspection:
    """Inspect a sanitized blank template without returning document body content."""
    if not path.is_file() or path.is_symlink() or path.suffix.lower() not in {".docx", ".dotx"}:
        raise WordTemplateError("template must be a regular DOCX or DOTX file")
    size_bytes = path.stat().st_size
    if size_bytes > 25 * 1024 * 1024:
        raise WordTemplateError("template exceeds the 25 MiB limit")
    data = path.read_bytes()
    try:
        document = Document(str(path))
    except (BadZipFile, PackageNotFoundError, ValueError, KeyError) as exc:
        raise WordTemplateError("template is not a readable OOXML package") from exc
    return WordTemplateInspection(
        sha256=hashlib.sha256(data).hexdigest(),
        size_bytes=size_bytes,
        section_count=len(document.sections),
        style_names=tuple(sorted(style.name for style in document.styles)),
    )
