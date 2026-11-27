"""Settings from chronos.toml (machine-specific, not in git; see chronos.example.toml)."""

from __future__ import annotations

import os
import tomllib
from dataclasses import dataclass, field
from pathlib import Path


class ConfigError(ValueError):
    pass


@dataclass
class Settings:
    roots: list[Path] = field(default_factory=list)
    depth: int = 2                       # how deep under each root to look for repositories
    authors: list[str] = field(default_factory=list)   # e-mails; empty = each repo's user.email
    exclude: list[str] = field(default_factory=list)   # folder names to skip
    private: list[str] = field(default_factory=list)   # folder names shown as "private project"
    all_branches: bool = True            # count commits on every local branch, not only HEAD
    iris_url: str = ""                   # e.g. http://127.0.0.1:8090/chronos
    remind_after: int = 20               # chronos remind: only after this hour (local time)


def default_path() -> Path:
    env = os.environ.get("CHRONOS_CONFIG")
    if env:
        return Path(env).expanduser()
    here = Path(__file__).resolve().parent.parent / "chronos.toml"
    if here.exists():
        return here
    base = Path(os.environ.get("XDG_CONFIG_HOME") or Path.home() / ".config")
    return base / "chronos" / "config.toml"


def _strings(data: dict, key: str) -> list[str]:
    value = data.get(key, [])
    if not isinstance(value, list) or not all(isinstance(v, str) for v in value):
        raise ConfigError(f"{key} must be a list of strings")
    return value


def parse(data: dict) -> Settings:
    s = Settings()
    s.roots = [Path(r).expanduser() for r in _strings(data, "roots")]
    depth = data.get("depth", s.depth)
    if not isinstance(depth, int) or isinstance(depth, bool) or not 0 <= depth <= 4:
        raise ConfigError("depth must be a whole number from 0 to 4")
    s.depth = depth
    s.authors = [a.strip().lower() for a in _strings(data, "authors") if a.strip()]
    s.exclude = _strings(data, "exclude")
    s.private = _strings(data, "private")
    branches = data.get("all_branches", s.all_branches)
    if not isinstance(branches, bool):
        raise ConfigError("all_branches must be true or false")
    s.all_branches = branches
    url = data.get("iris_url", "")
    if not isinstance(url, str) or (url and not url.startswith(("http://", "https://"))):
        raise ConfigError("iris_url must be an http(s) address")
    s.iris_url = url
    hour = data.get("remind_after", s.remind_after)
    if not isinstance(hour, int) or isinstance(hour, bool) or not 0 <= hour <= 23:
        raise ConfigError("remind_after must be an hour from 0 to 23")
    s.remind_after = hour
    return s


def load(path: Path | None = None) -> Settings:
    path = path or default_path()
    if not path.exists():
        # No file: look at the current folder and its children.
        return Settings(roots=[Path.cwd()])
    try:
        data = tomllib.loads(path.read_text(encoding="utf-8"))
    except (tomllib.TOMLDecodeError, UnicodeDecodeError) as exc:
        raise ConfigError(f"{path}: {exc}") from None
    s = parse(data)
    if not s.roots:
        raise ConfigError(f"{path}: roots is empty")
    return s
