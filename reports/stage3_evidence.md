# PermitPulse AI — Stage 3 Evidence Layer

Decision: **PASSED**

## What Stage 3 adds

Model v1 now returns an evidence packet rather than a bare probability:

1. 30-day delay probability, risk band, and alert decision.
2. Five local sensitivity factors produced by one-at-a-time reference
   substitution.
3. Twelve similar completed filings retrieved from a local DuckDB index.
4. Median and interquartile processing time plus comparable delay count.
5. Warnings for missing, unseen, extreme, or post-training inputs.
6. Model training period and snapshot observation date.

## Verified full-data demo

The demo used filing `Q01437995-I1` only as an input example and excluded it
from retrieval.

| Result | Value |
| --- | ---: |
| Predicted delay risk | 82.50% |
| Model threshold | 53.00% |
| Risk level | High |
| Comparable scope | Borough + job type + review type |
| Comparable filings | 12 |
| Comparable median | 90.5 days |
| Comparable interquartile range | 79.5–140.0 days |
| Comparables exceeding 30 days | 11 of 12 |
| Indexed completed filings | 572,902 |

The largest local sensitivity was Standard Plan Examination versus the
training reference of Professional Certification. Replacing only that field
with its reference reduced predicted risk by approximately 31.9 percentage
points. This is a model sensitivity statement, not a causal claim about how to
obtain a permit faster.

## Limitations

- The model was trained through 2023, while later processing conditions show
  drift. Every assessment surfaces this date boundary.
- Comparable processing-time statistics require an observed first permit and
  therefore exclude unresolved or never-permitted filings.
- One-at-a-time sensitivity effects interact and do not add up to the final
  probability.
- Similarity is an explicit weighted business rule, not a learned metric.
- This layer supports planning; it does not assess code compliance or guarantee
  issuance.

## Next stage

Stage 4 will place these deterministic tools inside a controlled LangGraph
workflow. The language model may summarize supplied evidence and draft an
action plan, but it may not generate probabilities, invent comparable filings,
or execute an action without human approval.
