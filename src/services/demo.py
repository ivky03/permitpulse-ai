"""Run one end-to-end Stage 3 evidence demo."""

from __future__ import annotations

import json

from src.retrieval.comparables import ComparableStore

from .risk_service import RiskService


def main() -> None:
    store = ComparableStore()
    job_number, request = store.example()
    result = RiskService().assess(request, exclude_job=job_number)
    print(json.dumps({"example_job": job_number, **result}, indent=2, default=str))


if __name__ == "__main__":
    main()
