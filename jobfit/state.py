from __future__ import annotations

from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
from typing import Any, Iterable

from .models import RankedJob, iso_or_none, utc_now


def _read_json(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    try:
        with path.open("r", encoding="utf-8") as handle:
            value = json.load(handle)
    except (OSError, json.JSONDecodeError):
        return {}
    return value if isinstance(value, dict) else {}


def write_json_atomic(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    with temporary.open("w", encoding="utf-8", newline="\n") as handle:
        json.dump(value, handle, ensure_ascii=False, indent=2, sort_keys=False)
        handle.write("\n")
    temporary.replace(path)


def annotate_and_update_seen(
    ranked_jobs: Iterable[RankedJob],
    state_path: Path,
    *,
    now: datetime | None = None,
    retention_days: int = 120,
    persist: bool = True,
) -> dict[str, Any]:
    now = (now or utc_now()).astimezone(timezone.utc)
    state = _read_json(state_path)
    seen = state.get("seen", {}) if isinstance(state.get("seen", {}), dict) else {}
    current_keys: set[str] = set()

    for ranked in ranked_jobs:
        key = ranked.job.canonical_key
        current_keys.add(key)
        record = seen.get(key) if isinstance(seen.get(key), dict) else None
        first_seen = record.get("first_seen") if record else None
        ranked.is_new = not bool(first_seen)
        ranked.first_seen = str(first_seen or iso_or_none(now))
        seen[key] = {
            "first_seen": ranked.first_seen,
            "last_seen": iso_or_none(now),
        }

    cutoff = now - timedelta(days=max(retention_days, 1))
    pruned: dict[str, Any] = {}
    for key, record in seen.items():
        if key in current_keys:
            pruned[key] = record
            continue
        if not isinstance(record, dict):
            continue
        last_seen_raw = record.get("last_seen")
        try:
            last_seen = datetime.fromisoformat(str(last_seen_raw).replace("Z", "+00:00"))
        except (TypeError, ValueError):
            continue
        if last_seen.tzinfo is None:
            last_seen = last_seen.replace(tzinfo=timezone.utc)
        if last_seen >= cutoff:
            pruned[key] = record

    updated = {
        "schema_version": 1,
        "updated_at": iso_or_none(now),
        "seen": pruned,
    }
    if persist:
        write_json_atomic(state_path, updated)
    return updated
