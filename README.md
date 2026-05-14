# funnel-researcher

A failure-diagnosis tool for developer-API activation funnels. When developers drop off at a specific step in an API or agent-platform onboarding, this reads the funnel definition, the dropoff data, and the product's artifacts (docs, SDK source, error catalog), and produces structured hypotheses about why — with `file:line` evidence and applyable edit specs.

Built for growth/PLG PMs running developer-facing API products. Particularly useful for agentic APIs, agent platforms, and developer tools where traditional funnel analytics doesn't translate cleanly because "the user" is a developer integrating, "the events" are API calls and SDK errors, and the behavior of interest is what the developer's code does over time.

## What it does

`diagnose` is the first subcommand. It takes:

- A **funnel definition** (YAML) describing the steps a developer moves through, plus a target step you're investigating
- **Dropoff data** (JSON) with per-step counts, pass rates, and failure signals
- The **product's artifacts** — docs, SDK source, error catalog — read from disk

…and produces a markdown report with 2-3 structurally distinct hypotheses, each categorized against a four-layer model, each grounded in specific file:line evidence AND specific dropoff signals, each with an applyable structured edit spec.

## The four layers

Hypotheses are categorized against where the cause of dropoff lives:

1. **Funnel definition** — the funnel itself is measuring the wrong thing, or the success criterion is unobservable
2. **API/SDK surface** — tool schemas, error codes, parameter requirements, SDK signatures
3. **Docs/Context** — what reaches the developer at decision time, where critical information sits, what's buried
4. **Workflow/Sequence** — the order of steps, implicit preconditions, branches assumed-linear

Each hypothesis picks exactly one layer and cites evidence specific to that layer. Two hypotheses that would be fixed by the same edit get collapsed.

## Install

```bash
pip install -e .
export ANTHROPIC_API_KEY=sk-ant-...
```

## Usage

```bash
python -m funnel_researcher diagnose \
    --funnel examples/api_activation/funnel.yaml \
    --dropoff examples/api_activation/dropoff_data.json \
    --product fixtures/pluma_api \
    --output-file outputs/pluma_diagnosis.md
```

The product's artifacts are loaded with each line prefixed by its 1-indexed line number, which lets the hypothesis report cite `file:line` evidence a reader can actually verify against the live source.

## Report shape

Each report has:

- Dropoff summary (relevant pass rates, top failure signals)
- Layer categorization (primary + secondary candidates, with reasoning)
- 2-3 hypotheses, each with:
  * Claim (one or two sentences about the mechanism)
  * Layer assignment
  * Evidence (`file:line` citations + specific dropoff signals)
  * Proposed change (prose + structured JSON edit spec)
  * How to verify (which pass rate should move, by how much, what signals should disappear)

## Worked example

[`examples/api_activation/`](examples/api_activation/) is the canonical worked example. It runs against a fictional agentic-API product (`fixtures/pluma_api/`) where the target dropoff step is `first_successful_agent_run`. The product is deliberately imperfect — `agent_id` setup buried in a separate doc, error messages that name the problem but not the path to the fix, an SDK `run()` signature that hides a precondition, a README quickstart that reads as linear when agent creation is a branch, and a scoped-keys concept introduced only in the error catalog.

`examples/api_activation/diagnosis.md` is the actual diagnose run output: three hypotheses spanning Layers 2 and 3, all with `applyable: true` structured edits, every file:line citation verified against the fixture source. See [the example's README](examples/api_activation/README.md) for the full breakdown and how to reproduce it.

## Forbidden hypothesis patterns

The system prompt rejects hypotheses that look like:

- "The docs need to be improved"
- "Add more examples"
- "The developer experience is poor"
- "Run an A/B test"
- "Add a tutorial video"
- "Improve error messages" (without naming which one, where, and what behavior the current message produces)

These pattern-match to generic growth advice and don't isolate the specific defect. If a hypothesis starts to look like one of these, the agent is told to dig deeper or drop it.

## Self-checks before emission

Before returning a report, the model walks eight self-checks: evidence-supports-claim (does the cited evidence actually back the claim?), structural distinctness (would two hypotheses be fixed by the same edit?), layer assignment, applyability of proposed changes, no forbidden patterns, no claiming information is missing when it exists in the docs/SDK, line-number verification (does the cited number match the prefix on the quoted content?), and structured-edit verification (does each `expected_content` string match the file verbatim?).

## Tests

```bash
python -m pytest tests/
```

Tests cover loaders (funnel + dropoff parsing), the product reader, the prompt assembler (line numbering, brace survival, field substitution), and the hypothesis agent (via a stub client; no API calls in tests).

## Methodology

This tool applies the same diagnostic methodology as [agent-researcher](https://github.com/ivaylogb/agent-researcher) to a different problem class. The structural pattern — addressable artifact + evidence-grounded hypotheses + four-layer categorization + applyable structured edits — was developed for diagnosing agent failures against evals and turned out to generalize to diagnosing developer-funnel dropoff against the products that produce it.

The four layers map differently between the two domains. In agent-researcher: evaluation, tools, context, workflow of an *agent*. In funnel-researcher: the funnel definition, API/SDK surface, docs/context, onboarding workflow of a *product*. The methodology survives the transfer because both domains share the underlying structure: an addressable artifact (agent code / product artifacts), a measurable failure (eval result / dropoff signal), and operations that produce verifiable hypotheses about the cause.

## License

MIT.
