# Worked example: Pluma API activation funnel

This example diagnoses developer dropoff at the `first_successful_agent_run` step of a sample API surface (Pluma). The product is in `fixtures/pluma_api/` and is deliberately imperfect in specific ways that produce the dropoff signals in the data.

## Running diagnose

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

## Running iterate

```bash
python -m funnel_researcher iterate \
    --hypothesis-report examples/api_activation/diagnosis.md \
    --product fixtures/pluma_api \
    --output-file outputs/pluma_iteration.md
```

Cost: $0 — iterate is mechanical, no API calls. It applies each hypothesis's structured edits against the fixture, captures the diff, and reverts before processing the next hypothesis. The fixture ends in the same state it started; nothing on disk persists across hypotheses.

`apply` is the single-hypothesis equivalent (`--hypothesis-id H1`, writes are real and not reverted).

## The produced iteration

`iteration.md` in this directory is the actual iterate run output. All 3 hypotheses applied cleanly against the fixture; 0 skipped, 0 errored.

- **H1** rewrites lines 21-32 of `docs/quickstart.md`: inserts a "Create an agent (required before running)" section above the run example and renames the placeholder to `agt_REPLACE_WITH_YOUR_ID`.
- **H2** rewrites lines 5-21 of `README.md`: same prerequisite framing applied to the top-level quickstart.
- **H3** rewrites lines 39-41 of `docs/quickstart.md` (adds a "My run started but isn't completing" troubleshooting block) and inserts a "(Not an error) Run started but never completes" entry after line 44 of `docs/errors.md`.

H1 and H3 both touch `docs/quickstart.md` — the iterator snapshots and reverts between hypotheses, so each is applied against the same clean baseline. There is no cumulative state.

## What this report does NOT prove

- Single-run diagnose results are subject to model variance. A second run might surface different but equally valid hypotheses, or different layer assignments. The methodology produces directional findings grounded in real artifact evidence, not a statistically-verified ranking.
- These hypotheses are not verified fixes. Each requires applying the structured edit, re-measuring the funnel, and comparing the dropoff signals. `apply` and `iterate` ship the *mechanical* half of that loop — the re-measurement half requires an instrumented funnel and is out of scope for v1.
- The iteration comparison does not pick a winner. The operator decides which (if any) hypothesis to ship based on the diagnose report's evidence plus the comparison's mechanical diffs.
