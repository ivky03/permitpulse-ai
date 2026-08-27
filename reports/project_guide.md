# PermitPulse AI: plain-English project guide

## 1. What problem are we solving?

A construction project can lose time and money when its first permit takes longer
than planned. PermitPulse gives a project manager an early warning at filing time:

> “Based on similar NYC filings, how likely is this filing to miss a 30-day first-
> permit target, what evidence supports that warning, and what should a human review?”

It does **not** decide whether a filing complies with code or predict the examiner's
exact decision. That would require information this dataset does not contain.

## 2. Where does the data come from?

We do not invent the dataset. `src/data/build_dataset.py` downloads official DOB NOW
filing records from NYC Open Data dataset `w9ak-ipjd`. It saves the original response,
records a hash and query manifest, cleans ambiguous rows, and creates labels.

For a filing made on January 1:

- first permit on or before January 31 → on time;
- no first permit by January 31 → delayed;
- observed before January 31 with no permit → not yet knowable, so excluded as censored.

Fields that reveal the outcome—such as permit date or filing status—are blocked from
model inputs. Otherwise the model would be “predicting” with the answer already known.

## 3. What did the model learn?

The positive class is **delay**: no first permit within 30 days. The selected gradient-
boosting model was trained on 2016–2023, tuned on 2024, and tested once on later data.

On the 248,665-row future-period test set:

| Metric | Result | Plain meaning |
|---|---:|---|
| ROC AUC | 0.869 | A random delayed case is usually ranked riskier than a random on-time case. |
| Average precision | 0.944 | Risk rankings stay strong even though delayed cases are common. |
| Delay recall | 80.7% | It alerts on about 81 of every 100 actual delays. |
| Delay precision | 88.8% | About 89 of every 100 alerts are actual delays. |
| False negatives | 33,795 | Delays the model incorrectly marked below the alert threshold. |

The model is useful, not perfect. Trying more models and threshold policies is a valid
later enhancement after the end-to-end product works.

## 4. What happens during one assessment?

1. The API receives only facts available when the filing is made.
2. The model returns a 30-day delay probability and risk level.
3. Local sensitivity shows which entered fields moved this individual prediction most.
4. DuckDB retrieves similar completed filings and summarizes their actual timing.
5. Code creates a bounded project-manager checklist; Gemini may optionally rewrite its
   summary without changing facts.
6. LangGraph pauses. A human approves or rejects the checklist.

“Approved” does not mean DOB approval. It means a person approved the proposed internal
follow-up. The app has no tool that submits a filing, emails anyone, or edits a schedule.

## 5. Why this is relevant to Procore

Procore is construction-management software. This project demonstrates a workflow that
could sit beside project schedules and permit logs: combine public operational data,
machine-learning risk, evidence retrieval, APIs, an understandable UI, and a controlled
human decision. The transferable idea is proactive project-risk management—not NYC-only
permit trivia.

The strongest interview story is the engineering judgment:

- use time-based evaluation because future projects differ from old ones;
- prevent outcome leakage;
- show evidence and uncertainty instead of only a score;
- keep generative AI away from factual calculations;
- require human approval before operational follow-up.

## 6. How to run and explain it

```bash
source .venv/bin/activate
python -m pip install -r requirements.txt
python -m src.modeling.train
python -m src.retrieval.comparables
python -m unittest discover -v
```

Then run FastAPI and Streamlit in two terminals using the commands in `README.md`.
During a demo, enter a filing profile, explain the risk card, inspect the sensitivity
and comparable cases, and show that the workflow cannot finish until you approve or
reject it.

The next enhancement backlog is intentionally separate: calibrate/retune the threshold,
try stronger tabular models, add subgroup monitoring, use a durable checkpointer and
authentication, then deploy with observability.
