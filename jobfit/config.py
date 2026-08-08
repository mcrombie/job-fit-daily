from __future__ import annotations

import json
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass(frozen=True, slots=True)
class Paths:
    root: Path
    profile: Path
    sources: Path
    data_dir: Path
    site_dir: Path


def project_root() -> Path:
    return Path(__file__).resolve().parents[1]


def load_json(path: Path) -> dict[str, Any]:
    try:
        with path.open("r", encoding="utf-8") as handle:
            value = json.load(handle)
    except FileNotFoundError as exc:
        raise RuntimeError(f"Configuration file not found: {path}") from exc
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"Invalid JSON in {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise RuntimeError(f"Expected a JSON object in {path}")
    return value


def resolve_paths(
    profile_path: str | Path | None = None,
    sources_path: str | Path | None = None,
) -> Paths:
    root = project_root()
    profile = Path(profile_path) if profile_path else root / "config" / "profile.json"
    sources = Path(sources_path) if sources_path else root / "config" / "sources.json"
    source_config = load_json(sources)
    output = source_config.get("output", {})
    data_dir = root / str(output.get("data_directory", "data"))
    site_dir = root / str(output.get("site_directory", "site"))
    data_dir.mkdir(parents=True, exist_ok=True)
    site_dir.mkdir(parents=True, exist_ok=True)
    return Paths(root=root, profile=profile, sources=sources, data_dir=data_dir, site_dir=site_dir)


def load_configuration(paths: Paths) -> tuple[dict[str, Any], dict[str, Any]]:
    profile = load_json(paths.profile)
    sources = load_json(paths.sources)
    validate_profile(profile)
    validate_sources(sources)
    return profile, sources


def validate_profile(profile: dict[str, Any]) -> None:
    candidate = profile.get("candidate")
    if not isinstance(candidate, dict):
        raise RuntimeError("profile.json requires a candidate object")
    for field in ("name", "summary", "minimum_salary_usd"):
        if field not in candidate:
            raise RuntimeError(f"profile.json candidate is missing {field!r}")
    if not profile.get("role_families"):
        raise RuntimeError("profile.json requires at least one role family")
    if not profile.get("skills"):
        raise RuntimeError("profile.json requires at least one skill")


def validate_sources(sources: dict[str, Any]) -> None:
    if not isinstance(sources.get("http", {}), dict):
        raise RuntimeError("sources.json http must be an object")
    if not isinstance(sources.get("output", {}), dict):
        raise RuntimeError("sources.json output must be an object")


def env(name: str, default: str = "") -> str:
    return os.environ.get(name, default).strip()


def env_int(name: str, default: int) -> int:
    raw = env(name)
    if not raw:
        return default
    try:
        return int(raw)
    except ValueError as exc:
        raise RuntimeError(f"Environment variable {name} must be an integer") from exc
