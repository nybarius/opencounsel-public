from __future__ import annotations

from pathlib import Path

import pytest
from conftest import make_roa_package
from sqlalchemy.orm import Session

from opencounsel.objects import ContentAddressedStore
from opencounsel.service import ConflictError, NotFoundError, import_roa, resolve


def test_import_and_exact_resolution(
    session: Session, roa_package: Path, tmp_path: Path
) -> None:
    store = ContentAddressedStore(tmp_path / "objects")
    imported = import_roa(
        session,
        store,
        roa_package,
        matter_slug="matter-001",
        document_key="record-on-appeal",
        expected_range=(3, 5),
    )

    assert imported.page_count == 3
    assert imported.warnings == ("original_source_absent",)
    assert not imported.already_present
    assert resolve(
        session,
        matter_slug="matter-001",
        document_key="record-on-appeal",
        cite="R. 3",
    ).physical_page == 1
    assert resolve(
        session,
        matter_slug="matter-001",
        document_key="record-on-appeal",
        cite="R 5",
    ).physical_page == 3

    repeated = import_roa(
        session,
        store,
        roa_package,
        matter_slug="matter-001",
        document_key="record-on-appeal",
    )
    assert repeated.already_present


def test_rejects_wrong_expected_range(
    session: Session, roa_package: Path, tmp_path: Path
) -> None:
    with pytest.raises(ConflictError, match="range"):
        import_roa(
            session,
            ContentAddressedStore(tmp_path / "objects"),
            roa_package,
            matter_slug="matter-001",
            document_key="record-on-appeal",
            expected_range=(3, 6),
        )


def test_not_found_is_content_free(session: Session) -> None:
    with pytest.raises(NotFoundError, match="not found"):
        resolve(
            session,
            matter_slug="matter-001",
            document_key="record-on-appeal",
            cite="R 3",
        )


def test_existing_document_rejects_different_bytes(
    session: Session, roa_package: Path, tmp_path: Path
) -> None:
    store = ContentAddressedStore(tmp_path / "objects")
    import_roa(
        session,
        store,
        roa_package,
        matter_slug="matter-001",
        document_key="record",
    )
    different = make_roa_package(tmp_path / "different.zip", first_record_page=10)
    with pytest.raises(ConflictError, match="different source bytes"):
        import_roa(
            session,
            store,
            different,
            matter_slug="matter-001",
            document_key="record",
        )


def test_rejects_disclosive_or_unsafe_key(
    session: Session, roa_package: Path, tmp_path: Path
) -> None:
    with pytest.raises(ValueError, match="opaque"):
        import_roa(
            session,
            ContentAddressedStore(tmp_path / "objects"),
            roa_package,
            matter_slug="contains spaces",
            document_key="record",
        )
