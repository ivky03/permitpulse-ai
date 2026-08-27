# PermitPulse AI — Stage 2 Model Evaluation

Target: **risk that the first permit is not issued within 30 days**

Winner: **Gradient Boosting**

Selection rule: highest validation average precision

## Time-based split

| Split | Rows | Start | End | Delay rate |
| --- | ---: | --- | --- | ---: |
| Train | 527,508 | 2016-08-04 | 2023-12-31 | 62.82% |
| Validation | 155,966 | 2024-01-01 | 2024-12-31 | 66.37% |
| Test | 248,665 | 2025-01-01 | 2026-07-27 | 70.46% |

The model learns from the past and is tested on later filings. A random split
was intentionally rejected because construction policy and processing behavior
change over time.

## Test results

| Model | Avg precision | ROC AUC | Delay precision | Delay recall | Delay F1 | Brier | Threshold |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| Historical Rate Baseline | 0.896 | 0.788 | 0.779 | 0.848 | 0.812 | 0.158 | 0.43 |
| Logistic Regression | 0.939 | 0.859 | 0.880 | 0.809 | 0.843 | 0.142 | 0.50 |
| Gradient Boosting | 0.944 | 0.869 | 0.888 | 0.807 | 0.845 | 0.136 | 0.53 |

The threshold is chosen on validation data to maximize precision while catching
at least 80% of delayed filings. It is then
frozen before the test set is scored.

## Interpretation

- `Average precision` measures ranking quality for delayed filings; higher is better.
- `ROC AUC` measures separation between delayed and on-time filings; higher is better.
- `Delay precision` is the share of risk alerts that were actually delayed.
- `Delay recall` is the share of delayed filings that the system caught.
- `Brier score` measures probability error; lower is better.
- The historical-rate baseline groups past cases by borough, job type, and
  review type. ML must add value beyond that transparent rule.

The artifact under `artifacts/` is generated locally and excluded from Git.
`reports/model_metrics.json` records the complete machine-readable result.
