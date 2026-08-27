# Stage 4: controlled workflow and product shell

## Outcome

PermitPulse now runs from filing-time inputs through prediction, comparable-case
evidence, a proposed checklist, and an explicit human decision. No Gemini key is
required: deterministic planning is the default fallback. When a key is present,
Gemini may rewrite only the evidence-bound summary; it cannot change the model
score, comparables, recommended action structure, or approval state.

## Workflow contract

1. `RiskService` calculates the model score, sensitivity, comparables, and warnings.
2. `EvidencePlanner` drafts a bounded checklist from that structured result.
3. LangGraph pauses with `interrupt()` and saves the thread state.
4. A reviewer sends `approve` or `reject` using the same thread ID.
5. Approval means only “approved for human follow-up.” No email, DOB submission,
   schedule change, or external side effect is performed.

The demo uses an in-memory LangGraph checkpointer. It is correct for local use and
tests, but a deployed multi-instance service must replace it with a durable shared
checkpointer before claiming crash recovery or long-lived approvals.

## Interfaces

- FastAPI: `POST /api/v1/assessments`
- Review: `POST /api/v1/assessments/{thread_id}/decision`
- Model metadata: `GET /api/v1/metadata`
- Interactive dashboard: `streamlit run ui.py`
- API documentation: `http://localhost:8000/docs`

## Guardrails worth defending

- The LLM writes language, not facts or risk scores.
- The workflow pauses before finalization.
- The response preserves model warnings and the completed-case limitation.
- Prediction requests still reject post-outcome leakage fields.
- The UI defaults unshown fields to documented training reference values; this is
  a portfolio-demo convenience, not a recommended production intake process.
