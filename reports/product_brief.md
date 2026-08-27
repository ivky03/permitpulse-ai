# PermitPulse AI: one-page product brief

## User and problem

Construction project and permit managers can have multiple permit-dependent milestones
but limited time to investigate every filing. Late first permits can threaten schedule
activities, yet a probability alone does not tell the team what to review, why, or who
should own the follow-up.

## Product

PermitPulse ranks a small portfolio of NYC permit filings by 30-day delay risk and
needed-by date. For each filing it shows filing-time risk factors, comparable completed
permits, data-quality warnings, and a bounded readiness checklist. A person must approve
before the system creates a durable PDF and a draft JSON record shaped for a future
Procore integration.

## Operational value

In the untouched future-period test set, reviewing the top-risk 20% found 99.4 delayed
filings per 100 reviews, compared with 97.6 for a strong grouped historical baseline and
70.5 expected under random selection. PermitPulse catches 28.2% of all delayed filings
inside that 20% review budget. Its expected calibration error is 0.053 across risk
deciles.

This is a modest ranking gain over the baseline. The stronger product value is the
combination of prioritization, evidence, ownership, human review, and a portable audit
artifact.

The largest measured subgroup weakness is recall: 46.2% for Professional Certification
versus 97.5% for Standard Plan Examination. Any production pilot should stratify or
recalibrate this segment before using the queue to allocate scarce review capacity.

## Procore relevance

- Portfolio view: mirrors the cross-project decisions construction teams make.
- Risk draft: maps an approved assessment to schedule risk, owner, response strategy,
  evidence, and follow-up actions without claiming a live integration.
- MCP service: lets approved AI clients retrieve the same read-only intelligence through
  explicit tool contracts.
- Auditability: freezes inputs, model context, comparables, warnings, actions, and reviewer
  notes in a PDF.

## Non-goals

PermitPulse does not predict code objections, determine compliance, contact NYC DOB,
guarantee issuance, change a schedule, or write to Procore. Completed comparables do not
represent unresolved filings. Model performance can drift as agency conditions change.

## Production path

Replace demo workspace IDs with SSO and authorization; move SQLite/LangGraph state to a
shared Postgres checkpointer; store reports in object storage; add project-system IDs;
validate a Procore field mapping with sandbox access; monitor calibration, subgroup
recall, latency, and reviewer decisions; then evaluate whether interventions shorten
schedule impact rather than merely predicting delay.
