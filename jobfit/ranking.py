from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timezone
import re
from typing import Any, Iterable
from urllib.parse import urlsplit

from .models import Job, RankedJob, utc_now
from .salary import salary_display
from .text import normalized, phrase_hits, required_years, tfidf_similarities


_SOURCE_QUALITY = {
    "Greenhouse": 5,
    "Lever": 5,
    "USAJOBS": 5,
    "Himalayas": 3,
    "Remotive": 3,
    "Arbeitnow": 2,
}

_WORLDWIDE_TERMS = {
    "worldwide",
    "anywhere",
    "global",
    "all countries",
}
_US_ALLOW_TERMS = {
    "united states",
    "united states of america",
    "usa",
    "u.s.",
    "u.s.a.",
    "us only",
    "remote - us",
    "remote, us",
    "north america",
    "americas",
    "nationwide",
}
_OUTSIDE_ONLY_TERMS = {
    "europe",
    "european union",
    "eu only",
    "emea",
    "united kingdom",
    "uk only",
    "canada",
    "germany",
    "france",
    "spain",
    "italy",
    "netherlands",
    "india",
    "australia",
    "new zealand",
    "apac",
    "latin america",
    "south america",
    "philippines",
    "south africa",
}


def _dedupe_text(value: str) -> str:
    value = normalized(value)
    value = re.sub(r"[^a-z0-9+#.]+", " ", value)
    return " ".join(value.split())


def _dedupe_key(job: Job) -> str:
    company = _dedupe_text(job.company)
    title = _dedupe_text(job.title)
    location = _dedupe_text(job.location)
    is_remote = bool(job.remote) or "remote" in location
    location_key = "remote" if is_remote else location
    return f"{company}|{title}|{location_key}"


def _job_richness(job: Job) -> tuple[int, int, int, int, int]:
    """Prefer direct feeds, complete descriptions, salary data, dates, and stable links."""
    parsed = urlsplit(job.url)
    return (
        _SOURCE_QUALITY.get(job.source, 1),
        1 if job.salary.known_usd else 0,
        min(len(job.description), 20_000),
        1 if job.posted_at else 0,
        1 if parsed.scheme == "https" and parsed.netloc else 0,
    )


def deduplicate_jobs(jobs: Iterable[Job]) -> list[Job]:
    grouped: dict[str, list[Job]] = defaultdict(list)
    for job in jobs:
        grouped[_dedupe_key(job)].append(job)

    selected: list[Job] = []
    for group in grouped.values():
        best = max(group, key=_job_richness)
        if len(group) > 1:
            sources = sorted({job.source for job in group})
            best.raw = dict(best.raw)
            best.raw["also_seen_on"] = sources
            # Fill gaps from alternate records without replacing better primary data.
            for alternate in sorted(group, key=_job_richness, reverse=True):
                if not best.description and alternate.description:
                    best.description = alternate.description
                if not best.salary.known_usd and alternate.salary.known_usd:
                    best.salary = alternate.salary
                if not best.posted_at and alternate.posted_at:
                    best.posted_at = alternate.posted_at
                if not best.employment_type and alternate.employment_type:
                    best.employment_type = alternate.employment_type
                best.categories = sorted(set(best.categories) | set(alternate.categories))
        selected.append(best)
    return selected


def _candidate_document(profile: dict[str, Any]) -> str:
    candidate = profile.get("candidate", {})
    skill_names = [str(item.get("name", "")) for item in profile.get("skills", [])]
    aliases = [
        str(alias)
        for item in profile.get("skills", [])
        for alias in item.get("aliases", [])
    ]
    family_terms = [
        str(term)
        for family in profile.get("role_families", [])
        for term in [*family.get("title_terms", []), *family.get("keywords", [])]
    ]
    return " ".join(
        [
            str(candidate.get("summary", "")),
            " ".join(str(value) for value in candidate.get("strengths", [])),
            " ".join(skill_names),
            " ".join(aliases),
            " ".join(family_terms),
        ]
    )


def _family_alignment(job: Job, profile: dict[str, Any]) -> tuple[dict[str, Any], float, list[str], list[str]]:
    title = normalized(job.title)
    full_text = normalized(job.searchable_text())
    best_family: dict[str, Any] | None = None
    best_score = -1.0
    best_title_hits: list[str] = []
    best_keyword_hits: list[str] = []

    for family in profile.get("role_families", []):
        title_hits = [term for term in family.get("title_terms", []) if normalized(str(term)) in title]
        keyword_hits = [term for term in family.get("keywords", []) if normalized(str(term)) in full_text]
        # Exact title alignment is the strongest signal. Longer matching phrases are more specific.
        title_points = 0.0
        if title_hits:
            most_specific = max(len(normalized(str(term)).split()) for term in title_hits)
            title_points = 16.0 + min(5.0, max(0, most_specific - 1) * 1.5)
        keyword_points = min(9.0, len(set(keyword_hits)) * 1.35)
        family_weight = float(family.get("weight", 1.0))
        score = min(30.0, (title_points + keyword_points) * family_weight)
        if score > best_score:
            best_family = family
            best_score = score
            best_title_hits = title_hits
            best_keyword_hits = keyword_hits

    if best_family is None:
        best_family = {"id": "other", "label": "Other", "weight": 1.0}
        best_score = 0.0
    return best_family, max(0.0, best_score), best_title_hits, best_keyword_hits


def _skill_alignment(job: Job, profile: dict[str, Any]) -> tuple[float, list[str]]:
    title = normalized(job.title)
    text = normalized(job.searchable_text())
    matches: list[tuple[float, str]] = []
    raw_score = 0.0
    for skill in profile.get("skills", []):
        aliases = [normalized(str(alias)) for alias in skill.get("aliases", []) if str(alias).strip()]
        if not aliases:
            continue
        in_title = any(alias in title for alias in aliases)
        in_text = in_title or any(alias in text for alias in aliases)
        if not in_text:
            continue
        weight = float(skill.get("weight", 1.0))
        points = weight * (1.65 if in_title else 1.0)
        raw_score += points
        matches.append((points, str(skill.get("name", aliases[0]))))
    score = min(20.0, raw_score * 1.75)
    names = [name for _, name in sorted(matches, reverse=True)[:8]]
    return score, names


def _himalayas_restrictions(job: Job) -> tuple[bool, bool] | None:
    """Return (US allowed, worldwide) when structured location restrictions are available."""
    if job.source != "Himalayas":
        return None
    restrictions = job.raw.get("locationRestrictions")
    if restrictions is None:
        return None
    if not restrictions:
        return True, True
    values: list[str] = []
    for item in restrictions:
        if isinstance(item, dict):
            values.extend(
                normalized(str(item.get(key, "")))
                for key in ("alpha2", "name", "slug")
                if item.get(key)
            )
        elif item:
            values.append(normalized(str(item)))
    us_allowed = any(value in {"us", "usa", "united states", "united-states"} for value in values)
    worldwide = any(term in " ".join(values) for term in _WORLDWIDE_TERMS)
    return us_allowed or worldwide, worldwide


def _location_classification(job: Job, profile: dict[str, Any]) -> tuple[str, str | None]:
    structured = _himalayas_restrictions(job)
    location = normalized(job.location)
    location_config = profile.get("locations", {})
    remote_terms = [normalized(str(term)) for term in location_config.get("remote_terms", [])]
    local_terms = [normalized(str(term)) for term in location_config.get("local_bonus_terms", [])]
    us_terms = [normalized(str(term)) for term in location_config.get("us_terms", [])]
    configured_outside = [normalized(str(term)) for term in location_config.get("outside_us_only_terms", [])]

    if structured is not None:
        us_allowed, worldwide = structured
        if not us_allowed:
            return "outside-us", "Himalayas lists location restrictions that do not include the United States"
        if worldwide:
            return "remote-global", None
        return "remote-us", None

    is_remote = bool(job.remote) or any(term and term in location for term in remote_terms)
    is_local = any(term and term in location for term in local_terms)
    us_allowed = any(term and term in location for term in [*us_terms, *_US_ALLOW_TERMS])
    worldwide = any(term and term in location for term in _WORLDWIDE_TERMS)
    outside_signal = any(term and term in location for term in [*configured_outside, *_OUTSIDE_ONLY_TERMS])

    # A location like "United States, Canada" remains eligible because it explicitly includes the US.
    if outside_signal and not us_allowed and not worldwide:
        return "outside-us", f"Location appears restricted outside the United States ({job.location})"
    if is_local:
        return "local", None
    if is_remote and (us_allowed or worldwide):
        return "remote-global" if worldwide and not us_allowed else "remote-us", None
    if is_remote:
        return "remote-unclear", None
    if us_allowed:
        return "us", None
    return "unknown", None


def _employment_classification(job: Job) -> str:
    text = normalized(f"{job.title} {job.employment_type}")
    if any(term in text for term in ("part-time", "part time", "parttime")):
        return "part-time"
    if any(term in text for term in ("internship", "intern ", " intern", "co-op", "apprentice")):
        return "internship"
    if "volunteer" in text or "unpaid" in text:
        return "volunteer"
    if any(term in text for term in ("contract", "contractor", "temporary", "freelance")):
        return "contract"
    if any(term in text for term in ("full-time", "full time", "fulltime", "permanent")):
        return "full-time"
    return "unknown"


def _hard_rejection(job: Job, profile: dict[str, Any], now: datetime) -> str | None:
    candidate = profile.get("candidate", {})
    hard = profile.get("hard_filters", {})
    feedback = profile.get("feedback", {})
    floor = float(candidate.get("minimum_salary_usd", 0))
    lookback_days = int(candidate.get("lookback_days", 30))

    if not job.title or not job.company or not job.url:
        return "Missing a title, company, or application URL"
    if job.expires_at and job.expires_at < now:
        return "Application window has closed"
    if job.posted_at and (now - job.posted_at).total_seconds() > lookback_days * 86400:
        return f"Older than the {lookback_days}-day search window"

    employment = _employment_classification(job)
    if hard.get("reject_part_time", True) and employment == "part-time":
        return "Part-time role"
    if hard.get("reject_internships", True) and employment == "internship":
        return "Internship or apprenticeship"
    if hard.get("reject_volunteer", True) and employment == "volunteer":
        return "Unpaid or volunteer role"

    if (
        hard.get("reject_salary_ceiling_below_floor", True)
        and job.salary.annual_maximum_usd is not None
        and job.salary.annual_maximum_usd < floor
    ):
        return f"Published salary ceiling is below ${floor:,.0f}"

    location_class, location_reason = _location_classification(job, profile)
    if hard.get("reject_explicit_non_us_only", True) and location_class == "outside-us":
        return location_reason

    company = normalized(job.company)
    blocked_companies = [normalized(str(value)) for value in feedback.get("block_companies", [])]
    if any(value and value in company for value in blocked_companies):
        return "Company is blocked in profile feedback"
    searchable = normalized(job.searchable_text())
    blocked_terms = [normalized(str(value)) for value in feedback.get("block_terms", [])]
    if any(value and value in searchable for value in blocked_terms):
        return "Role contains a blocked profile term"
    return None


def _salary_score(job: Job, profile: dict[str, Any]) -> tuple[float, str | None, str | None]:
    floor = float(profile.get("candidate", {}).get("minimum_salary_usd", 0))
    minimum = job.salary.annual_minimum_usd
    maximum = job.salary.annual_maximum_usd
    display = salary_display(job.salary)
    if minimum is not None and minimum >= floor:
        return 10.0, f"Published pay starts at or above your ${floor:,.0f} floor", None
    if minimum is not None and maximum is not None and maximum >= floor:
        fraction = max(0.0, min(1.0, (maximum - floor) / max(1.0, maximum - minimum)))
        score = 5.0 + 2.0 * fraction
        return score, f"Published range reaches your ${floor:,.0f} floor", f"Range starts below target: {display}"
    if minimum is None and maximum is not None and maximum >= floor:
        return 5.0, f"Published ceiling clears your ${floor:,.0f} floor", f"Only a salary ceiling is listed: {display}"
    if job.salary.known_usd:
        # A known salary below the floor should already have been rejected when the ceiling is conclusive.
        return 2.0, None, f"Salary information may not reliably clear the ${floor:,.0f} target"
    return 2.0, None, "Salary is not listed or could not be normalized to annual USD"


def _location_score(job: Job, profile: dict[str, Any]) -> tuple[float, str | None, str | None]:
    classification, _ = _location_classification(job, profile)
    if classification == "local":
        return 10.0, "Located in Northern Virginia / the Washington region", None
    if classification == "remote-us":
        return 9.0, "Remote and explicitly open to U.S. applicants", None
    if classification == "remote-global":
        return 9.0, "Remote with worldwide eligibility", None
    if classification == "remote-unclear":
        return 6.0, "Advertised as remote", "Remote eligibility for a Virginia applicant is not explicit"
    if classification == "us":
        return 5.0, "Located in or open across the United States", None
    return 3.0, None, "Location eligibility is not explicit"


def _freshness_score(job: Job, now: datetime) -> tuple[float, str | None, str | None]:
    if job.posted_at is None:
        return 1.0, None, "Posting date is not available"
    days = max(0.0, (now - job.posted_at).total_seconds() / 86400.0)
    if days <= 1:
        return 8.0, "Posted within the last day", None
    if days <= 3:
        return 7.0, "Posted within the last three days", None
    if days <= 7:
        return 6.0, "Posted within the last week", None
    if days <= 14:
        return 4.0, None, None
    return 2.0, None, None


def _employment_score(job: Job, profile: dict[str, Any]) -> tuple[float, str | None, str | None]:
    classification = _employment_classification(job)
    if classification == "full-time":
        return 5.0, "Full-time role", None
    if classification == "contract":
        if profile.get("candidate", {}).get("allow_contract", True):
            return 2.0, None, "Contract or temporary rather than a permanent position"
        return -4.0, None, "Contract role is outside the preferred employment type"
    return 3.0, None, "Employment type is not explicit"


def _seniority_score(job: Job, profile: dict[str, Any]) -> tuple[float, list[str], list[str]]:
    config = profile.get("seniority", {})
    title = normalized(job.title)
    seniority_text = normalized(f"{job.title} {' '.join(job.categories)}")
    full_text = normalized(job.description)
    score = 6.0
    reasons: list[str] = []
    concerns: list[str] = []

    preferred = phrase_hits(title, config.get("preferred_title_terms", []))
    if preferred:
        score += 3.0
        reasons.append("Seniority label is aligned with an early-to-mid-career search")

    years = required_years(full_text)
    maximum_preferred = int(config.get("maximum_preferred_required_years", 5))
    if years is not None:
        if years <= 2:
            score += 2.0
            reasons.append(f"Experience requirement appears attainable ({years} years)")
        elif years <= maximum_preferred:
            score += 0.5
            reasons.append(f"Experience requirement is within the stretch range ({years} years)")
        else:
            penalty = min(15.0, 2.5 + (years - maximum_preferred) * 2.0)
            score -= penalty
            concerns.append(f"Posting appears to ask for about {years} years of experience")

    penalties = config.get("title_penalties", {})
    applied_terms: list[str] = []
    applied_penalty = 0.0
    for term, value in penalties.items():
        normalized_term = normalized(str(term))
        if normalized_term and normalized_term in seniority_text:
            applied_terms.append(str(term).strip())
            applied_penalty = max(applied_penalty, float(value))
    if applied_penalty:
        score -= applied_penalty
        concerns.append(f"Seniority title may be a reach ({', '.join(applied_terms)})")

    return max(-30.0, min(10.0, score)), reasons, concerns


def _risk_adjustment(job: Job, profile: dict[str, Any]) -> tuple[float, list[str]]:
    text = normalized(job.searchable_text())
    penalty = 0.0
    concerns: list[str] = []
    for risk in profile.get("risk_terms", []):
        terms = [normalized(str(term)) for term in risk.get("terms", [])]
        if any(term and term in text for term in terms):
            value = float(risk.get("penalty", 0))
            penalty -= value
            concerns.append(str(risk.get("label", "Potential requirement mismatch")))
    return penalty, concerns


def _feedback_adjustment(job: Job, profile: dict[str, Any]) -> tuple[float, list[str]]:
    feedback = profile.get("feedback", {})
    company = normalized(job.company)
    text = normalized(job.searchable_text())
    score = 0.0
    reasons: list[str] = []
    if any(normalized(str(value)) in company for value in feedback.get("boost_companies", []) if str(value).strip()):
        score += 6.0
        reasons.append("Company is explicitly boosted in your profile")
    matched_terms = [
        str(value)
        for value in feedback.get("boost_terms", [])
        if str(value).strip() and normalized(str(value)) in text
    ]
    if matched_terms:
        score += min(8.0, len(matched_terms) * 3.0)
        reasons.append("Matches terms you explicitly boosted")
    return score, reasons


def _rejected_ranked(job: Job, profile: dict[str, Any], reason: str) -> RankedJob:
    family, family_score, _, _ = _family_alignment(job, profile)
    return RankedJob(
        job=job,
        score=max(0.0, family_score),
        family_id=str(family.get("id", "other")),
        family_label=str(family.get("label", "Other")),
        reasons=[],
        concerns=[reason],
        matched_skills=[],
        breakdown={"role": family_score},
        eligible=False,
        rejection_reason=reason,
    )


def rank_jobs(
    jobs: Iterable[Job],
    profile: dict[str, Any],
    *,
    now: datetime | None = None,
) -> tuple[list[RankedJob], list[RankedJob]]:
    now = (now or utc_now()).astimezone(timezone.utc)
    unique_jobs = deduplicate_jobs(jobs)
    candidate_document = _candidate_document(profile)
    documents = [job.searchable_text()[:12_000] for job in unique_jobs]
    similarities = tfidf_similarities(candidate_document, documents)

    ranked: list[RankedJob] = []
    rejected: list[RankedJob] = []
    for job, similarity in zip(unique_jobs, similarities, strict=True):
        rejection = _hard_rejection(job, profile, now)
        if rejection:
            rejected.append(_rejected_ranked(job, profile, rejection))
            continue

        family, role_score, title_hits, keyword_hits = _family_alignment(job, profile)
        skill_score, matched_skills = _skill_alignment(job, profile)
        similarity_score = min(14.0, max(0.0, similarity) * 62.0)
        salary_score, salary_reason, salary_concern = _salary_score(job, profile)
        location_score, location_reason, location_concern = _location_score(job, profile)
        freshness_score, freshness_reason, freshness_concern = _freshness_score(job, now)
        employment_score, employment_reason, employment_concern = _employment_score(job, profile)
        seniority_score, seniority_reasons, seniority_concerns = _seniority_score(job, profile)
        risk_score, risk_concerns = _risk_adjustment(job, profile)
        feedback_score, feedback_reasons = _feedback_adjustment(job, profile)

        breakdown = {
            "role": role_score,
            "skills": skill_score,
            "profile_similarity": similarity_score,
            "salary": salary_score,
            "location": location_score,
            "freshness": freshness_score,
            "employment": employment_score,
            "seniority": seniority_score,
            "risk": risk_score,
            "feedback": feedback_score,
        }
        total = max(0.0, min(100.0, sum(breakdown.values())))

        reasons: list[str] = []
        if title_hits:
            reasons.append(f"Title aligns with {family.get('label', 'a target role family')}")
        elif len(keyword_hits) >= 4:
            reasons.append(f"Responsibilities align with {family.get('label', 'a target role family')}")
        if matched_skills:
            reasons.append("Matches " + ", ".join(matched_skills[:5]))
        if similarity_score >= 6.0:
            reasons.append("Overall language is close to your résumé and project profile")
        for candidate_reason in [salary_reason, location_reason, freshness_reason, employment_reason, *seniority_reasons, *feedback_reasons]:
            if candidate_reason and candidate_reason not in reasons:
                reasons.append(candidate_reason)

        concerns: list[str] = []
        for candidate_concern in [
            salary_concern,
            location_concern,
            freshness_concern,
            employment_concern,
            *seniority_concerns,
            *risk_concerns,
        ]:
            if candidate_concern and candidate_concern not in concerns:
                concerns.append(candidate_concern)
        if not title_hits and role_score < 10:
            concerns.append("Title is outside the strongest target role families")
        if not matched_skills:
            concerns.append("Few explicit skill overlaps were detected")
        if len(job.description) < 220:
            concerns.append("Description is sparse, so the fit score is less certain")

        ranked.append(
            RankedJob(
                job=job,
                score=round(total, 2),
                family_id=str(family.get("id", "other")),
                family_label=str(family.get("label", "Other")),
                reasons=reasons[:6],
                concerns=concerns[:5],
                matched_skills=matched_skills,
                breakdown=breakdown,
            )
        )

    ranked.sort(
        key=lambda item: (
            item.score,
            item.job.posted_at or datetime.min.replace(tzinfo=timezone.utc),
            item.job.salary.annual_minimum_usd or 0,
        ),
        reverse=True,
    )
    rejected.sort(key=lambda item: item.job.posted_at or datetime.min.replace(tzinfo=timezone.utc), reverse=True)
    return ranked, rejected
