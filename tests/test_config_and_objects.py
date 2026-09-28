from __future__ import annotations

import stat
from pathlib import Path

import pytest

from opencounsel.config import ConfigError, Settings, init_config, load_settings
from opencounsel.objects import ContentAddressedStore


def test_config_and_objects_are_private(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("opencounsel.config.DEFAULT_OBJECT_ROOT", tmp_path / "objects")
    config = tmp_path / "config" / "config.toml"
    settings = init_config(config)

    assert stat.S_IMODE(config.stat().st_mode) == 0o600
    assert stat.S_IMODE(settings.object_root.stat().st_mode) == 0o700
    assert load_settings(config).model_policy == "disabled"

    source = tmp_path / "source.bin"
    source.write_bytes(b"privileged synthetic bytes")
    stored = ContentAddressedStore(settings.object_root).put_path(source)
    destination = settings.object_root / stored.key
    assert stat.S_IMODE(destination.stat().st_mode) == 0o600
    assert destination.read_bytes() == source.read_bytes()


def test_rejects_overpermissive_config(tmp_path: Path) -> None:
    config = tmp_path / "config.toml"
    config.write_text(
        'schema_version = 1\ndatabase_url = "postgresql+psycopg://local/db"\n'
        f'object_root = "{tmp_path / "objects"}"\nmodel_policy = "disabled"\n',
        encoding="utf-8",
    )
    config.chmod(0o644)
    with pytest.raises(ConfigError, match="group/world"):
        load_settings(config)


def test_config_fail_closed_cases(tmp_path: Path) -> None:
    with pytest.raises(ConfigError, match="configuration not found"):
        load_settings(tmp_path / "missing.toml")
    with pytest.raises(ConfigError, match="canonical database"):
        Settings("https://database.invalid", tmp_path).validate()
    with pytest.raises(ConfigError, match="model_policy"):
        Settings("postgresql+psycopg://local/db", tmp_path, "openai").validate()
    Settings("sqlite+pysqlite:///:memory:", tmp_path).validate(allow_test_database=True)


def test_object_store_is_idempotent_and_confined(tmp_path: Path) -> None:
    root = tmp_path / "objects"
    store = ContentAddressedStore(root)
    source = tmp_path / "source.bin"
    source.write_bytes(b"same bytes")
    first = store.put_path(source)
    second = store.put_path(source)
    assert first == second
    with store.open(first.key) as stream:
        assert stream.read() == b"same bytes"
    with pytest.raises(ValueError, match="escapes"):
        store.open("../outside")
    store.clear_for_test()
    assert not root.exists()
