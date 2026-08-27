# PermitPulse AI

PermitPulse AI estimates whether an NYC construction permit is likely to be
issued before a project target date, retrieves comparable historical permits,
and proposes an administratively valid next step for project-manager approval.

## Current checkpoint: Stage 1

Stage 0 established `GO WITH LIMITATIONS`. Stage 1 is complete: it downloads a
reproducible raw snapshot and builds a leakage-safe, filing-level table. No
model or agent code is added before this data contract passes.

## macOS + VS Code setup

```bash
git clone <your-repository-url>
cd permitpulse-ai
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m unittest discover -v

# Fast development proof: download and clean 5,000 live rows
python -m src.data.build_dataset --observation-date 2026-08-26 --max-rows 5000

# Full snapshot: omit --max-rows (this may take several minutes)
python -m src.data.build_dataset --observation-date 2026-08-26
```

Stage 1 stores compressed outputs under `data/`. These large reproducible files
are excluded from Git; their manifest records provenance, cleaning results,
the feature policy, and cryptographic hashes.

Optional: copy `.env.example` to `.env`, add a Socrata app token, and export it
before running the audit. Never commit `.env`.

## Scope boundary

This is a planning-support tool. It does not determine code compliance,
predict examiner objections, guarantee issuance dates, or replace a licensed
professional or DOB examiner.

## Stage 1 rules worth defending

- The API supplies the raw facts; our code only selects, cleans, and labels.
- Every repeated `job_filing_number` is quarantined. There are very few, and
  guessing which conflicting row is correct would be harder to defend.
- A missing permit is a negative for a 30-day target only after 30 days have
  elapsed. More recent unresolved filings remain censored and are not trained
  as failures.
- Outcome and post-filing status fields never enter the model feature list.
- Applicant names, exact addresses, and license numbers are not downloaded
  because the initial model does not need them.
