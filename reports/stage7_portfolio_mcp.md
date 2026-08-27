# Stage 7-9: portfolio, MCP, and public-demo release

## Added product behavior

- Portfolio queue with project name, permit-needed-by date, owner, workflow status,
  risk distribution, filtering, demo scenarios, and CSV batch import.
- Human-approved Procore-shaped risk draft. It is downloadable JSON and deliberately
  performs no external write.
- Three read-only MCP tools over the same tested risk/evidence service plus model-card
  and portfolio-evaluation resources.
- Future-period operational evaluation for limited review capacity, calibration,
  subgroup precision/recall, and false-negative concentration.
- Render Blueprint, verified runtime bootstrap, anonymous public-demo workspaces,
  maximum 25-item batches, and process-local demo rate limiting.
- Recruiter-first README, one-page product brief, five-minute demo script, refreshed
  approved PDF, and portfolio evaluation figure.

## Verified result

- 33 automated unit/integration/contract tests pass.
- Full API and Streamlit processes start together.
- Six real-model demo assessments populate the portfolio.
- Human approval creates a valid PDF and Procore draft; rejection creates no PDF.
- MCP stdio tools are callable and the streamable-HTTP server listens on `/mcp`.
- The PDF was rendered page-by-page and visually checked.
- `render.yaml` parses into API, UI, and MCP services.

## Operational evaluation

On 248,665 untouched future-period filings, reviewing the top-risk 20% found 99.4
actual delays per 100 reviews. The grouped historical-rate baseline found 97.6 and
random selection would find 70.5. PermitPulse caught 28.2% of all delayed filings inside
the 20% review budget. Expected calibration error across risk deciles was 0.053.

This is only a modest improvement over a strong baseline. At the frozen alert threshold,
Professional Certification recall was 46.2%, compared with 97.5% for Standard Plan
Examination, and 33,795 actual delays were missed. The project therefore remains a
human-reviewed prioritization prototype rather than an autonomous decision system.

## Deployment boundary

The repository is deployment-ready but not deployed by code in this checkpoint because
deployment requires the owner's Render/GitHub authorization and a GitHub Release URL for
the runtime artifact bundle. Free Render service files are ephemeral, so hosted demo
history disappears after a restart or redeploy. A production version needs authentication,
shared Postgres/LangGraph state, object storage, edge rate limiting, and a validated
Procore sandbox mapping.
