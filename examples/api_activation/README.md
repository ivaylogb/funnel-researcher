# Worked example: Pluma API activation funnel

This example diagnoses developer dropoff at the `first_successful_agent_run` step of a fictional agentic-API product (Pluma). The product is in `fixtures/pluma_api/` and is deliberately imperfect in specific ways that produce the dropoff signals in the data.

## How to run it

```bash
python -m funnel_researcher diagnose \
    --funnel examples/api_activation/funnel.yaml \
    --dropoff examples/api_activation/dropoff_data.json \
    --product fixtures/pluma_api \
    --output-file outputs/pluma_diagnosis.md \
    --model claude-opus-4-7
```

Cost: roughly $0.50 per run against Opus 4.7.

## The produced report

`diagnosis.md` in this directory is the actual run output. The model produced 3 hypotheses spanning Layers 2 and 3, all with `applyable: true` structured edits. Citation spot-check across 9 file:line citations: all 9 matched the actual fixture source.

- **H1 (Layer 3):** the `agent_id` requirement is structurally buried — quickstart shows the placeholder without explaining prerequisite agent creation, which lives in a separate doc (`agents.md`) that the quickstart never links to.
- **H2 (Layer 3):** the README's quickstart code block reads as linear execution; the agent-creation branch is demoted to a reference line below the code.
- **H3 (Layer 2):** the SDK `run()` signature shows `agent_id` as the first parameter with no precondition hint at the signature level, and the Troubleshooting section in `quickstart.md` points developers at an error catalog that doesn't cover the stalled-run case (24% of dropoffs).

## What this report does NOT prove

- Single-run results are subject to model variance. A second run might surface different but equally valid hypotheses, or different layer assignments. The methodology produces directional findings grounded in real artifact evidence, not a statistically-verified ranking.
- These hypotheses are not verified fixes. Each requires applying the structured edit, re-measuring the funnel, and comparing the dropoff signals. That loop is the `apply` and `iterate` subcommands, planned for v2 once Phase 1 hypothesis quality has been validated in practice.
