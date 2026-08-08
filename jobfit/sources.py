from __future__ import annotations

import logging
import os
from typing import Any, Callable
from urllib.parse import urljoin

from .http import FetchError, get_json
from .models import Job, SourceStatus, parse_datetime
from .salary import best_salary, parse_salary_text, structured_salary
from .text import html_to_text, normalize_space


LOGGER = logging.getLogger(__name__)


def _http_options(config: dict[str, Any]) -> dict[str, Any]:
    http = config.get("http", {})
    return {
        "timeout": int(http.get("timeout_seconds", 30)),
        "retries": int(http.get("retries", 3)),
        "user_agent": str(http.get("user_agent", "job-fit-daily/1.0")),
    }


def _text(value: Any) -> str:
    return normalize_space(str(value or ""))


def _list_of_text(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        return [normalize_space(value)] if value.strip() else []
    if isinstance(value, (list, tuple, set)):
        result: list[str] = []
        for item in value:
            if isinstance(item, dict):
                label = item.get("name") or item.get("text") or item.get("label")
                if label:
                    result.append(_text(label))
            elif item not in (None, ""):
                result.append(_text(item))
        return [item for item in result if item]
    return [_text(value)]


def fetch_himalayas(config: dict[str, Any]) -> list[Job]:
    settings = config.get("himalayas", {})
    if not settings.get("enabled", True):
        return []
    page_size = min(20, max(1, int(settings.get("page_size", 20))))
    max_pages = max(1, int(settings.get("max_pages", 8)))
    options = _http_options(config)
    jobs: list[Job] = []
    offset = 0
    for _ in range(max_pages):
        payload = get_json(
            "https://himalayas.app/jobs/api",
            params={"limit": page_size, "offset": offset},
            **options,
        )
        records = payload.get("jobs", []) if isinstance(payload, dict) else []
        if not records:
            break
        for record in records:
            restrictions = record.get("locationRestrictions") or []
            countries = []
            for item in restrictions:
                if isinstance(item, dict):
                    countries.append(_text(item.get("name") or item.get("alpha2") or item.get("slug")))
                else:
                    countries.append(_text(item))
            location = "Remote — " + (", ".join(filter(None, countries)) if countries else "Worldwide")
            salary = structured_salary(
                record.get("minSalary"),
                record.get("maxSalary"),
                record.get("currency") or "USD",
                record.get("salaryPeriod") or "annual",
            )
            description = html_to_text(record.get("description") or record.get("excerpt") or "")
            jobs.append(
                Job(
                    source="Himalayas",
                    source_id=_text(record.get("guid") or record.get("id") or record.get("applicationLink")),
                    title=_text(record.get("title")),
                    company=_text(record.get("companyName")),
                    location=location,
                    url=_text(record.get("applicationLink")),
                    description=description,
                    posted_at=parse_datetime(record.get("pubDate")),
                    expires_at=parse_datetime(record.get("expiryDate")),
                    employment_type=_text(record.get("employmentType")),
                    remote=True,
                    salary=best_salary(salary, description),
                    categories=[
                        *_list_of_text(record.get("categories")),
                        *_list_of_text(record.get("parentCategories")),
                        *_list_of_text(record.get("seniority")),
                    ],
                    source_url=_text(record.get("applicationLink")) or "https://himalayas.app/jobs",
                    raw=dict(record),
                )
            )
        offset += len(records)
        total = int(payload.get("totalCount", offset)) if isinstance(payload, dict) else offset
        if len(records) < page_size or offset >= total:
            break
    return jobs


def fetch_remotive(config: dict[str, Any]) -> list[Job]:
    settings = config.get("remotive", {})
    if not settings.get("enabled", True):
        return []
    options = _http_options(config)
    payload = get_json(
        "https://remotive.com/api/remote-jobs",
        params={"limit": int(settings.get("limit", 1000))},
        **options,
    )
    records = payload.get("jobs", []) if isinstance(payload, dict) else []
    jobs: list[Job] = []
    for record in records:
        description = html_to_text(record.get("description"))
        salary_raw = _text(record.get("salary"))
        salary = parse_salary_text(salary_raw or description)
        location = _text(record.get("candidate_required_location")) or "Remote"
        jobs.append(
            Job(
                source="Remotive",
                source_id=_text(record.get("id")),
                title=_text(record.get("title")),
                company=_text(record.get("company_name")),
                location=location,
                url=_text(record.get("url")),
                description=description,
                posted_at=parse_datetime(record.get("publication_date")),
                employment_type=_text(record.get("job_type")),
                remote=True,
                salary=salary,
                categories=_list_of_text(record.get("category")),
                source_url=_text(record.get("url")) or "https://remotive.com/remote-jobs",
                raw=dict(record),
            )
        )
    return jobs


def fetch_arbeitnow(config: dict[str, Any]) -> list[Job]:
    settings = config.get("arbeitnow", {})
    if not settings.get("enabled", True):
        return []
    options = _http_options(config)
    max_pages = max(1, int(settings.get("max_pages", 5)))
    jobs: list[Job] = []
    url: str | None = "https://www.arbeitnow.com/api/job-board-api"
    for _page in range(1, max_pages + 1):
        if not url:
            break
        payload = get_json(url, **options)
        records = payload.get("data", []) if isinstance(payload, dict) else []
        if not records:
            break
        for record in records:
            description = html_to_text(record.get("description"))
            remote = bool(record.get("remote"))
            location = _text(record.get("location")) or ("Remote" if remote else "Location not listed")
            tags = _list_of_text(record.get("tags"))
            job_types = _list_of_text(record.get("job_types") or record.get("job_type"))
            jobs.append(
                Job(
                    source="Arbeitnow",
                    source_id=_text(record.get("slug") or record.get("id") or record.get("url")),
                    title=_text(record.get("title")),
                    company=_text(record.get("company_name")),
                    location=location,
                    url=_text(record.get("url")),
                    description=description,
                    posted_at=parse_datetime(record.get("created_at") or record.get("date")),
                    employment_type=", ".join(job_types),
                    remote=remote,
                    salary=parse_salary_text(description),
                    categories=tags,
                    source_url=_text(record.get("url")) or "https://www.arbeitnow.com/",
                    raw=dict(record),
                )
            )
        links = payload.get("links", {}) if isinstance(payload, dict) else {}
        next_url = links.get("next") if isinstance(links, dict) else None
        if not next_url:
            break
        url = urljoin(url, str(next_url))
    return jobs


def _board_record(item: Any) -> tuple[str, str]:
    if isinstance(item, str):
        return item, item
    if isinstance(item, dict):
        token = _text(item.get("token") or item.get("board_token"))
        company = _text(item.get("company") or item.get("name") or token)
        return token, company
    return "", ""


def fetch_greenhouse(config: dict[str, Any]) -> list[Job]:
    settings = config.get("greenhouse", {})
    if not settings.get("enabled", True):
        return []
    options = _http_options(config)
    jobs: list[Job] = []
    for item in settings.get("boards", []):
        token, configured_company = _board_record(item)
        if not token:
            continue
        payload = get_json(
            f"https://boards-api.greenhouse.io/v1/boards/{token}/jobs",
            params={"content": "true"},
            **options,
        )
        for record in payload.get("jobs", []) if isinstance(payload, dict) else []:
            location_obj = record.get("location") or {}
            location = _text(location_obj.get("name") if isinstance(location_obj, dict) else location_obj)
            description = html_to_text(record.get("content"))
            departments = _list_of_text(record.get("departments"))
            offices = _list_of_text(record.get("offices"))
            company = configured_company or _text(payload.get("name")) or token
            location_text = location or ", ".join(offices) or "Location not listed"
            jobs.append(
                Job(
                    source="Greenhouse",
                    source_id=f"{token}:{_text(record.get('id'))}",
                    title=_text(record.get("title")),
                    company=company,
                    location=location_text,
                    url=_text(record.get("absolute_url")),
                    description=description,
                    posted_at=parse_datetime(record.get("updated_at") or record.get("created_at")),
                    employment_type="",
                    remote="remote" in location_text.lower(),
                    salary=parse_salary_text(description),
                    categories=[*departments, *offices],
                    source_url=_text(record.get("absolute_url")),
                    raw=dict(record),
                )
            )
    return jobs


def _lever_site(item: Any) -> tuple[str, str, str]:
    if isinstance(item, str):
        return item, item, "global"
    if isinstance(item, dict):
        site = _text(item.get("site") or item.get("token"))
        company = _text(item.get("company") or item.get("name") or site)
        region = _text(item.get("region") or "global").lower()
        return site, company, region
    return "", "", "global"


def fetch_lever(config: dict[str, Any]) -> list[Job]:
    settings = config.get("lever", {})
    if not settings.get("enabled", True):
        return []
    options = _http_options(config)
    jobs: list[Job] = []
    for item in settings.get("sites", []):
        site, company, region = _lever_site(item)
        if not site:
            continue
        host = "https://api.eu.lever.co" if region == "eu" else "https://api.lever.co"
        payload = get_json(f"{host}/v0/postings/{site}", params={"mode": "json"}, **options)
        records = payload if isinstance(payload, list) else []
        for record in records:
            categories_obj = record.get("categories") or {}
            category_values = []
            if isinstance(categories_obj, dict):
                for key in ("team", "department", "commitment", "level"):
                    value = categories_obj.get(key)
                    if value:
                        category_values.append(_text(value))
                category_values.extend(_list_of_text(categories_obj.get("allLocations")))
            description_parts = [
                record.get("descriptionPlain"),
                record.get("additionalPlain"),
            ]
            for extra in record.get("lists", []) or []:
                if isinstance(extra, dict):
                    description_parts.append(extra.get("text"))
                    description_parts.append(html_to_text(extra.get("content")))
            description = normalize_space(" ".join(_text(part) for part in description_parts if part))
            location = _text(categories_obj.get("location") if isinstance(categories_obj, dict) else "")
            workplace = _text(record.get("workplaceType"))
            if not location:
                location = workplace or "Location not listed"
            salary_obj = record.get("salaryRange") or {}
            salary = structured_salary(
                salary_obj.get("min") if isinstance(salary_obj, dict) else None,
                salary_obj.get("max") if isinstance(salary_obj, dict) else None,
                salary_obj.get("currency") if isinstance(salary_obj, dict) else None,
                salary_obj.get("interval") if isinstance(salary_obj, dict) else None,
                _text(record.get("salaryDescriptionPlain")) or None,
            )
            jobs.append(
                Job(
                    source="Lever",
                    source_id=f"{site}:{_text(record.get('id'))}",
                    title=_text(record.get("text")),
                    company=company,
                    location=location,
                    url=_text(record.get("hostedUrl") or record.get("applyUrl")),
                    description=description,
                    posted_at=parse_datetime(record.get("createdAt")),
                    employment_type=_text(categories_obj.get("commitment") if isinstance(categories_obj, dict) else ""),
                    remote=workplace.lower() == "remote" or "remote" in location.lower(),
                    salary=best_salary(salary, description),
                    categories=category_values,
                    source_url=_text(record.get("hostedUrl")),
                    raw=dict(record),
                )
            )
    return jobs


def _usajobs_description(descriptor: dict[str, Any]) -> str:
    user_area = descriptor.get("UserArea") or {}
    details = user_area.get("Details") if isinstance(user_area, dict) else {}
    parts = [
        descriptor.get("QualificationSummary"),
        descriptor.get("PositionTitle"),
        descriptor.get("OrganizationName"),
    ]
    if isinstance(details, dict):
        for key in (
            "JobSummary",
            "MajorDuties",
            "Education",
            "Requirements",
            "Evaluations",
            "HowToApply",
            "Benefits",
        ):
            parts.append(details.get(key))
    return normalize_space(" ".join(html_to_text(str(part)) for part in parts if part))


def fetch_usajobs(config: dict[str, Any]) -> list[Job]:
    settings = config.get("usajobs", {})
    if not settings.get("enabled", False):
        return []
    api_key = os.environ.get("USAJOBS_API_KEY", "").strip()
    email = os.environ.get("USAJOBS_EMAIL", "").strip()
    if not api_key or not email:
        raise FetchError("USAJOBS is enabled but USAJOBS_API_KEY or USAJOBS_EMAIL is missing")
    options = _http_options(config)
    headers = {
        "Host": "data.usajobs.gov",
        "User-Agent": email,
        "Authorization-Key": api_key,
    }
    jobs: list[Job] = []
    for keyword in settings.get("keywords", []):
        payload = get_json(
            "https://data.usajobs.gov/api/search",
            params={
                "Keyword": keyword,
                "LocationName": settings.get("location", "United States"),
                "DatePosted": int(settings.get("date_posted_days", 30)),
                "ResultsPerPage": int(settings.get("results_per_page", 100)),
            },
            headers=headers,
            **options,
        )
        search_result = payload.get("SearchResult", {}) if isinstance(payload, dict) else {}
        for item in search_result.get("SearchResultItems", []) if isinstance(search_result, dict) else []:
            descriptor = item.get("MatchedObjectDescriptor") or {}
            description = _usajobs_description(descriptor)
            remuneration = descriptor.get("PositionRemuneration") or []
            first_pay = remuneration[0] if remuneration and isinstance(remuneration[0], dict) else {}
            salary = structured_salary(
                first_pay.get("MinimumRange"),
                first_pay.get("MaximumRange"),
                "USD",
                first_pay.get("RateIntervalCode") or "annual",
            )
            schedules = descriptor.get("PositionSchedule") or []
            schedule_names = [
                _text(schedule.get("Name"))
                for schedule in schedules
                if isinstance(schedule, dict) and schedule.get("Name")
            ]
            locations = descriptor.get("PositionLocation") or []
            location_names = [
                _text(location.get("LocationName"))
                for location in locations
                if isinstance(location, dict) and location.get("LocationName")
            ]
            location = _text(descriptor.get("PositionLocationDisplay")) or ", ".join(location_names)
            user_area = descriptor.get("UserArea") or {}
            details = user_area.get("Details") if isinstance(user_area, dict) else {}
            telework = _text(details.get("TeleworkEligible") if isinstance(details, dict) else "")
            jobs.append(
                Job(
                    source="USAJOBS",
                    source_id=_text(descriptor.get("PositionID") or item.get("MatchedObjectId")),
                    title=_text(descriptor.get("PositionTitle")),
                    company=_text(descriptor.get("OrganizationName") or descriptor.get("DepartmentName")),
                    location=location or "United States",
                    url=_text(descriptor.get("PositionURI")),
                    description=description,
                    posted_at=parse_datetime(descriptor.get("PublicationStartDate")),
                    expires_at=parse_datetime(descriptor.get("ApplicationCloseDate")),
                    employment_type=", ".join(schedule_names),
                    remote="yes" in telework.lower() or "remote" in location.lower(),
                    salary=salary,
                    categories=[_text(descriptor.get("JobCategory", [{}])[0].get("Name"))]
                    if descriptor.get("JobCategory")
                    else [],
                    source_url=_text(descriptor.get("PositionURI")),
                    raw=dict(item),
                )
            )
    return jobs


_FETCHERS: list[tuple[str, str, Callable[[dict[str, Any]], list[Job]]]] = [
    ("Himalayas", "himalayas", fetch_himalayas),
    ("Remotive", "remotive", fetch_remotive),
    ("Arbeitnow", "arbeitnow", fetch_arbeitnow),
    ("Greenhouse", "greenhouse", fetch_greenhouse),
    ("Lever", "lever", fetch_lever),
    ("USAJOBS", "usajobs", fetch_usajobs),
]


def fetch_all_sources(config: dict[str, Any]) -> tuple[list[Job], list[SourceStatus]]:
    jobs: list[Job] = []
    statuses: list[SourceStatus] = []
    for source_name, config_key, fetcher in _FETCHERS:
        settings = config.get(config_key, {})
        if isinstance(settings, dict) and not settings.get("enabled", True):
            statuses.append(SourceStatus(source=source_name, ok=True, message="disabled"))
            continue
        if config_key == "greenhouse" and not settings.get("boards"):
            statuses.append(SourceStatus(source=source_name, ok=True, message="no boards configured"))
            continue
        if config_key == "lever" and not settings.get("sites"):
            statuses.append(SourceStatus(source=source_name, ok=True, message="no sites configured"))
            continue
        try:
            source_jobs = fetcher(config)
            jobs.extend(source_jobs)
            statuses.append(SourceStatus(source=source_name, ok=True, fetched=len(source_jobs)))
            LOGGER.info("Fetched %s jobs from %s", len(source_jobs), source_name)
        except Exception as exc:  # One broken feed must not erase the full daily digest.
            LOGGER.exception("Source %s failed", source_name)
            statuses.append(SourceStatus(source=source_name, ok=False, message=str(exc)))
    return jobs, statuses
