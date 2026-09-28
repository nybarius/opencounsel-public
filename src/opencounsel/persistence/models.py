from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import (
    BigInteger,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
    Uuid,
    func,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


class Matter(Base):
    __tablename__ = "matter"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    slug: Mapped[str] = mapped_column(String(80), unique=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class SourceFile(Base):
    __tablename__ = "source_file"
    __table_args__ = (UniqueConstraint("matter_id", "role", "sha256"),)

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    matter_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("matter.id"), nullable=False)
    parent_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("source_file.id"))
    role: Mapped[str] = mapped_column(String(40), nullable=False)
    provenance_status: Mapped[str] = mapped_column(String(40), nullable=False)
    media_type: Mapped[str] = mapped_column(String(100), nullable=False)
    sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    size_bytes: Mapped[int] = mapped_column(BigInteger, nullable=False)
    object_key: Mapped[str] = mapped_column(String(100), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class Document(Base):
    __tablename__ = "document"
    __table_args__ = (UniqueConstraint("matter_id", "document_key"),)

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    matter_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("matter.id"), nullable=False)
    document_key: Mapped[str] = mapped_column(String(80), nullable=False)
    kind: Mapped[str] = mapped_column(String(40), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    representations: Mapped[list[Representation]] = relationship(
        back_populates="document", cascade="all, delete-orphan"
    )


class Representation(Base):
    __tablename__ = "representation"
    __table_args__ = (UniqueConstraint("document_id", "kind"),)

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    document_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("document.id"), nullable=False)
    source_file_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("source_file.id"), nullable=False)
    kind: Mapped[str] = mapped_column(String(40), nullable=False)
    extractor: Mapped[str] = mapped_column(String(80), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    document: Mapped[Document] = relationship(back_populates="representations")
    pages: Mapped[list[Page]] = relationship(
        back_populates="representation", cascade="all, delete-orphan"
    )


class Page(Base):
    __tablename__ = "page"
    __table_args__ = (UniqueConstraint("representation_id", "ordinal"),)

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    representation_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("representation.id"), nullable=False
    )
    ordinal: Mapped[int] = mapped_column(Integer, nullable=False)
    text: Mapped[str] = mapped_column(Text, nullable=False)
    representation: Mapped[Representation] = relationship(back_populates="pages")


class LocatorScheme(Base):
    __tablename__ = "locator_scheme"
    __table_args__ = (UniqueConstraint("document_id", "name"),)

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    document_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("document.id"), nullable=False)
    name: Mapped[str] = mapped_column(String(40), nullable=False)
    prefix: Mapped[str] = mapped_column(String(16), nullable=False)


class Locator(Base):
    __tablename__ = "locator"
    __table_args__ = (
        UniqueConstraint("scheme_id", "value"),
        UniqueConstraint("scheme_id", "normalized"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    scheme_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("locator_scheme.id"), nullable=False)
    page_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("page.id"), nullable=False)
    value: Mapped[int] = mapped_column(Integer, nullable=False)
    normalized: Mapped[str] = mapped_column(String(40), nullable=False)
    display: Mapped[str] = mapped_column(String(40), nullable=False)


class IngestionRun(Base):
    __tablename__ = "ingestion_run"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    matter_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("matter.id"), nullable=False)
    package_source_file_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("source_file.id"), nullable=False
    )
    status: Mapped[str] = mapped_column(String(20), nullable=False)
    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class ValidationResult(Base):
    __tablename__ = "validation_result"
    __table_args__ = (UniqueConstraint("ingestion_run_id", "code"),)

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    ingestion_run_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("ingestion_run.id"), nullable=False
    )
    code: Mapped[str] = mapped_column(String(80), nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False)
    detail: Mapped[str] = mapped_column(Text, nullable=False)

