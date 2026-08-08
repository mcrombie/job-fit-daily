from __future__ import annotations

import re
from typing import Any

from .models import Salary
from .text import normalize_space, normalized


_PERIOD_MULTIPLIERS = {
    "annual": 1.0,
    "annually": 1.0,
    "year": 1.0,
    "yearly": 1.0,
    "per year": 1.0,
    "month": 12.0,
    "monthly": 12.0,
    "per month": 12.0,
    "week": 52.0,
    "weekly": 52.0,
    "per week": 52.0,
    "fortnightly": 26.0,
    "biweekly": 26.0,
    "hour": 2080.0,
    "hourly": 2080.0,
    "per hour": 2080.0,
}


def _number(value: Any) -> float | None:
    if value in (None, ""):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    text = str(value).strip().lower().replace(",", "")
    multiplier = 1.0
    if text.endswith("k"):
        text = text[:-1]
        multiplier = 1000.0
    try:
        return float(text) * multiplier
    except ValueError:
        return None


def annualize(value: float | None, period: str | None) -> float | None:
    if value is None:
        return None
    key = normalized(period or "annual")
    multiplier = _PERIOD_MULTIPLIERS.get(key)
    if multiplier is None:
        if "hour" in key:
            multiplier = 2080.0
        elif "month" in key:
            multiplier = 12.0
        elif "week" in key:
            multiplier = 52.0
        else:
            multiplier = 1.0
    return value * multiplier


def structured_salary(
    minimum: Any,
    maximum: Any,
    currency: str | None = "USD",
    period: str | None = "annual",
    raw: str | None = None,
) -> Salary:
    min_value = _number(minimum)
    max_value = _number(maximum)
    currency_code = (currency or "").upper() or None
    annual_min = annualize(min_value, period) if currency_code == "USD" else None
    annual_max = annualize(max_value, period) if currency_code == "USD" else None
    return Salary(
        minimum=min_value,
        maximum=max_value,
        currency=currency_code,
        period=period,
        raw=raw,
        annual_minimum_usd=annual_min,
        annual_maximum_usd=annual_max,
    )


_RANGE_PATTERNS = (
    # $80,000 - $110,000 per year / USD 80k–110k annually
    re.compile(
        r"(?P<currency>\$|usd\s*)"
        r"(?P<min>\d{2,3}(?:[,.]\d{3})*(?:\.\d+)?\s*[kK]?)"
        r"\s*(?:-|–|—|to)\s*"
        r"(?:\$|usd\s*)?"
        r"(?P<max>\d{2,3}(?:[,.]\d{3})*(?:\.\d+)?\s*[kK]?)"
        r"(?:\s*(?:/|per\s+)?(?P<period>hour|hr|year|yr|month|week|annum|annually|yearly|hourly|monthly|weekly))?",
        re.IGNORECASE,
    ),
    # 80k-110k USD
    re.compile(
        r"(?P<min>\d{2,3}(?:\.\d+)?\s*[kK])\s*(?:-|–|—|to)\s*"
        r"(?P<max>\d{2,3}(?:\.\d+)?\s*[kK])\s*(?P<currency>usd)"
        r"(?:\s*(?:/|per\s+)?(?P<period>hour|year|month|week|annually|hourly|monthly|weekly))?",
        re.IGNORECASE,
    ),
)

_SINGLE_PATTERN = re.compile(
    r"(?P<currency>\$|usd\s*)"
    r"(?P<value>\d{2,3}(?:[,.]\d{3})*(?:\.\d+)?\s*[kK]?)"
    r"\s*(?:\+|or more|minimum)?"
    r"(?:\s*(?:/|per\s+)?(?P<period>hour|hr|year|yr|month|week|annum|annually|yearly|hourly|monthly|weekly))",
    re.IGNORECASE,
)


def _normalize_period(period: str | None, values: list[float | None]) -> str:
    if period:
        word = normalized(period)
        if word in {"hr", "hour", "hourly"}:
            return "hourly"
        if word in {"yr", "year", "annum", "annually", "yearly"}:
            return "annual"
        if "month" in word:
            return "monthly"
        if "week" in word:
            return "weekly"
    # Values below 500 with a currency symbol are much more likely hourly than annual.
    non_null = [value for value in values if value is not None]
    if non_null and max(non_null) < 500:
        return "hourly"
    return "annual"


def parse_salary_text(text: str | None) -> Salary:
    if not text:
        return Salary()
    compact = normalize_space(text)
    for pattern in _RANGE_PATTERNS:
        match = pattern.search(compact)
        if not match:
            continue
        minimum = _number(match.group("min"))
        maximum = _number(match.group("max"))
        period = _normalize_period(match.groupdict().get("period"), [minimum, maximum])
        raw = match.group(0)
        return structured_salary(minimum, maximum, "USD", period, raw)
    match = _SINGLE_PATTERN.search(compact)
    if match:
        value = _number(match.group("value"))
        period = _normalize_period(match.groupdict().get("period"), [value])
        return structured_salary(value, None, "USD", period, match.group(0))
    return Salary(raw=compact[:300])


def best_salary(primary: Salary | None, fallback_text: str | None) -> Salary:
    if primary and (primary.minimum is not None or primary.maximum is not None):
        return primary
    parsed = parse_salary_text(fallback_text)
    if primary and primary.raw and not parsed.raw:
        parsed.raw = primary.raw
    return parsed


def salary_display(salary: Salary) -> str:
    if salary.raw and not salary.known_usd:
        return salary.raw
    minimum = salary.annual_minimum_usd
    maximum = salary.annual_maximum_usd
    if minimum is not None and maximum is not None:
        return f"${minimum:,.0f}–${maximum:,.0f} / year"
    if minimum is not None:
        return f"From ${minimum:,.0f} / year"
    if maximum is not None:
        return f"Up to ${maximum:,.0f} / year"
    if salary.raw:
        return salary.raw
    return "Salary not listed"
