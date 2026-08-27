"""Stage 1: cache and clean official DOB NOW filing data."""

from __future__ import annotations

import argparse
import csv
import gzip
import hashlib
import io
import json
import math
from collections import Counter, defaultdict
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any, Iterable, TextIO

from .socrata_client import SocrataClient


ROOT = Path(__file__).resolve().parents[2]
DATASET_ID = "w9ak-ipjd"
TARGET_DAYS = (30, 60, 90)

# These are known at filing time. Names, exact addresses, and license numbers
# are unnecessary for the first model and are deliberately not downloaded.
MODEL_FEATURES = (
    "borough",
    "commmunity_board",
    "job_type",
    "filing_review_type",
    "applicant_professional_title",
    "owner_type",
    "building_type",
    "review_building_code",
    "initial_cost",
    "total_construction_floor_area",
    "existing_stories",
    "existing_height",
    "existing_dwelling_units",
    "proposed_no_of_stories",
    "proposed_height",
    "proposed_dwelling_units",
    "little_e",
    "request_legalization",
    "includes_permanent_removal",
    "in_compliance_with_nycecc",
    "exempt_from_nycecc",
    "sprinkler_work_type",
    "plumbing_work_type",
    "standpipe",
    "antenna",
    "sign",
    "curb_cut",
    "fence",
    "scaffold",
    "shed",
    "boiler_equipment_work_type_",
    "earth_work_work_type_",
    "foundation_work_type_",
    "general_construction_work_type_",
    "mechanical_systems_work_type_",
    "place_of_assembly_work_type_",
    "protection_mechanical_methods_work_type_",
    "sidewalk_shed_work_type_",
    "structural_work_type_",
    "support_of_excavation_work_type_",
    "temporary_place_of_assembly_work_type_",
    "green_roof_work_type_",
    "solar_work_type_",
    "full_demolition_work_type_",
    "suspended_scaffold_work_type_",
)
NUMERIC_FEATURES = {
    "initial_cost",
    "total_construction_floor_area",
    "existing_stories",
    "existing_height",
    "existing_dwelling_units",
    "proposed_no_of_stories",
    "proposed_height",
    "proposed_dwelling_units",
}
LEAKAGE_FIELDS = {
    "filing_status",
    "current_status_date",
    "first_permit_date",
    "approved_date",
    "signoff_date",
}


def parse_date(value: str | None) -> date | None:
    if not value:
        return None
    return date.fromisoformat(value[:10])


def parse_number(value: Any) -> float | None:
    if value in (None, ""):
        return None
    try:
        number = float(str(value).replace("$", "").replace(",", "").strip())
    except ValueError:
        return None
    return number if math.isfinite(number) else None


def label_within_target(
    filing_date: date,
    first_permit_date: date | None,
    observation_date: date,
    target_days: int,
) -> bool | None:
    """Return True/False when known, or None while the case is censored."""
    age_days = (observation_date - filing_date).days
    if first_permit_date is not None:
        processing_days = (first_permit_date - filing_date).days
        if processing_days <= target_days:
            return True
    if age_days >= target_days:
        return False
    return None


def normalized_row(row: dict[str, Any]) -> dict[str, Any]:
    cleaned: dict[str, Any] = {}
    for field in MODEL_FEATURES:
        value = row.get(field)
        if field in NUMERIC_FEATURES:
            value = parse_number(value)
        elif isinstance(value, str):
            value = value.strip() or None
        cleaned[field] = value
    return cleaned


def open_gzip_text(path: Path, mode: str) -> TextIO:
    """Open gzip text and use a stable timestamp for written archives."""
    if "w" in mode:
        binary = gzip.GzipFile(filename=str(path), mode="wb", mtime=0)
        return io.TextIOWrapper(binary, encoding="utf-8", newline="")
    return gzip.open(path, mode, encoding="utf-8", newline="")


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def snapshot_paths(
    output_root: Path, observation_date: date, max_rows: int | None
) -> dict[str, Path]:
    suffix = observation_date.isoformat()
    if max_rows is not None:
        suffix += f"_sample_{max_rows}"
    return {
        "raw": output_root / "raw" / f"dob_now_filings_{suffix}.jsonl.gz",
        "processed": output_root / "processed" / f"dob_now_filings_model_{suffix}.csv.gz",
        "manifest": output_root / "manifests" / f"dob_now_filings_{suffix}.json",
        "cohorts": output_root / "processed" / f"cohort_coverage_{suffix}.csv",
        "quarantine": output_root / "processed" / f"quarantine_{suffix}.jsonl.gz",
    }


def download_raw(
    client: SocrataClient,
    path: Path,
    observation_date: date,
    max_rows: int | None,
) -> int:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".part")
    select = ":id as source_row_id," + ",".join(
        ("job_filing_number", "filing_date", "first_permit_date", *MODEL_FEATURES)
    )
    count = 0
    try:
        with open_gzip_text(temporary, "wt") as handle:
            for row in client.iter_rows(
                DATASET_ID,
                select=select,
                where=f"filing_date <= '{observation_date.isoformat()}T23:59:59'",
                order=":id",
                page_size=50_000,
                max_rows=max_rows,
            ):
                handle.write(
                    json.dumps(row, sort_keys=True, separators=(",", ":")) + "\n"
                )
                count += 1
        temporary.replace(path)
    except Exception:
        temporary.unlink(missing_ok=True)
        raise
    return count


def read_json_lines(path: Path) -> Iterable[dict[str, Any]]:
    with open_gzip_text(path, "rt") as handle:
        for line in handle:
            yield json.loads(line)


def write_quarantine(handle: TextIO, reason: str, row: dict[str, Any]) -> None:
    handle.write(json.dumps({"reason": reason, "row": row}, sort_keys=True) + "\n")


def clean_snapshot(
    raw_path: Path,
    processed_path: Path,
    quarantine_path: Path,
    cohort_path: Path,
    observation_date: date,
) -> dict[str, Any]:
    counts = Counter(row.get("job_filing_number") for row in read_json_lines(raw_path))
    duplicate_ids = {key for key, value in counts.items() if key and value > 1}
    processed_path.parent.mkdir(parents=True, exist_ok=True)
    temporary_processed = processed_path.with_suffix(processed_path.suffix + ".part")
    temporary_quarantine = quarantine_path.with_suffix(quarantine_path.suffix + ".part")
    cohorts: dict[tuple[str, int], Counter[str]] = defaultdict(Counter)
    stats: Counter[str] = Counter()

    output_fields = [
        "job_filing_number",
        "filing_date",
        *MODEL_FEATURES,
        "processing_days",
        *(f"issued_within_{days}_days" for days in TARGET_DAYS),
    ]
    try:
        with (
            open_gzip_text(temporary_processed, "wt") as processed_handle,
            open_gzip_text(temporary_quarantine, "wt") as quarantine_handle,
        ):
            writer = csv.DictWriter(processed_handle, fieldnames=output_fields)
            writer.writeheader()
            for row in read_json_lines(raw_path):
                stats["raw_rows"] += 1
                job_number = row.get("job_filing_number")
                filing = parse_date(row.get("filing_date"))
                permit = parse_date(row.get("first_permit_date"))
                if not job_number or filing is None:
                    stats["missing_key_or_filing_date"] += 1
                    write_quarantine(quarantine_handle, "missing_key_or_filing_date", row)
                    continue
                if job_number in duplicate_ids:
                    stats["duplicate_job_filing_number"] += 1
                    write_quarantine(quarantine_handle, "duplicate_job_filing_number", row)
                    continue
                if filing > observation_date:
                    stats["filing_after_observation_date"] += 1
                    write_quarantine(quarantine_handle, "filing_after_observation_date", row)
                    continue
                if permit is not None and (permit < filing or permit > observation_date):
                    stats["invalid_permit_date"] += 1
                    write_quarantine(quarantine_handle, "invalid_permit_date", row)
                    continue

                output = {
                    "job_filing_number": job_number,
                    "filing_date": filing.isoformat(),
                    **normalized_row(row),
                    "processing_days": (permit - filing).days if permit else None,
                }
                cohort = filing.strftime("%Y-%m")
                for days in TARGET_DAYS:
                    label = label_within_target(filing, permit, observation_date, days)
                    output[f"issued_within_{days}_days"] = (
                        "1" if label is True else "0" if label is False else ""
                    )
                    bucket = (
                        "positive"
                        if label is True
                        else "negative"
                        if label is False
                        else "censored"
                    )
                    cohorts[(cohort, days)][bucket] += 1
                writer.writerow(output)
                stats["clean_rows"] += 1

        temporary_processed.replace(processed_path)
        temporary_quarantine.replace(quarantine_path)
    except Exception:
        temporary_processed.unlink(missing_ok=True)
        temporary_quarantine.unlink(missing_ok=True)
        raise

    with cohort_path.open("w", encoding="utf-8", newline="") as handle:
        fields = [
            "filing_month",
            "target_days",
            "positive",
            "negative",
            "censored",
            "total",
            "label_coverage",
        ]
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        for (month, days), values in sorted(cohorts.items()):
            total = sum(values.values())
            observed = values["positive"] + values["negative"]
            writer.writerow(
                {
                    "filing_month": month,
                    "target_days": days,
                    "positive": values["positive"],
                    "negative": values["negative"],
                    "censored": values["censored"],
                    "total": total,
                    "label_coverage": f"{observed / total:.6f}" if total else "",
                }
            )

    stats["duplicate_ids_quarantined"] = len(duplicate_ids)
    return dict(stats)


def run(
    observation_date: date,
    output_root: Path,
    max_rows: int | None,
    refresh: bool,
) -> dict[str, Any]:
    paths = snapshot_paths(output_root, observation_date, max_rows)
    paths["manifest"].parent.mkdir(parents=True, exist_ok=True)
    if refresh or not paths["raw"].exists():
        downloaded = download_raw(
            SocrataClient(), paths["raw"], observation_date, max_rows
        )
    else:
        downloaded = sum(1 for _ in read_json_lines(paths["raw"]))

    cleaning = clean_snapshot(
        paths["raw"],
        paths["processed"],
        paths["quarantine"],
        paths["cohorts"],
        observation_date,
    )
    manifest = {
        "dataset_id": DATASET_ID,
        "source": f"https://data.cityofnewyork.us/resource/{DATASET_ID}.json",
        "extracted_at_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "observation_date": observation_date.isoformat(),
        "is_sample": max_rows is not None,
        "max_rows": max_rows,
        "downloaded_rows": downloaded,
        "query": {
            "select": [
                "source_row_id",
                "job_filing_number",
                "filing_date",
                "first_permit_date",
                *MODEL_FEATURES,
            ],
            "where": f"filing_date <= {observation_date.isoformat()}",
            "order": ":id",
        },
        "model_features": list(MODEL_FEATURES),
        "fields_used_only_for_splitting_or_labels": [
            "filing_date",
            "first_permit_date",
        ],
        "leakage_fields_blocked": sorted(LEAKAGE_FIELDS),
        "cleaning": cleaning,
        "files": {
            key: {
                "path": str(path.relative_to(output_root)),
                "sha256": sha256_file(path),
            }
            for key, path in paths.items()
            if key != "manifest"
        },
    }
    paths["manifest"].write_text(
        json.dumps(manifest, indent=2) + "\n", encoding="utf-8"
    )
    return manifest


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--observation-date", type=date.fromisoformat, default=date.today()
    )
    parser.add_argument("--output-root", type=Path, default=ROOT / "data")
    parser.add_argument(
        "--max-rows",
        type=int,
        default=None,
        help="Development sample size; omit for full data",
    )
    parser.add_argument(
        "--refresh", action="store_true", help="Redownload an existing raw snapshot"
    )
    args = parser.parse_args()
    manifest = run(
        args.observation_date, args.output_root, args.max_rows, args.refresh
    )
    print(json.dumps(manifest, indent=2))


if __name__ == "__main__":
    main()
