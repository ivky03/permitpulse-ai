# PermitPulse agent evaluation

PermitPulse now separates ML evaluation from agent evaluation. The automated test suite
checks deterministic fallback, required tool calls, rejection of unsupported numeric
claims, document schema normalization, missing-field handling, human confirmation, and
API contracts without spending Gemini tokens.

Run the live Gemini evaluation after setting `GOOGLE_API_KEY`:

```bash
python -m scripts.evaluate_agent
```

The live suite covers risk explanation, historical evidence, mitigation focus, a direct
prompt-injection attempt, and exact extraction of six core fields from a labeled
synthetic PDF. The generated report replaces this file with observed tool calls and
pass/fail results. Do not report a live pass rate until the command has run.
