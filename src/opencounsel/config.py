from __future__ import annotations

import os
import stat
import tomllib
from dataclasses import dataclass
from pathlib import Path

DEFAULT_CONFIG_PATH = Path.home() / ".config" / "opencounsel" / "config.toml"
DEFAULT_OBJECT_ROOT = Path.home() / ".local" / "share" / "opencounsel" / "objects"
DEFAULT_DATABASE_URL = "postgresql+psycopg://opencounsel@/opencounsel"


class ConfigError(ValueError):
    """Raised when local configuration weakens the default security boundary."""


@dataclass(frozen=True, slots=True)
class Settings:
    database_url: str
    object_root: Path
    model_policy: str = "disabled"

    def validate(self, *, allow_test_database: bool = False) -> None:
        if not self.database_url.startswith("postgresql+psycopg://") and not (
            allow_test_database and self.database_url.startswith("sqlite")
        ):
            raise ConfigError("the canonical database must use postgresql+psycopg")
        if self.model_policy != "disabled":
            raise ConfigError("this slice requires model_policy = 'disabled'")


def init_config(path: Path = DEFAULT_CONFIG_PATH) -> Settings:
    """Create a private, conservative local configuration or validate the existing one."""
    if path.exists():
        return load_settings(path)

    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    path.parent.chmod(0o700)
    object_root = DEFAULT_OBJECT_ROOT
    object_root.mkdir(parents=True, exist_ok=True, mode=0o700)
    object_root.chmod(0o700)
    body = (
        "schema_version = 1\n"
        f'database_url = "{DEFAULT_DATABASE_URL}"\n'
        f'object_root = "{object_root}"\n'
        'model_policy = "disabled"\n'
    )
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as stream:
        stream.write(body)
    return Settings(DEFAULT_DATABASE_URL, object_root)


def load_settings(path: Path = DEFAULT_CONFIG_PATH) -> Settings:
    if not path.is_file():
        raise ConfigError(f"configuration not found: {path}; run 'opencounsel init'")
    mode = stat.S_IMODE(path.stat().st_mode)
    if mode & 0o077:
        raise ConfigError(f"configuration must not be group/world accessible (mode {mode:04o})")
    with path.open("rb") as stream:
        values = tomllib.load(stream)
    if values.get("schema_version") != 1:
        raise ConfigError("unsupported configuration schema")
    settings = Settings(
        database_url=os.environ.get("OPENCOUNSEL_DATABASE_URL", values["database_url"]),
        object_root=Path(values["object_root"]).expanduser(),
        model_policy=values.get("model_policy", "disabled"),
    )
    settings.validate()
    return settings
