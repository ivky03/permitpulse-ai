# PermitPulse AI — Stage 0 Data-Viability Audit

Generated: `2026-08-25T18:41:28-06:00`  
Source: official NYC Open Data Socrata APIs  
Decision: **GO WITH LIMITATIONS**

## Executive conclusion

The DOB NOW filings dataset exposes both `filing_date` and `first_permit_date`
in the same dataset. A historical label can therefore be defined
as `first_permit_date - filing_date` without manufacturing a target or relying
on a cross-system join. The project should initially train only on DOB NOW
records and treat filings without a first permit date as right-censored/open,
not as failed or infinitely delayed.

The decision is **GO WITH LIMITATIONS**, rather than an unconditional GO,
because the dataset is a current-state snapshot, 137 rows exceed filing-number
uniqueness, 15 labeled rows have impossible negative calendar-day durations, open filings
are censored, one job filing can lead to multiple work permits, and BIS and
DOB NOW use different identifiers, date formats, workflows, and coverage periods.

## Datasets and schemas

| Alias | Dataset ID | Columns | Official name |
| --- | --- | --- | --- |
| now_filings | w9ak-ipjd | 95 | DOB NOW: Build – Job Application Filings |
| now_permits | rbx6-tga4 | 46 | DOB NOW: Build – Approved Permits |
| bis_permits | ipu4-2q9a | 60 | DOB Permit Issuance |
| bis_filings | ic3t-wcy2 | 95 | DOB Job Application Filings |

Full machine-readable schemas are saved in `reports/schemas/`.

## Quantitative checks

| Check | Result |
| --- | --- |
| DOB NOW filing rows | 947,954 |
| Distinct DOB NOW job filing numbers | 947,817 |
| Duplicate filing-number rows | 137 |
| Filing-date coverage | 99.70% |
| Raw first-permit-date coverage | 60.40% |
| Usable non-negative label coverage | 60.40% |
| Open or censored filings | 375,416 (39.60%) |
| First permit on an earlier calendar day than filing | 15 |
| DOB NOW filing date range | 2016-08-04T20:00:00.000 to 2026-08-24T00:00:00.000 |
| DOB NOW first-permit date range | 2016-09-20T00:00:00.000 to 2026-08-24T17:17:07.000 |
| DOB NOW approved-permit rows | 989,378 |
| DOB NOW distinct permitted filings | 573,526 |
| DOB NOW issuance date range | 2016-06-23T08:15:04.000 to 2026-08-24T00:00:00.000 |
| Recent permit sample join to NOW filings | 99.20% (992/1,000 rows) |
| Sample jobs with multiple work types | 69/869 |
| Duplicate sample permit composite keys | 113 |
| Legacy BIS filing rows | 2,716,042 |
| Legacy BIS permit rows | 3,990,092 |

The join statistic is a diagnostic based on the 1,000 most recently issued DOB
NOW permit rows, not a population estimate. Stage 1 must repeat it on a larger,
time-bounded sample before relying on the permits table.

Stage 1 refined the original timestamp comparison. The API reports 340 records
where the permit timestamp is earlier than the filing timestamp, but 325 occur
on the same calendar day and are valid zero-day outcomes for this day-level
project. Only 15 cross into an earlier calendar date and are quarantined.

## Duplicate filing-number examples

| Job filing number | Rows |
| --- | --- |
| Q00657653-A9 | 6 |
| Q00564746-A3 | 4 |
| B00830930-A6 | 4 |
| B00600073-A6 | 4 |
| B00561184-A4 | 4 |
| Q00732043-A4 | 4 |
| B00587567-A3 | 4 |
| Q00479380-A4 | 4 |
| M00611352-A9 | 4 |
| Q00523537-A7 | 4 |
| X01072612-A5 | 4 |
| M01075131-P9 | 4 |
| M00637209-A3 | 4 |
| B00698051-P9 | 4 |
| M00628781-P6 | 4 |
| Q08051255-P8 | 4 |
| Q00633533-A9 | 4 |
| B00561184-A3 | 4 |
| Q01078424-P7 | 4 |
| B00735907-A9 | 2 |

Inspection found both exact-looking repeated rows and reused filing numbers with
different filing dates. Therefore `job_filing_number` is a candidate business
identifier, not a valid primary key as published. Stage 1 must preserve raw
rows, separate exact duplicates from conflicting duplicates, document a
deterministic resolution policy, and test whether the anomalies affect labeled
records.

## Current filing-status distribution

| Filing status | Rows |
| --- | --- |
| LOC Issued | 370744 |
| Approved | 318259 |
| Permit Entire | 189514 |
| Objections | 21479 |
| Filing Withdrawn | 13361 |
| TA Certificate of Operation Issued | 9416 |
| Plan Examiner Review | 6515 |
| CO Issued | 5980 |
| PA Certificate of Operation Issued | 2901 |
| Full Demolition Signed-off | 1586 |
| Permit Issued | 1522 |
| On Hold – Administrative Action | 1357 |
| Incomplete | 1019 |
| QA Failed | 693 |
| Pending Plan Examiner Assignment | 513 |
| OnHold-NoGoodCheck | 503 |
| Prof Cert QA Review | 433 |
| PAA Approved | 382 |
| Chief Plan Examiner/ Assistant Chief Plan Examiner Review | 347 |
| On Hold - Pending Supersede of Applicant of Record | 271 |
| LL 158-2017-Denied | 254 |
| On Hold  - Applicant Supersede Request Required | 218 |
| On Hold - Special Inspector Withdrew | 112 |
| Pending CPE/ACPE Assignment | 106 |
| Pending Prof Cert QA Assignment | 77 |
| SO Plan Examiner Review | 70 |
| On Hold - Progress Inspector Withdrew | 55 |
| On Hold - Pending Supersede of Special Inspector | 45 |
| Awaiting Energy Approval | 25 |
| On Hold - Pending Supersede of Progress Inspector | 24 |
| On Hold - Applicant of Record Withdrawn | 22 |
| On Hold - Pending Withdrawal of Site Safety Coordinator | 16 |
| Pending Loft Board Submission | 14 |
| Zoning Plan Examiner Review | 14 |
| Loft Board QA Failed | 13 |
| On Hold - Pending Withdrawal of Special Inspector | 12 |
| Permit Entire - BC/DBC Review Objections | 12 |
| Pending SO PE Assignment | 10 |
| Pending QA Review | 8 |
| Intent to Revoke | 8 |
| Loft Board Review | 7 |
| Revoked | 6 |
| Work Without Permit CPE/ACPE Review (LL 158/17) | 4 |
| Pending Zoning Plan Examiner Assignment | 4 |
| On Hold - Pending Withdrawal of Progress Inspector | 3 |
| Inspection Complete | 3 |
| On Hold | 3 |
| Permit Entire - BC/DBC Review | 2 |
| On Hold – Pending Withdrawal of TR | 2 |
| On Hold – Pending Supersede of Owner | 2 |
| Intent to Revoke - Audit Review in Progress | 2 |
| Pending QA Assignment | 2 |
| Pending L2 Review | 1 |
| On Hold - Admin Review | 1 |
| Intent to Revoke - Challenge Accepted | 1 |
| QA Review for LOC | 1 |

## Statuses among records with no first permit date

| Filing status | Rows |
| --- | --- |
| Approved | 317643 |
| Objections | 21477 |
| Filing Withdrawn | 11925 |
| TA Certificate of Operation Issued | 9416 |
| Plan Examiner Review | 6515 |
| PA Certificate of Operation Issued | 2901 |
| Incomplete | 1019 |
| QA Failed | 693 |
| Full Demolition Signed-off | 624 |
| Pending Plan Examiner Assignment | 513 |
| Prof Cert QA Review | 433 |
| PAA Approved | 382 |
| Chief Plan Examiner/ Assistant Chief Plan Examiner Review | 347 |
| On Hold – Administrative Action | 342 |
| OnHold-NoGoodCheck | 306 |
| LL 158-2017-Denied | 254 |
| On Hold - Pending Supersede of Applicant of Record | 117 |
| Pending CPE/ACPE Assignment | 106 |
| Pending Prof Cert QA Assignment | 77 |
| On Hold  - Applicant Supersede Request Required | 71 |
| SO Plan Examiner Review | 70 |
| Permit Entire | 39 |
| Awaiting Energy Approval | 25 |
| LOC Issued | 22 |
| Zoning Plan Examiner Review | 14 |
| Pending Loft Board Submission | 14 |
| Loft Board QA Failed | 13 |
| Pending SO PE Assignment | 10 |
| On Hold - Applicant of Record Withdrawn | 8 |
| Pending QA Review | 8 |
| Loft Board Review | 7 |
| Revoked | 5 |
| Work Without Permit CPE/ACPE Review (LL 158/17) | 4 |
| Pending Zoning Plan Examiner Assignment | 4 |
| On Hold | 3 |
| On Hold – Pending Withdrawal of TR | 2 |
| On Hold – Pending Supersede of Owner | 2 |
| Pending QA Assignment | 2 |
| Intent to Revoke | 1 |
| On Hold - Admin Review | 1 |
| Pending L2 Review | 1 |

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
forecast: `approved_date, current_status_date, filing_status, first_permit_date, signoff_date`. They are outcomes or are
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
