# Five-minute interviewer demo

## 0:00 - Frame the problem

“PermitPulse helps a project team decide which permit-dependent milestones deserve
attention first. It is planning support, not a compliance or issuance system.”

## 0:30 - Single-permit agent intake

Open **Assess one permit**. Either enter fields or upload a safe sample permit brief.
For an upload, show Gemini's source/confidence table and correct one field before
confirming. Explain that the model cannot run until a person confirms the extracted
values.

## 1:20 - Agent tool use

Run the assessment and show the agent trace. Gemini must call the frozen ML risk and
comparable-permit tools; deterministic code rejects unsupported numerical claims. Ask:
“Why is this high risk, and what should I review first?”

## 2:10 - Portfolio queue

Optionally open **Portfolio**, click **Load six demo projects**, and point out:

- risk level and calibrated probability;
- permit-needed-by date;
- mitigation owner and unassigned work;
- ordering by risk, date, then probability.

## 2:45 - Evidence, not just a score

Open one assessment. Explain that “Why the model moved” is local sensitivity, not
causation. Show comparable completed filings and the completed-case coverage warning.
Call out any post-training or unseen-input warnings.

## 3:30 - Human boundary

Reject the first assessment. Confirm that the rejection is saved and no PDF exists.
Create or open another assessment, add a reviewer note, and approve it.

## 4:10 - Portable outputs

Download the PDF and show that it freezes the project context, risk, evidence,
checklist, limitations, and reviewer note. Download the integration-ready JSON and point to
`integration_status: draft_only_no_external_write`.

## 4:35 - Engineering evidence

Open `reports/portfolio_evaluation.md`. State the future-period result honestly:
99.4 delayed filings per 100 prioritized reviews versus 97.6 for the baseline. Explain
that calibration and subgroup recall matter more than chasing headline accuracy.

## 4:50 - MCP

Show the three read-only MCP tools. A strong prompt is: “Rank these six filings for a
permit-readiness meeting and explain the top two.” Emphasize that the server cannot send
email, edit Procore, submit permits, or bypass human review.

## Closing

“The next production step is not a more complicated agent. It is authentication, shared
state, a validated Procore sandbox mapping, and measuring whether teams reduce schedule
impact after acting on the queue.”
