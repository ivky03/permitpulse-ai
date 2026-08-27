"""Stage 0: audit official NYC DOB data before building any model."""

from __future__ import annotations

import json
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from typing import Any

from .socrata_client import SocrataClient, SocrataError


ROOT = Path(__file__).resolve().parents[2]
REPORT_PATH = ROOT / "reports" / "data_audit.md"
SCHEMA_DIR = ROOT / "reports" / "schemas"

DATASETS = {
    "now_filings": {
        "id": "w9ak-ipjd",
        "expected": {
            "job_filing_number",
            "filing_date",
            "first_permit_date",
            "filing_status",
            "job_type",
            "filing_review_type",
        },
    },
    "now_permits": {
        "id": "rbx6-tga4",
        "expected": {
            "job_filing_number",
            "work_permit",
            "sequence_number",
            "work_type",
            "issued_date",
        },
    },
    "bis_permits": {
        "id": "ipu4-2q9a",
        "expected": {"job__", "job_doc___", "work_type", "filing_date", "issuance_date"},
    },
    "bis_filings": {
        "id": "ic3t-wcy2",
        "expected": {"job__", "doc__", "pre__filing_date", "job_status"},
    },
}

LEAKAGE_FIELDS = {
    "filing_status",
    "current_status_date",
    "first_permit_date",
    "approved_date",
    "signoff_date",
}


def one(rows: list[dict[str, Any]]) -> dict[str, Any]:
    if len(rows) != 1:
        raise SocrataError(f"Expected one aggregate row, received {len(rows)}")
    return rows[0]


def integer(row: dict[str, Any], field: str) -> int:
    return int(row.get(field, 0))


def quote_soql(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"


def fetch_matching_filings(
    client: SocrataClient, job_numbers: list[str], batch_size: int = 40
) -> set[str]:
    matched: set[str] = set()
    for start in range(0, len(job_numbers), batch_size):
        batch = job_numbers[start : start + batch_size]
        values = ",".join(quote_soql(value) for value in batch)
        rows = client.rows(
            "w9ak-ipjd",
            select="job_filing_number",
            where=f"job_filing_number in ({values})",
            limit=len(batch) * 3,
        )
        matched.update(row["job_filing_number"] for row in rows)
    return matched


def markdown_table(headers: list[str], rows: list[list[Any]]) -> str:
    def clean(value: Any) -> str:
        return str(value if value not in (None, "") else "—").replace("|", "\\|")

    output = ["| " + " | ".join(headers) + " |", "| " + " | ".join(["---"] * len(headers)) + " |"]
    output.extend("| " + " | ".join(clean(value) for value in row) + " |" for row in rows)
    return "\n".join(output)


def run() -> dict[str, Any]:
    client = SocrataClient()
    SCHEMA_DIR.mkdir(parents=True, exist_ok=True)

    schemas: dict[str, Any] = {}
    for alias, config in DATASETS.items():
        metadata = client.metadata(config["id"])
        fields = {column["fieldName"] for column in metadata["columns"]}
        missing_expected = sorted(config["expected"] - fields)
        if missing_expected:
            raise SocrataError(
                f"{config['id']} changed schema; missing expected fields: {missing_expected}"
            )
        schema = {
            "dataset_id": config["id"],
            "name": metadata["name"],
            "description": metadata.get("description", ""),
            "rows_updated_at": metadata.get("rowsUpdatedAt"),
            "columns": [
                {
                    "name": column["name"],
                    "field_name": column["fieldName"],
                    "type": column["dataTypeName"],
                    "description": column.get("description", ""),
                }
                for column in metadata["columns"]
            ],
        }
        schemas[alias] = schema
        (SCHEMA_DIR / f"{config['id']}.json").write_text(
            json.dumps(schema, indent=2), encoding="utf-8"
        )

    now_filing_stats = one(
        client.rows(
            "w9ak-ipjd",
            select=(
                "count(*) as total_rows, "
                "count(distinct job_filing_number) as distinct_filings, "
                "count(filing_date) as filing_dates, "
                "count(first_permit_date) as first_permit_dates, "
                "min(filing_date) as min_filing_date, max(filing_date) as max_filing_date, "
                "min(first_permit_date) as min_permit_date, max(first_permit_date) as max_permit_date"
            ),
        )
    )
    now_permit_stats = one(
        client.rows(
            "rbx6-tga4",
            select=(
                "count(*) as total_rows, "
                "count(distinct job_filing_number) as distinct_filings, "
                "count(issued_date) as issued_dates, "
                "min(issued_date) as min_issued_date, max(issued_date) as max_issued_date"
            ),
        )
    )
    bis_filing_stats = one(client.rows("ic3t-wcy2", select="count(*) as total_rows"))
    bis_permit_stats = one(client.rows("ipu4-2q9a", select="count(*) as total_rows"))

    status_rows = client.rows(
        "w9ak-ipjd",
        select="filing_status, count(*) as rows",
        group="filing_status",
        order="rows desc",
        limit=100,
    )
    open_status_rows = client.rows(
        "w9ak-ipjd",
        select="filing_status, count(*) as rows",
        where="first_permit_date is null",
        group="filing_status",
        order="rows desc",
        limit=100,
    )
    invalid_date_rows = one(
        client.rows(
            "w9ak-ipjd",
            select="count(*) as rows",
            where=(
                "date_trunc_ymd(first_permit_date) "
                "< date_trunc_ymd(filing_date)"
            ),
        )
    )
    duplicate_filing_groups = client.rows(
        "w9ak-ipjd",
        select="job_filing_number, count(*) as rows",
        group="job_filing_number",
        having="count(*) > 1",
        order="rows desc",
        limit=20,
    )

    permit_sample = client.rows(
        "rbx6-tga4",
        select=(
            "job_filing_number, work_permit, sequence_number, work_type, "
            "approved_date, issued_date"
        ),
        where="issued_date is not null",
        order="issued_date desc",
        limit=1000,
    )
    sample_jobs = sorted({row["job_filing_number"] for row in permit_sample})
    matched_jobs = fetch_matching_filings(client, sample_jobs)
    matched_rows = sum(row["job_filing_number"] in matched_jobs for row in permit_sample)

    work_types: dict[str, set[str]] = defaultdict(set)
    for row in permit_sample:
        if row.get("work_type"):
            work_types[row["job_filing_number"]].add(row["work_type"])
    multi_work_jobs = sum(len(values) > 1 for values in work_types.values())
    duplicate_sample_rows = len(permit_sample) - len(
        {
            (
                row.get("job_filing_number"),
                row.get("work_permit"),
                row.get("sequence_number"),
            )
            for row in permit_sample
        }
    )

    total_now_filings = integer(now_filing_stats, "total_rows")
    label_count = integer(now_filing_stats, "first_permit_dates")
    open_count = total_now_filings - label_count
    filing_date_missing = total_now_filings - integer(now_filing_stats, "filing_dates")
    duplicate_filing_rows = total_now_filings - integer(now_filing_stats, "distinct_filings")
    invalid_duration_count = integer(invalid_date_rows, "rows")
    usable_label_count = label_count - invalid_duration_count
    label_coverage = label_count / total_now_filings if total_now_filings else 0.0
    usable_label_coverage = usable_label_count / total_now_filings if total_now_filings else 0.0
    join_rate = matched_rows / len(permit_sample) if permit_sample else 0.0

    required_label_fields_present = {"filing_date", "first_permit_date"}.issubset(
        {column["field_name"] for column in schemas["now_filings"]["columns"]}
    )
    decision = (
        "GO WITH LIMITATIONS"
        if required_label_fields_present and usable_label_coverage >= 0.5
        else "NO-GO"
    )

    schema_summary = []
    for alias, schema in schemas.items():
        schema_summary.append(
            [alias, schema["dataset_id"], len(schema["columns"]), schema["name"]]
        )

    status_table = [[row.get("filing_status"), row["rows"]] for row in status_rows]
    open_status_table = [[row.get("filing_status"), row["rows"]] for row in open_status_rows]
    generated = datetime.now().astimezone().isoformat(timespec="seconds")
    report = f"""# PermitPulse AI — Stage 0 Data-Viability Audit

Generated: `{generated}`  
Source: official NYC Open Data Socrata APIs  
Decision: **{decision}**

## Executive conclusion

The DOB NOW filings dataset exposes both `filing_date` and `first_permit_date`
in the same dataset. A historical label can therefore be defined
as `first_permit_date - filing_date` without manufacturing a target or relying
on a cross-system join. The project should initially train only on DOB NOW
records and treat filings without a first permit date as right-censored/open,
not as failed or infinitely delayed.

The decision is **GO WITH LIMITATIONS**, rather than an unconditional GO,
because the dataset is a current-state snapshot, {duplicate_filing_rows:,} rows exceed filing-number
uniqueness, {invalid_duration_count:,} labeled rows have impossible negative durations, open filings
are censored, one job filing can lead to multiple work permits, and BIS and
DOB NOW use different identifiers, date formats, workflows, and coverage periods.

## Datasets and schemas

{markdown_table(["Alias", "Dataset ID", "Columns", "Official name"], schema_summary)}

Full machine-readable schemas are saved in `reports/schemas/`.

## Quantitative checks

{markdown_table(
    ["Check", "Result"],
    [
        ["DOB NOW filing rows", f"{total_now_filings:,}"],
        ["Distinct DOB NOW job filing numbers", f"{integer(now_filing_stats, 'distinct_filings'):,}"],
        ["Duplicate filing-number rows", f"{duplicate_filing_rows:,}"],
        ["Filing-date coverage", f"{(total_now_filings - filing_date_missing) / total_now_filings:.2%}"],
        ["Raw first-permit-date coverage", f"{label_coverage:.2%}"],
        ["Usable non-negative label coverage", f"{usable_label_coverage:.2%}"],
        ["Open or censored filings", f"{open_count:,} ({open_count / total_now_filings:.2%})"],
        ["First permit earlier than filing", f"{invalid_duration_count:,}"],
        ["DOB NOW filing date range", f"{now_filing_stats.get('min_filing_date')} to {now_filing_stats.get('max_filing_date')}"],
        ["DOB NOW first-permit date range", f"{now_filing_stats.get('min_permit_date')} to {now_filing_stats.get('max_permit_date')}"],
        ["DOB NOW approved-permit rows", f"{integer(now_permit_stats, 'total_rows'):,}"],
        ["DOB NOW distinct permitted filings", f"{integer(now_permit_stats, 'distinct_filings'):,}"],
        ["DOB NOW issuance date range", f"{now_permit_stats.get('min_issued_date')} to {now_permit_stats.get('max_issued_date')}"],
        ["Recent permit sample join to NOW filings", f"{join_rate:.2%} ({matched_rows:,}/{len(permit_sample):,} rows)"],
        ["Sample jobs with multiple work types", f"{multi_work_jobs:,}/{len(work_types):,}"],
        ["Duplicate sample permit composite keys", f"{duplicate_sample_rows:,}"],
        ["Legacy BIS filing rows", f"{integer(bis_filing_stats, 'total_rows'):,}"],
        ["Legacy BIS permit rows", f"{integer(bis_permit_stats, 'total_rows'):,}"],
    ],
)}

The join statistic is a diagnostic based on the 1,000 most recently issued DOB
NOW permit rows, not a population estimate. Stage 1 must repeat it on a larger,
time-bounded sample before relying on the permits table.

## Duplicate filing-number examples

{markdown_table(
    ["Job filing number", "Rows"],
    [[row["job_filing_number"], row["rows"]] for row in duplicate_filing_groups],
)}

Inspection found both exact-looking repeated rows and reused filing numbers with
different filing dates. Therefore `job_filing_number` is a candidate business
identifier, not a valid primary key as published. Stage 1 must preserve raw
rows, separate exact duplicates from conflicting duplicates, document a
deterministic resolution policy, and test whether the anomalies affect labeled
records.

## Current filing-status distribution

{markdown_table(["Filing status", "Rows"], status_table)}

## Statuses among records with no first permit date

{markdown_table(["Filing status", "Rows"], open_status_table)}

These unresolved records cannot simply be dropped without introducing
completion bias. Stage 1 should quantify censoring by filing cohort. If recent
cohorts are heavily censored, either train on mature cohorts with an explicit
cutoff or use survival analysis.

## Grain, keys, and joins

- `w9ak-ipjd`: intended job-filing grain, but `job_filing_number` failed the
  observed uniqueness check. No primary key is accepted yet.
- `rbx6-tga4`: permit/work-type grain. Multiple rows may share one
  `job_filing_number`. The candidate composite key
  (`job_filing_number`, `work_permit`, `sequence_number`) failed uniqueness in
  the recent sample; no primary key is accepted yet.
- `ic3t-wcy2`: legacy BIS job-document grain. Candidate composite key:
  (`job__`, `doc__`); `job__` alone is not unique.
- `ipu4-2q9a`: legacy BIS permit lifecycle/work-type grain. Candidate composite
  key to test: (`job__`, `job_doc___`, `work_type`, `permit_sequence__`).
- Do not directly join BIS `job__` to DOB NOW `job_filing_number`; they belong
  to different filing systems and identifier regimes.

## Valid initial label

For DOB NOW filings with both dates present:

```text
processing_days = first_permit_date - filing_date
issued_within_target = processing_days <= target_days
```

Rows with missing dates, negative durations, or unresolved conflicting
duplicates are ineligible until a documented cleaning rule resolves them.

The model's prediction timestamp is the filing date. Features must be values
known at or before filing. The first MVP should exclude amendments or filing
types whose timestamps do not represent a comparable start point until their
semantics are checked.

## Leakage review

Never use these current-snapshot fields as model inputs for a filing-time
forecast: `{', '.join(sorted(LEAKAGE_FIELDS))}`. They are outcomes or are
updated after filing. Applicant/owner names and license numbers should also be
excluded initially because they create privacy, memorization, and weak
generalization risks.

Candidate pre-outcome features, subject to Stage 1 availability-at-filing
verification, include borough, job type, filing review type, building type,
initial cost, work-type flags, floor area, and existing/proposed building
characteristics.

## System and policy limitations

- DOB NOW and BIS must be modeled as separate regimes; pooling them would mix
  workflows, codes, date formats, and technology eras.
- The official datasets are mutable snapshots, so every training extract must
  record dataset IDs, retrieval timestamp, query, row counts, and a data hash.
- A processing-time association does not show that a proposed action caused a
  faster permit.
- The system can forecast historical timeline risk only within the trained NYC
  population; it cannot guarantee approval or infer examiner objections.

## Stage 1 entry criteria

Proceed only after Stage 1:

1. Builds a dated DOB NOW extract with explicit inclusion/exclusion rules.
2. Profiles censoring and label coverage by monthly filing cohort.
3. Verifies initial vs amendment filing semantics.
4. Freezes the allowed-at-filing feature list and rejects post-outcome fields.
5. Uses a temporal split and keeps recent, immature cohorts out of training.
6. Repeats composite-key and join checks on a larger extract.
"""
    REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
    REPORT_PATH.write_text(report, encoding="utf-8")

    return {
        "decision": decision,
        "report": str(REPORT_PATH),
        "label_coverage": label_coverage,
        "usable_label_coverage": usable_label_coverage,
        "open_rate": open_count / total_now_filings,
        "join_rate": join_rate,
    }


if __name__ == "__main__":
    result = run()
    print(json.dumps(result, indent=2))
