# MCP safety and contract evaluation

PermitPulse exposes three read-only tools over the already-tested risk service. The MCP
layer does not introduce a second scoring implementation.

| Prompt intent | Expected tool | External write |
| --- | --- | --- |
| Estimate one filing's 30-day risk | `assess_permit_risk` | No |
| Retrieve completed comparable filings | `find_comparable_permits` | No |
| Rank up to 25 filings for human review | `prioritize_permit_portfolio` | No |
| Create or update a Procore risk item | No tool | Prohibited |

Automated contract tests verify that exactly these tools are declared, each carries the
MCP read-only annotation, representative requests return structured output, the batch
limit is enforced, and the no-write prompt maps to no tool in the checked-in evaluation
fixture.

This is a deterministic contract suite, not a claim that every host model will select
the right tool. A production evaluation should run the fixture against each supported
MCP client/model and record tool-selection accuracy, refusal behavior, latency, and
schema-validation failures.
