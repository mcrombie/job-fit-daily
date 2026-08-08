from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from hashlib import sha256
from typing import Any


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def parse_datetime(value: Any) -> datetime | None:
    """Parse common API date formats into an aware UTC datetime."""
    if value is None or value == "":
        return None
    if isinstance(value, datetime):
        dt = value
    elif isinstance(value, (int, float)):
        # Most job APIs expose Unix timestamps in either seconds or milliseconds.
        seconds = float(value)
        if seconds > 10_000_000_000:
            seconds /= 1000.0
        try:
            dt = datetime.fromtimestamp(seconds, tz=timezone.utc)
        except (OverflowError, OSError, ValueError):
            return None
    else:
        text = str(value).strip()
        if not text:
            return None
        if text.isdigit():
            return parse_datetime(int(text))
        normalized = text.replace("Z", "+00:00")
        try:
            dt = datetime.fromisoformat(normalized)
        except ValueError:
            # A small set of formats used by public job feeds.
            formats = (
                "%Y-%m-%dT%H:%M:%S.%f%z",
                "%Y-%m-%dT%H:%M:%S%z",
                "%Y-%m-%d %H:%M:%S",
                "%Y-%m-%d",
            )
            for fmt in formats:
                try:
                    dt = datetime.strptime(text, fmt)
                    break
                except ValueError:
                    continue
            else:
                return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def iso_or_none(value: datetime | None) -> str | None:
    if value is None:
        return None
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


@dataclass(slots=True)
class Salary:
    minimum: float | None = None
    maximum: float | None = None
    currency: str | None = None
    period: str | None = None
    raw: str | None = None
    annual_minimum_usd: float | None = None
    annual_maximum_usd: float | None = None

    @property
    def known_usd(self) -> bool:
        return self.annual_minimum_usd is not None or self.annual_maximum_usd is not None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any] | None) -> "Salary":
        return cls(**(data or {}))


@dataclass(slots=True)
class Job:
    source: str
    source_id: str
    title: str
    company: str
    location: str
    url: str
    description: str = ""
    posted_at: datetime | None = None
    expires_at: datetime | None = None
    employment_type: str = ""
    remote: bool | None = None
    salary: Salary = field(default_factory=Salary)
    categories: list[str] = field(default_factory=list)
    source_url: str = ""
    raw: dict[str, Any] = field(default_factory=dict, repr=False)

    @property
    def canonical_key(self) -> str:
        location = self.location
        if self.remote or "remote" in self.location.lower():
            location = "remote"
        parts = [self.company, self.title, location]
        normalized = "|".join(" ".join(part.lower().split()) for part in parts)
        return sha256(normalized.encode("utf-8")).hexdigest()[:24]

    @property
    def fingerprint(self) -> str:
        if self.source_id:
            stable = f"{self.source}:{self.source_id}"
        else:
            stable = f"{self.source}:{self.url}:{self.canonical_key}"
        return sha256(stable.encode("utf-8")).hexdigest()[:24]

    def searchable_text(self) -> str:
        return " ".join(
            part
            for part in (
                self.title,
                self.company,
                self.location,
                self.employment_type,
                " ".join(self.categories),
                self.description,
            )
            if part
        )

    def to_dict(self, include_raw: bool = False) -> dict[str, Any]:
        data: dict[str, Any] = {
            "source": self.source,
            "source_id": self.source_id,
            "fingerprint": self.fingerprint,
            "canonical_key": self.canonical_key,
            "title": self.title,
            "company": self.company,
            "location": self.location,
            "url": self.url,
            "description": self.description,
            "posted_at": iso_or_none(self.posted_at),
            "expires_at": iso_or_none(self.expires_at),
            "employment_type": self.employment_type,
            "remote": self.remote,
            "salary": self.salary.to_dict(),
            "categories": self.categories,
            "source_url": self.source_url,
        }
        if include_raw:
            data["raw"] = self.raw
        return data

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Job":
        return cls(
            source=str(data.get("source", "")),
            source_id=str(data.get("source_id", "")),
            title=str(data.get("title", "")),
            company=str(data.get("company", "")),
            location=str(data.get("location", "")),
            url=str(data.get("url", "")),
            description=str(data.get("description", "")),
            posted_at=parse_datetime(data.get("posted_at")),
            expires_at=parse_datetime(data.get("expires_at")),
            employment_type=str(data.get("employment_type", "")),
            remote=data.get("remote"),
            salary=Salary.from_dict(data.get("salary")),
            categories=[str(item) for item in data.get("categories", [])],
            source_url=str(data.get("source_url", "")),
            raw=dict(data.get("raw", {})),
        )


@dataclass(slots=True)
class RankedJob:
    job: Job
    score: float
    family_id: str
    family_label: str
    reasons: list[str]
    concerns: list[str]
    matched_skills: list[str]
    breakdown: dict[str, float]
    eligible: bool = True
    rejection_reason: str | None = None
    is_new: bool = False
    first_seen: str | None = None

    def to_dict(self) -> dict[str, Any]:
        data = self.job.to_dict()
        data.update(
            {
                "score": round(self.score, 1),
                "family_id": self.family_id,
                "family_label": self.family_label,
                "reasons": self.reasons,
                "concerns": self.concerns,
                "matched_skills": self.matched_skills,
                "breakdown": {key: round(value, 2) for key, value in self.breakdown.items()},
                "eligible": self.eligible,
                "rejection_reason": self.rejection_reason,
                "is_new": self.is_new,
                "first_seen": self.first_seen,
            }
        )
        return data


@dataclass(slots=True)
class SourceStatus:
    source: str
    ok: bool
    fetched: int = 0
    kept: int = 0
    message: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)
