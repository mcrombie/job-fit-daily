from __future__ import annotations

from collections import Counter
from datetime import datetime, timedelta, timezone
import json
import logging
import os
from pathlib import Path
from typing import Any

from .config import Paths, load_configuration
from .models import Job, SourceStatus, iso_or_none, utc_now
from .notify import send_digest
from .ranking import rank_jobs
from .render import build_payload, render_site
from .sources import fetch_all_sources
from .state import annotate_and_update_seen, write_json_atomic


LOGGER = logging.getLogger(__name__)


def _load_fixture(path: Path, now: datetime) -> tuple[list[Job], list[SourceStatus]]:
    with path.open("r", encoding="utf-8") as handle:
        payload = json.load(handle)
    records = payload.get("jobs", payload) if isinstance(payload, dict) else payload
    if not isinstance(records, list):
        raise RuntimeError(f"Fixture must contain a list of jobs: {path}")
    jobs: list[Job] = []
    for original in records:
        if not isinstance(original, dict):
            continue
        record = dict(original)
        if "posted_days_ago" in record:
            record["posted_at"] = iso_or_none(now - timedelta(days=float(record.pop("posted_days_ago"))))
        if "expires_days_from_now" in record:
            record["expires_at"] = iso_or_none(now + timedelta(days=float(record.pop("expires_days_from_now"))))
        jobs.append(Job.from_dict(record))
    counts = Counter(job.source for job in jobs)
    statuses = [SourceStatus(source=name, ok=True, fetched=count, message="demo fixture") for name, count in sorted(counts.items())]
    return jobs, statuses


def _dashboard_url() -> str:
    explicit = os.environ.get("DASHBOARD_URL", "").strip()
    if explicit:
        return explicit
    repository = os.environ.get("GITHUB_REPOSITORY", "").strip()
    if "/" in repository:
        owner, name = repository.split("/", 1)
        return f"https://{owner}.github.io/{name}/"
    return ""


def _prune_history(history_dir: Path, keep_days: int, now: datetime) -> None:
    cutoff = (now - timedelta(days=max(1, keep_days))).date()
    if not history_dir.exists():
        return
    for path in history_dir.glob("*.json"):
        try:
            file_date = datetime.strptime(path.stem, "%Y-%m-%d").date()
        except ValueError:
            continue
        if file_date < cutoff:
            path.unlink(missing_ok=True)


def run_pipeline(
    paths: Paths,
    *,
    now: datetime | None = None,
    fixture_path: Path | None = None,
    demo: bool = False,
    send_email: bool = True,
) -> dict[str, Any]:
    now = (now or utc_now()).astimezone(timezone.utc)
    profile, source_config = load_configuration(paths)

    if fixture_path:
        source_jobs, statuses = _load_fixture(fixture_path, now)
    else:
        source_jobs, statuses = fetch_all_sources(source_config)
        if not source_jobs and any(not status.ok for status in statuses):
            raise RuntimeError("Every usable source returned zero jobs while at least one source failed; preserving the previous dashboard")

    ranked, rejected = rank_jobs(source_jobs, profile, now=now)
    retention_days = max(90, int(source_config.get("output", {}).get("history_days", 45)) * 2)
    state_path = paths.data_dir / ("demo-state.json" if demo else "state.json")
    annotate_and_update_seen(
        ranked,
        state_path,
        now=now,
        retention_days=retention_days,
        persist=not demo,
    )

    eligible_by_source = Counter(item.job.source for item in ranked)
    for status in statuses:
        status.kept = eligible_by_source.get(status.source, 0)

    candidate = profile.get("candidate", {})
    threshold = float(candidate.get("dashboard_min_score", 42))
    maximum = int(candidate.get("max_dashboard_results", 50))
    above_threshold = [item for item in ranked if item.score >= threshold]
    dashboard_jobs = above_threshold[:maximum]
    below_threshold_count = sum(1 for item in ranked if item.score < threshold)
    truncated_count = max(0, len(above_threshold) - len(dashboard_jobs))

    payload = build_payload(
        dashboard_jobs,
        statuses,
        profile,
        generated_at=now,
        fetched_count=len(source_jobs),
        eligible_count=len(ranked),
        rejected_count=len(rejected),
        below_threshold_count=below_threshold_count,
        demo=demo,
    )
    payload["pipeline"]["deduplicated"] = len(ranked) + len(rejected)
    payload["pipeline"]["truncated"] = truncated_count
    render_site(payload, paths.site_dir)

    run_record = {
        "schema_version": 1,
        "generated_at": iso_or_none(now),
        "demo": demo,
        "fetched": len(source_jobs),
        "deduplicated": len(ranked) + len(rejected),
        "eligible": len(ranked),
        "rejected": len(rejected),
        "above_threshold": len(above_threshold),
        "shown": len(dashboard_jobs),
        "truncated": truncated_count,
        "new_shown": sum(1 for item in dashboard_jobs if item.is_new),
        "source_statuses": [status.to_dict() for status in statuses],
        "top_jobs": [
            {
                "score": round(item.score, 1),
                "title": item.job.title,
                "company": item.job.company,
                "url": item.job.url,
            }
            for item in dashboard_jobs[:10]
        ],
    }

    if not demo:
        write_json_atomic(paths.data_dir / "latest.json", payload)
        write_json_atomic(paths.data_dir / "run-summary.json", run_record)
        history_dir = paths.data_dir / "history"
        history_dir.mkdir(parents=True, exist_ok=True)
        write_json_atomic(history_dir / f"{now.date().isoformat()}.json", run_record)
        _prune_history(history_dir, int(source_config.get("output", {}).get("history_days", 45)), now)

    email_sent = False
    email_message = "Email not attempted"
    if send_email and not demo:
        try:
            email_sent, email_message = send_digest(
                ranked,
                profile,
                source_config,
                generated_at=now,
                dashboard_url=_dashboard_url(),
            )
        except Exception as exc:  # Dashboard generation must survive an optional notification failure.
            LOGGER.exception("Email notification failed")
            email_message = f"Email failed: {exc}"
    run_record["email_sent"] = email_sent
    run_record["email_message"] = email_message
    if not demo:
        write_json_atomic(paths.data_dir / "run-summary.json", run_record)

    LOGGER.info(
        "Run complete: %s fetched, %s eligible, %s shown, %s rejected",
        len(source_jobs),
        len(ranked),
        len(dashboard_jobs),
        len(rejected),
    )
    return run_record
