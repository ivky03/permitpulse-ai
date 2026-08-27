"""Tiny dependency-free client for public Socrata datasets."""

from __future__ import annotations

import json
import os
import time
from collections.abc import Iterator
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen


class SocrataError(RuntimeError):
    """Raised when the NYC Open Data API cannot satisfy a request."""


class SocrataClient:
    def __init__(
        self,
        domain: str = "data.cityofnewyork.us",
        timeout_seconds: int = 45,
        retries: int = 3,
    ) -> None:
        self.domain = domain
        self.timeout_seconds = timeout_seconds
        self.retries = retries
        self.app_token = os.getenv("NYC_OPEN_DATA_APP_TOKEN")

    def metadata(self, dataset_id: str) -> dict[str, Any]:
        return self._get_json(f"https://{self.domain}/api/views/{dataset_id}")

    def rows(self, dataset_id: str, **soql: str | int) -> list[dict[str, Any]]:
        params = {f"${key}": value for key, value in soql.items() if value is not None}
        url = f"https://{self.domain}/resource/{dataset_id}.json"
        if params:
            url = f"{url}?{urlencode(params)}"
        payload = self._get_json(url)
        if not isinstance(payload, list):
            raise SocrataError(f"Expected a row list from {dataset_id}")
        return payload

    def iter_rows(
        self,
        dataset_id: str,
        *,
        page_size: int = 50_000,
        max_rows: int | None = None,
        **soql: str | int,
    ) -> Iterator[dict[str, Any]]:
        """Yield all matching rows using deterministic Socrata pagination."""
        offset = 0
        while max_rows is None or offset < max_rows:
            limit = page_size
            if max_rows is not None:
                limit = min(limit, max_rows - offset)
            page = self.rows(
                dataset_id,
                **soql,
                limit=limit,
                offset=offset,
            )
            if not page:
                break
            yield from page
            offset += len(page)
            if len(page) < limit:
                break

    def _get_json(self, url: str) -> Any:
        headers = {"User-Agent": "PermitPulseAI/0.1 (data viability audit)"}
        if self.app_token:
            headers["X-App-Token"] = self.app_token

        last_error: Exception | None = None
        for attempt in range(self.retries):
            try:
                with urlopen(
                    Request(url, headers=headers), timeout=self.timeout_seconds
                ) as response:
                    return json.load(response)
            except (HTTPError, URLError, TimeoutError) as exc:
                last_error = exc
                if attempt + 1 < self.retries:
                    time.sleep(2**attempt)

        raise SocrataError(f"Request failed after {self.retries} attempts: {last_error}")
