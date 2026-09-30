# Product documentation

The thinking behind InvoiceAgent, in the order worth reading it.

| Document | What it covers |
|---|---|
| [prd.md](prd.md) | The problem, the users, scope, user stories and success metrics — and what changed once it was built |
| [decision-log.md](decision-log.md) | Every product trade-off and why it went that way, including the six decisions the build forced |
| [trust-design.md](trust-design.md) | How the interface earns an analyst's trust: showing the working, confidence bands, cheap overrides |
| [evaluation-framework.md](evaluation-framework.md) | How the agent is measured, what has been measured, and what the numbers do not mean |
| [failure-taxonomy.md](failure-taxonomy.md) | How it can fail, what stops each failure, and whether that has been tested |
| [model-card.md](model-card.md) | The honest summary: intended use, performance, limitations, and what would have to be true before deploying it |

Results referenced throughout: [eval/results/SUMMARY.md](../eval/results/SUMMARY.md).
Test-data design and its deviations from the spec: [data/generator/README.md](../data/generator/README.md).

Three things to know before reading any performance number:

1. The evaluation data is synthetic and was generated from the same rules the agent applies, so
   rule-based steps score near 100% by construction.
2. The live model evaluation has not been run, so extraction accuracy, latency and cost are
   projections.
3. No real invoice has been through this system.
