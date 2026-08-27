# Data policy

Raw and processed data are generated locally and excluded from Git because the
complete snapshot is large. Stage 1 creates:

- `raw/*.jsonl.gz`: unchanged selected fields returned by NYC Open Data.
- `processed/*_model_*.csv.gz`: cleaned filing-level model table.
- `processed/cohort_coverage_*.csv`: label coverage by filing month.
- `processed/quarantine_*.jsonl.gz`: rejected rows with explicit reasons.
- `manifests/*.json`: source, extraction time, rules, row counts, and SHA-256
  hashes.

The raw snapshot is evidence and is never silently overwritten. Use
`--refresh` only when you intentionally want to redownload it.
