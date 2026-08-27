"""Build and query a compact DuckDB index of completed permit filings."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
from pathlib import Path
from typing import Any

import duckdb
import pandas as pd

from src.data.build_dataset import MODEL_FEATURES, NUMERIC_FEATURES
from src.modeling.train import ROOT, find_full_dataset


DATABASE_PATH = ROOT / "artifacts" / "comparables.duckdb"
WORK_TYPE_FEATURES = [
    column
    for column in MODEL_FEATURES
    if "work_type" in column
    or column
    in {
        "standpipe",
        "antenna",
        "sign",
        "curb_cut",
        "fence",
        "scaffold",
        "shed",
    }
]
CORE_COLUMNS = [
    "job_filing_number",
    "filing_date",
    "borough",
    "job_type",
    "filing_review_type",
    "building_type",
    "initial_cost",
    "total_construction_floor_area",
    "processing_days",
    "issued_within_30_days",
]
INDEX_COLUMNS = list(dict.fromkeys([*CORE_COLUMNS, *MODEL_FEATURES]))


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def build_index(data_path: Path, database_path: Path = DATABASE_PATH) -> dict[str, Any]:
    database_path.parent.mkdir(parents=True, exist_ok=True)
    database_path.unlink(missing_ok=True)
    connection = duckdb.connect(str(database_path))
    selected_expressions = []
    for column in INDEX_COLUMNS:
        quoted = f'"{column}"'
        if column == "filing_date":
            selected_expressions.append(f"TRY_CAST({quoted} AS DATE) AS {quoted}")
        elif column in NUMERIC_FEATURES:
            selected_expressions.append(f"TRY_CAST({quoted} AS DOUBLE) AS {quoted}")
        elif column in {"processing_days", "issued_within_30_days"}:
            selected_expressions.append(f"TRY_CAST({quoted} AS INTEGER) AS {quoted}")
        else:
            selected_expressions.append(quoted)
    selected = ", ".join(selected_expressions)
    try:
        connection.execute(
            f"""
            CREATE TABLE comparable_filings AS
            SELECT {selected}
            FROM read_csv_auto(?, header=true, all_varchar=true)
            WHERE TRY_CAST(processing_days AS INTEGER) >= 0
            """,
            [str(data_path.resolve())],
        )
        connection.execute(
            "CREATE INDEX comparable_group_idx ON comparable_filings "
            "(job_type, filing_review_type, borough)"
        )
        row_count = connection.execute(
            "SELECT count(*) FROM comparable_filings"
        ).fetchone()[0]
        connection.execute("CREATE TABLE index_metadata (key VARCHAR, value VARCHAR)")
        metadata = {
            "source_path": str(data_path),
            "source_sha256": sha256_file(data_path),
            "rows": int(row_count),
        }
        connection.executemany(
            "INSERT INTO index_metadata VALUES (?, ?)",
            [(key, json.dumps(value)) for key, value in metadata.items()],
        )
    finally:
        connection.close()
    return metadata


def active_work_types(row: dict[str, Any]) -> set[str]:
    return {
        column
        for column in WORK_TYPE_FEATURES
        if str(row.get(column, "")).strip().upper() == "YES"
    }


def numeric_distance(left: Any, right: Any) -> float:
    try:
        left_number = max(0.0, float(left))
        right_number = max(0.0, float(right))
    except (TypeError, ValueError):
        return 1.0
    return min(abs(math.log1p(left_number) - math.log1p(right_number)), 4.0) / 4.0


def similarity_score(request: dict[str, Any], candidate: dict[str, Any]) -> float:
    score = 0.0
    for column, weight in (
        ("job_type", 4.0),
        ("filing_review_type", 3.0),
        ("borough", 2.0),
        ("building_type", 1.0),
    ):
        if request.get(column) and request.get(column) == candidate.get(column):
            score += weight
    score += 1.5 * (
        1.0
        - numeric_distance(request.get("initial_cost"), candidate.get("initial_cost"))
    )
    score += 1.0 * (
        1.0
        - numeric_distance(
            request.get("total_construction_floor_area"),
            candidate.get("total_construction_floor_area"),
        )
    )
    request_work = active_work_types(request)
    candidate_work = active_work_types(candidate)
    union = request_work | candidate_work
    if union:
        score += 2.0 * len(request_work & candidate_work) / len(union)
    return score


class ComparableStore:
    def __init__(self, database_path: Path = DATABASE_PATH) -> None:
        if not database_path.exists():
            raise FileNotFoundError(
                "Comparable index is missing. Run `python -m src.retrieval.comparables` first."
            )
        self.database_path = database_path

    def _candidates(
        self, request: dict[str, Any], exclude_job: str | None, pool_size: int
    ) -> tuple[pd.DataFrame, str]:
        filters = [
            (
                "borough = ? AND job_type = ? AND filing_review_type = ?",
                [
                    request.get("borough"),
                    request.get("job_type"),
                    request.get("filing_review_type"),
                ],
                "borough + job type + review type",
            ),
            (
                "job_type = ? AND filing_review_type = ?",
                [request.get("job_type"), request.get("filing_review_type")],
                "job type + review type",
            ),
            ("job_type = ?", [request.get("job_type")], "job type"),
        ]
        selected = ", ".join(f'"{column}"' for column in INDEX_COLUMNS)
        connection = duckdb.connect(str(self.database_path), read_only=True)
        try:
            for condition, parameters, scope in filters:
                if any(value in (None, "") for value in parameters):
                    continue
                exclusion = " AND job_filing_number <> ?" if exclude_job else ""
                query_parameters = [*parameters, *([exclude_job] if exclude_job else [])]
                frame = connection.execute(
                    f"""
                    SELECT {selected}
                    FROM comparable_filings
                    WHERE {condition}{exclusion}
                    ORDER BY filing_date DESC, job_filing_number
                    LIMIT {int(pool_size)}
                    """,
                    query_parameters,
                ).fetchdf()
                if len(frame) >= 12 or scope == "job type":
                    return frame, scope
        finally:
            connection.close()
        return pd.DataFrame(columns=INDEX_COLUMNS), "no comparable scope"

    def retrieve(
        self,
        request: dict[str, Any],
        limit: int = 12,
        exclude_job: str | None = None,
        pool_size: int = 5_000,
    ) -> dict[str, Any]:
        candidates, scope = self._candidates(request, exclude_job, pool_size)
        records = candidates.where(pd.notna(candidates), None).to_dict("records")
        for record in records:
            record["similarity_score"] = similarity_score(request, record)
        records.sort(
            key=lambda row: (
                -row["similarity_score"],
                str(row.get("job_filing_number", "")),
            )
        )
        selected = records[:limit]
        processing = [int(row["processing_days"]) for row in selected]
        delayed = sum(int(row["issued_within_30_days"]) == 0 for row in selected)
        public_rows = [
            {
                "job_filing_number": row["job_filing_number"],
                "filing_date": str(row["filing_date"])[:10],
                "borough": row.get("borough"),
                "job_type": row.get("job_type"),
                "filing_review_type": row.get("filing_review_type"),
                "processing_days": int(row["processing_days"]),
                "issued_within_30_days": bool(int(row["issued_within_30_days"])),
                "similarity_score": round(float(row["similarity_score"]), 3),
            }
            for row in selected
        ]
        return {
            "scope": scope,
            "count": len(public_rows),
            "coverage_note": (
                "Processing-time comparables include only filings with an observed first permit."
            ),
            "median_processing_days": (
                float(pd.Series(processing).median()) if processing else None
            ),
            "p25_processing_days": (
                float(pd.Series(processing).quantile(0.25)) if processing else None
            ),
            "p75_processing_days": (
                float(pd.Series(processing).quantile(0.75)) if processing else None
            ),
            "delayed_count": delayed,
            "comparables": public_rows,
        }

    def example(self) -> tuple[str, dict[str, Any]]:
        selected = ", ".join(f'"{column}"' for column in MODEL_FEATURES)
        connection = duckdb.connect(str(self.database_path), read_only=True)
        try:
            row = connection.execute(
                f"""
                SELECT job_filing_number, {selected}
                FROM comparable_filings
                WHERE borough = 'Queens'
                  AND job_type = 'Alteration'
                  AND filing_review_type = 'Standard Plan Examination'
                ORDER BY filing_date DESC, job_filing_number
                LIMIT 1
                """
            ).fetchdf().iloc[0]
        finally:
            connection.close()
        values = row.where(pd.notna(row), None).to_dict()
        return str(values.pop("job_filing_number")), values


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-path", type=Path, default=None)
    parser.add_argument("--database-path", type=Path, default=DATABASE_PATH)
    args = parser.parse_args()
    metadata = build_index(args.data_path or find_full_dataset(), args.database_path)
    print(json.dumps(metadata, indent=2))


if __name__ == "__main__":
    main()
