from __future__ import annotations

import json
import logging
import random
import time
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode, urlsplit, urlunsplit, parse_qsl
from urllib.request import Request, urlopen


LOGGER = logging.getLogger(__name__)


class FetchError(RuntimeError):
    pass


def add_query(url: str, params: dict[str, Any] | None) -> str:
    if not params:
        return url
    parts = urlsplit(url)
    query = parse_qsl(parts.query, keep_blank_values=True)
    for key, value in params.items():
        if value is None:
            continue
        if isinstance(value, (list, tuple)):
            query.extend((key, str(item)) for item in value)
        else:
            query.append((key, str(value)))
    return urlunsplit((parts.scheme, parts.netloc, parts.path, urlencode(query, doseq=True), parts.fragment))


def get_json(
    url: str,
    *,
    params: dict[str, Any] | None = None,
    headers: dict[str, str] | None = None,
    timeout: int = 30,
    retries: int = 3,
    user_agent: str = "job-fit-daily/1.0",
) -> Any:
    final_url = add_query(url, params)
    request_headers = {
        "Accept": "application/json",
        "User-Agent": user_agent,
    }
    if headers:
        request_headers.update(headers)

    last_error: Exception | None = None
    for attempt in range(max(1, retries)):
        request = Request(final_url, headers=request_headers, method="GET")
        try:
            with urlopen(request, timeout=timeout) as response:
                body = response.read()
                charset = response.headers.get_content_charset() or "utf-8"
                return json.loads(body.decode(charset))
        except HTTPError as exc:
            last_error = exc
            if exc.code not in {408, 425, 429, 500, 502, 503, 504} or attempt + 1 >= retries:
                break
            retry_after = exc.headers.get("Retry-After") if exc.headers else None
            try:
                delay = float(retry_after) if retry_after else 2 ** attempt
            except ValueError:
                delay = 2 ** attempt
            LOGGER.warning("HTTP %s from %s; retrying", exc.code, final_url)
            time.sleep(min(30.0, delay + random.random()))
        except (URLError, TimeoutError, json.JSONDecodeError, UnicodeDecodeError) as exc:
            last_error = exc
            if attempt + 1 >= retries:
                break
            LOGGER.warning("Fetch failed for %s; retrying: %s", final_url, exc)
            time.sleep(min(15.0, (2 ** attempt) + random.random()))
    raise FetchError(f"Unable to fetch {final_url}: {last_error}")
