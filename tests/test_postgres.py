from __future__ import annotations

import os
from pathlib import Path

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from opencounsel.objects import ContentAddressedStore
from opencounsel.persistence.models import Base
from opencounsel.service import import_roa, resolve

DATABASE_URL = os.environ.get("OPENCOUNSEL_TEST_DATABASE_URL")
pytestmark = pytest.mark.skipif(DATABASE_URL is None, reason="PostgreSQL integration URL not set")


def test_postgresql_import_and_resolution(roa_package: Path, tmp_path: Path) -> None:
    engine = create_engine(DATABASE_URL)
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)
    try:
        with Session(engine) as session:
            import_roa(
                session,
                ContentAddressedStore(tmp_path / "objects"),
                roa_package,
                matter_slug="matter-001",
                document_key="record",
                expected_range=(3, 5),
            )
            assert resolve(
                session,
                matter_slug="matter-001",
                document_key="record",
                cite="R 5",
            ).physical_page == 3
    finally:
        Base.metadata.drop_all(engine)
        engine.dispose()

