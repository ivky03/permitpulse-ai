# Agent Quality Audit: real Gemini responses + human review + independent LLM judge

This is one **optional feature of PermitPulse AI**, not a separate AI product. It does not alter the ML model, FastAPI assessment contracts, existing agent prompt, or human approval workflow.

## What it measures

The existing `src.agent.planner.EvidencePlanner` produces real Gemini answers using the saved PermitPulse ML risk assessment and historical evidence tools. A reviewer labels each observed answer PASS/FAIL with a rationale. A *separate* Gemini invocation grades the same answer using a fixed quality rubric, **without being shown the reviewer's verdict, rationale, or prior judge output**.

The page displays reviewed count, judged count, judge–reviewer agreement, false accepts (judge PASS for reviewer FAIL), false rejects, and individual disagreements. This is judge calibration against **author-reviewed** labels, not independently expert-certified truth.

## Where the goldset comes from

No external goldset is required. Use the existing PermitPulse UI to create a demo permit assessment, then the new **Agent Quality Audit** Streamlit page to collect actual Gemini responses. Review and label only after checking the risk figures, comparable evidence, and tool calls. Download the JSON to retain a versioned author-reviewed dataset. The default starter prompts are *questions*, not fabricated goldset answers. The app never pre-labels agent responses.

If the real agent gives all PASS-quality answers, that is a valid result—**do not manufacture failing real-agent outputs**. A small all-PASS collection cannot estimate false-accept rate. To test that later, create a clearly separate adversarial/synthetic negative-control suite or evaluate real failures you discover.

## Setup

1. Run PermitPulse's FastAPI backend as documented in the root README:

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements-audit.txt
uvicorn src.api.app:app --reload --port 8000
```

2. In a second terminal, start the existing Streamlit app:

```bash
streamlit run ui.py
```

3. Create or open a *demo* PermitPulse assessment. From Streamlit's **Agent Quality Audit** page, choose **Use the assessment currently open**, or find a saved assessment using its workspace ID. The page does not need the FastAPI server to hold an API key.

4. Enter your **Gemini API key at runtime**, choose a judge/agent model, and generate a response to a question. The code passes the key directly to a per-session Gemini client, rather than setting a process-global environment variable. API calls incur provider usage and cost.

5. Inspect the actual response, evidence snapshot, and observed tool calls. Mark PASS/FAIL and supply an evidence-based reason. Repeat for a handful of questions.

6. Run the independent **LLM Judge**. Read the disagreements. Download the JSON report so the manually reviewed answers become your audit dataset; imported judge verdicts are discarded and must be rerun.

7. Optional: enable Langfuse in the page and supply its *public* and *secret* keys and host at runtime. The app creates model-generation observations for agent and judge calls and flushes them after use. Only use **synthetic/demo permit data**—the traced inputs contain question/evidence/answer text.

## Tests (offline, no external keys)

```bash
python -m unittest tests.test_agent_quality_audit -v
python -m unittest discover -v
```

## Security and honesty

- **Never paste a key into Git or a README.** Streamlit password inputs keep keys in server-side session state; they are not included in JSON exports or Langfuse trace payloads. Use only a trusted access-controlled HTTPS deployment; do not expose this BYOK interface on a publicly shared untrusted app. Streamlit itself may keep session input state during the active session.
- Do not use real applicant data or private construction filings: the existing demo workspace is not authentication/tenant isolation, and the third-party model and Langfuse services process supplied text.
- Only bounded model prediction, comparable-summary and sensitivity fields are sent to the new evaluator; individual comparable addresses, workspace names and project IDs are excluded.
- Reference labels are human **author reviews**, not externally verified gold truth; don't claim an independent expert calibrated the judge.
- The app does not invent benchmark scores, fix the original agent prompt, auto-deploy new prompts, or block deployment. It measures quality and surfaces failure cases for subsequent changes.
- Very small or all-positive datasets are insufficient for general reliability conclusions. The interface shows denominators and leaves false-accept rates undefined when no reviewed FAIL examples exist.
- Model calls require your own Gemini key. No real evaluation result is claimed until you run it.

## One-sentence resume explanation (after a live run)

> Extended PermitPulse's evidence-grounded Gemini agent with a human-review evaluation workflow, independent LLM-as-a-Judge scoring, Langfuse traces, and disagreement analysis to quantify agent-answer reliability on manually reviewed construction-permit questions.

Add counts and metrics only after completing real, labeled evaluations.
