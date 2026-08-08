from __future__ import annotations

from datetime import datetime, timedelta, timezone
import json
from pathlib import Path

from jobfit.models import Job, iso_or_none


FIXTURE = Path(__file__).parent / "fixtures" / "demo_jobs.json"


def demo_jobs(now: datetime | None = None) -> list[Job]:
    now = now or datetime(2026, 8, 7, 12, 0, tzinfo=timezone.utc)
    payload = json.loads(FIXTURE.read_text(encoding="utf-8"))
    jobs: list[Job] = []
    for original in payload["jobs"]:
        record = dict(original)
        if "posted_days_ago" in record:
            record["posted_at"] = iso_or_none(now - timedelta(days=float(record.pop("posted_days_ago"))))
        if "expires_days_from_now" in record:
            record["expires_at"] = iso_or_none(now + timedelta(days=float(record.pop("expires_days_from_now"))))
        jobs.append(Job.from_dict(record))
    return jobs
