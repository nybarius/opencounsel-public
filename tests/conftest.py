from __future__ import annotations

import csv
import io
import json
import zipfile
from pathlib import Path

import pytest
from pypdf import PdfWriter
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from opencounsel.persistence.models import Base


@pytest.fixture
def roa_package(tmp_path: Path) -> Path:
    return make_roa_package(tmp_path / "synthetic-roa.zip")


@pytest.fixture
def session() -> Session:
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as value:
        yield value


def make_roa_package(path: Path, *, first_record_page: int = 3, pages: int = 3) -> Path:
    writer = PdfWriter()
    for _ in range(pages):
        writer.add_blank_page(width=612, height=792)
    pdf = io.BytesIO()
    writer.write(pdf)

    jsonl = io.StringIO()
    csv_stream = io.StringIO(newline="")
    fields = [
        "pdf_page",
        "record_page",
        "record_cite",
        "printed_top_center_number",
        "verified_original_number",
    ]
    csv_writer = csv.DictWriter(csv_stream, fieldnames=fields)
    csv_writer.writeheader()
    for physical in range(1, pages + 1):
        record = first_record_page + physical - 1
        cite = f"R {record}"
        jsonl.write(
            json.dumps(
                {
                    "physical_pdf_page": physical,
                    "record_page": record,
                    "record_cite": cite,
                    "text": f"Synthetic page {physical}.",
                }
            )
            + "\n"
        )
        csv_writer.writerow(
            {
                "pdf_page": physical,
                "record_page": record,
                "record_cite": cite,
                "printed_top_center_number": record,
                "verified_original_number": "true",
            }
        )
    with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("page_map.csv", csv_stream.getvalue())
        archive.writestr("indexed.pdf", pdf.getvalue())
        archive.writestr("pages.jsonl", jsonl.getvalue())
        archive.writestr("text.txt", "synthetic derivative")
    return path

