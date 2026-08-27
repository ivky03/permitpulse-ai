# PermitPulse AI — Stage 1 Dataset Checkpoint

Observation date: `2026-08-26`  
Source: official NYC DOB NOW Job Application Filings (`w9ak-ipjd`)  
Decision: **DATA CONTRACT PASSED**

## What Stage 1 produced

The pipeline downloads selected source rows into an immutable compressed raw
snapshot, cleans them into one unambiguous row per filing number, constructs
30/60/90-day labels, writes monthly censoring statistics, quarantines rejected
records, and records file hashes in a manifest.

The generated data files are intentionally excluded from Git. Run the pipeline
locally to reproduce them.

## Full-run results

| Check | Result |
| --- | ---: |
| Downloaded filings with a filing date by the observation date | 945,789 |
| Clean model rows | 945,546 |
| Rows quarantined for repeated filing numbers | 228 |
| Distinct repeated filing numbers quarantined | 93 |
| Rows quarantined for truly negative calendar-day durations | 15 |
| Completed non-negative processing-time observations | 572,902 |
| Median completed processing time | 21 days |
| 90th percentile completed processing time | 262 days |

The earlier Stage 0 audit counted 340 negative timestamp durations. Stage 1
confirmed that 325 of these occurred on the same calendar day: the filing time
was later than a midnight permit timestamp. Because this product predicts in
whole days, those are valid zero-day outcomes. Only 15 records cross into an
earlier calendar date.

## Fixed-horizon label results

| Target | Positive | Negative | Censored | Usable coverage |
| --- | ---: | ---: | ---: | ---: |
| Within 30 days | 324,751 | 610,091 | 10,704 | 98.87% |
| Within 60 days | 393,067 | 533,402 | 19,077 | 97.98% |
| Within 90 days | 432,652 | 485,468 | 27,426 | 97.10% |

“Censored” means the filing has not been observed for the complete target
window and has not yet received its first permit. It is excluded from training
for that target rather than mislabeled as a failure.

## Frozen rules

1. The initial product predicts first-permit issuance, not final project
   approval or code compliance.
2. Repeated filing numbers are quarantined rather than resolved by guesswork.
3. Dates are compared at calendar-day granularity.
4. `filing_status`, `current_status_date`, `approved_date`,
   `first_permit_date`, and `signoff_date` are blocked as model features.
5. Applicant names, exact addresses, and license numbers are not downloaded.
6. Recent unresolved cases remain censored until their target window passes.

## Next gate

Stage 2 should begin with a time-based train/validation/test split and a simple
non-ML baseline. Only after establishing that baseline should logistic
regression and gradient boosting be evaluated.
