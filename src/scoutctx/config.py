"""Configuration loading for ScoutCTX."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
import tomllib


CONFIG_NAME = ".scoutctx.toml"
DEFAULT_CONFIG = """# ScoutCTX project settings
[scoutctx]
budget = 12000
max_file_bytes = 262144
max_files = 24
redact = true

# Paths use gitignore-style globs.
include = []
exclude = [
  "*.min.js",
  "*.map",
  "coverage/**",
  "fixtures/**",
]
"""


@dataclass(slots=True)
class Settings:
    budget: int = 12_000
    max_file_bytes: int = 262_144
    max_files: int = 24
    redact: bool = True
    include: list[str] = field(default_factory=list)
    exclude: list[str] = field(default_factory=list)


def load_settings(root: Path) -> Settings:
    """Load ``.scoutctx.toml`` from *root*, falling back to safe defaults."""

    path = root / CONFIG_NAME
    if not path.exists():
        return Settings()

    try:
        raw = tomllib.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, tomllib.TOMLDecodeError) as exc:
        raise ValueError(f"could not read {CONFIG_NAME}: {exc}") from exc

    data = raw.get("scoutctx", {})
    if not isinstance(data, dict):
        raise ValueError(f"{CONFIG_NAME}: [scoutctx] must be a table")

    settings = Settings()
    validators: dict[str, type] = {
        "budget": int,
        "max_file_bytes": int,
        "max_files": int,
        "redact": bool,
        "include": list,
        "exclude": list,
    }
    for key, expected in validators.items():
        if key not in data:
            continue
        value = data[key]
        if not isinstance(value, expected):
            raise ValueError(f"{CONFIG_NAME}: {key} must be {expected.__name__}")
        setattr(settings, key, value)

    if settings.budget < 256:
        raise ValueError(f"{CONFIG_NAME}: budget must be at least 256")
    if settings.max_file_bytes < 1024:
        raise ValueError(f"{CONFIG_NAME}: max_file_bytes must be at least 1024")
    if settings.max_files < 1:
        raise ValueError(f"{CONFIG_NAME}: max_files must be positive")
    if not all(isinstance(item, str) for item in settings.include + settings.exclude):
        raise ValueError(f"{CONFIG_NAME}: include and exclude entries must be strings")
    return settings


def initialize(root: Path) -> Path:
    """Create a documented starter config without overwriting an existing one."""

    path = root / CONFIG_NAME
    if path.exists():
        raise FileExistsError(f"{path} already exists")
    path.write_text(DEFAULT_CONFIG, encoding="utf-8")
    return path

