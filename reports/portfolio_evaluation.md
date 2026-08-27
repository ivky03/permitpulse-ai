# PermitPulse portfolio evaluation

![Operational prioritization and calibration](figures/portfolio_evaluation.png)

Evaluation population: **248,665 future-period filings** from
2025-01-01 through 2026-07-27.

## Limited-capacity review

Assume a project team can inspect only the highest-ranked 20%
of filings. `Delays per 100 reviews` translates model ranking into workload value.

| Strategy | Reviewed | Delays found | Delays per 100 reviews | Share of all delays caught |
| --- | ---: | ---: | ---: | ---: |
| Random expected | 49,733 | 35,042.0 | 70.5 | 20.0% |
| Historical-rate baseline | 49,733 | 48,548 | 97.6 | 27.7% |
| PermitPulse | 49,733 | 49,418 | 99.4 | 28.2% |

This is a retrospective prioritization simulation, not proof that an intervention
caused a permit to arrive sooner.

## Calibration

Expected calibration error across risk deciles: **0.053**.
Calibration should be monitored after deployment because agency processing conditions
can change after the training period.

## Subgroup performance

These slices expose where alert precision or recall differs. They do not establish
fairness or causation; small groups under 2,000 future-period rows are omitted.

### Borough

| Group | Rows | Delay rate | Alert precision | Alert recall |
| --- | ---: | ---: | ---: | ---: |
| Manhattan | 91,126 | 65.2% | 87.0% | 71.0% |
| Brooklyn | 68,645 | 75.1% | 89.2% | 86.7% |
| Queens | 49,482 | 72.7% | 89.7% | 83.9% |
| Bronx | 26,077 | 74.6% | 91.5% | 86.7% |
| Staten Island | 13,335 | 66.6% | 86.5% | 85.2% |

### Job Type

| Group | Rows | Delay rate | Alert precision | Alert recall |
| --- | ---: | ---: | ---: | ---: |
| Alteration | 190,195 | 62.9% | 84.8% | 72.0% |
| New Building | 23,093 | 94.9% | 95.7% | 99.3% |
| Alteration CO | 20,423 | 95.2% | 95.8% | 99.5% |
| ALT-CO - New Building with Existing Elements to Remain | 6,983 | 95.7% | 96.0% | 99.7% |
| Full Demolition | 4,061 | 90.2% | 91.3% | 98.2% |
| No Work | 3,910 | 100.0% | 100.0% | 100.0% |

### Filing Review Type

| Group | Rows | Delay rate | Alert precision | Alert recall |
| --- | ---: | ---: | ---: | ---: |
| Standard Plan Examination | 128,999 | 91.3% | 94.5% | 97.5% |
| Professional Certification | 119,666 | 48.0% | 70.3% | 46.2% |


## False-negative review

At the frozen threshold, PermitPulse missed **33,795**
actual delayed filings. The machine-readable report lists their largest borough,
job-type, and review-type concentrations for targeted error analysis.

## Decision boundary

- The evaluation uses the untouched future-period test set.
- Portfolio ranking does not authorize an external action.
- Completed comparables remain selective evidence.
- Model probabilities are planning estimates, not permit decisions or guarantees.
