from __future__ import annotations

import hashlib
import os
import shutil
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import BinaryIO, Protocol


class BinaryReader(Protocol):
    def read(self, size: int = -1) -> bytes: ...


@dataclass(frozen=True, slots=True)
class StoredObject:
    sha256: str
    size_bytes: int
    key: str


class ContentAddressedStore:
    """A private local implementation of the future object-store boundary."""

    def __init__(self, root: Path) -> None:
        self.root = root
        self.root.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.root.chmod(0o700)

    def put_path(self, source: Path) -> StoredObject:
        with source.open("rb") as stream:
            return self.put_stream(stream)

    def put_stream(self, source: BinaryReader) -> StoredObject:
        digest = hashlib.sha256()
        size = 0
        fd, temporary = tempfile.mkstemp(prefix="ingest-", dir=self.root)
        try:
            if fchmod := getattr(os, "fchmod", None):
                fchmod(fd, 0o600)
            with os.fdopen(fd, "wb") as target:
                while chunk := source.read(1024 * 1024):
                    digest.update(chunk)
                    size += len(chunk)
                    target.write(chunk)
                target.flush()
                os.fsync(target.fileno())

            sha256 = digest.hexdigest()
            key = f"sha256/{sha256[:2]}/{sha256[2:]}"
            destination = self.root / key
            destination.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
            destination.parent.chmod(0o700)
            if destination.exists():
                Path(temporary).unlink()
            else:
                os.replace(temporary, destination)
                destination.chmod(0o600)
            return StoredObject(sha256=sha256, size_bytes=size, key=key)
        except BaseException:
            Path(temporary).unlink(missing_ok=True)
            raise

    def open(self, key: str) -> BinaryIO:
        return self.path_for(key).open("rb")

    def path_for(self, key: str) -> Path:
        """Resolve a stored key without allowing absolute paths or traversal."""
        raw = Path(key)
        if raw.is_absolute() or not raw.parts:
            raise ValueError("object key escapes the object root")
        root = self.root.resolve()
        candidate = (root / raw).resolve()
        if candidate == root or root not in candidate.parents:
            raise ValueError("object key escapes the object root")
        return candidate

    def clear_for_test(self) -> None:
        """Remove an isolated test store; not exposed by the CLI."""
        shutil.rmtree(self.root)
