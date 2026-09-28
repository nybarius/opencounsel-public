from __future__ import annotations

import os
import sys
import tempfile
from contextlib import suppress
from pathlib import Path

import atheris

with atheris.instrument_imports():
    from opencounsel.briefs.docx import BriefDocxError, inspect_brief_docx


def test_one_input(data: bytes) -> None:
    descriptor, name = tempfile.mkstemp(suffix=".docx")
    path = Path(name)
    try:
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(data)
        with suppress(BriefDocxError):
            inspect_brief_docx(path)
    finally:
        path.unlink(missing_ok=True)


def main() -> None:
    atheris.Setup(sys.argv, test_one_input)
    atheris.Fuzz()


if __name__ == "__main__":
    main()
