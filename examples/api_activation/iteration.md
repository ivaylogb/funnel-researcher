# Iteration comparison

## Summary

- Hypotheses in report: 3
- Applied cleanly: 3
- Skipped (applyable: false): 0
- Errored during apply: 0
- Source report: `examples/api_activation/diagnosis.md`

## Hypothesis 1 — Layer 3

**Title:** Quickstart presents `agent_id` as a placeholder rather than a prerequisite, so developers copy-paste-and-run the placeholder and hit `MISSING_AGENT_ID` (Layer 3)

**Status:** applied (1 edit(s))

## Files modified

| File | Edits | Lines affected | Changed |
|---|---|---|---|
| `docs/quickstart.md` | 1 | 21-32 | yes |

## Per-edit detail

### Edit 1: `docs/quickstart.md` (replace, lines 21-32)

**Before:**

```
## Run your first agent

```python
run = client.agents.run(
    agent_id="agt_xxxxxxxx",
    input="What's the weather like in San Francisco?",
)

print(run.output)
```

That's it.
```

**After:**

```
## Create an agent (required before running)

Pluma agents are pre-configured: each agent has a name, a model, a toolset, and a system prompt. You must create one before calling `agents.run()`. This takes about 2 minutes.

The fastest path: go to https://dashboard.pluma.dev/agents, click "Create agent," and copy the `agent_id` (it looks like `agt_8x3kqp2n`) from the top of the detail page. For programmatic creation, see [Configure your agent](agents.md).

If you call `agents.run()` without a valid `agent_id`, you will receive a `MISSING_AGENT_ID` or `INVALID_AGENT_SCOPE` error.

## Run your first agent

Replace `agt_REPLACE_WITH_YOUR_ID` below with the `agent_id` you just created:

```python
run = client.agents.run(
    agent_id="agt_REPLACE_WITH_YOUR_ID",
    input="What's the weather like in San Francisco?",
)

print(run.output)
```

That's it.
```

## Hypothesis 2 — Layer 3

**Title:** The README's top-level quickstart has the same placeholder problem and is the developer's first impression — many developers never reach `docs/quickstart.md` with a corrected mental model (Layer 3)

**Status:** applied (1 edit(s))

## Files modified

| File | Edits | Lines affected | Changed |
|---|---|---|---|
| `README.md` | 1 | 5-21 | yes |

## Per-edit detail

### Edit 1: `README.md` (replace, lines 5-21)

**Before:**

```
## Quickstart

```python
from pluma import PlumaClient

client = PlumaClient(api_key="sk_pluma_...")

run = client.agents.run(
    agent_id="agt_xxxxxxxx",
    input="Summarize the Q3 earnings call transcript attached.",
    attachments=["earnings_q3.pdf"],
)

print(run.output)
```

See the [agent configuration guide](docs/agents.md) for how to create an `agent_id` before running.
```

**After:**

```
## Quickstart

Pluma agents are pre-configured. Before you can call `agents.run()`, you need an `agent_id` — create one at https://dashboard.pluma.dev/agents (about 2 minutes) or via [`client.agents.create()`](docs/agents.md). Then:

```python
from pluma import PlumaClient

client = PlumaClient(api_key="sk_pluma_...")

# Replace agt_REPLACE_WITH_YOUR_ID with the agent_id you created above.
run = client.agents.run(
    agent_id="agt_REPLACE_WITH_YOUR_ID",
    input="Summarize the Q3 earnings call transcript attached.",
    attachments=["earnings_q3.pdf"],
)

print(run.output)
```

See the [agent configuration guide](docs/agents.md) for full details on creating and managing agents.
```

## Hypothesis 3 — Layer 2

**Title:** When a run starts but stalls, neither the SDK nor the error catalog tells the developer how to diagnose it, so 24% of dropoffs occur one-shot with no retry (Layer 2)

**Status:** applied (2 edit(s))

## Files modified

| File | Edits | Lines affected | Changed |
|---|---|---|---|
| `docs/quickstart.md` | 1 | 39-41 | yes |
| `docs/errors.md` | 1 | (insert after 44) | yes |

## Per-edit detail

### Edit 1: `docs/quickstart.md` (replace, lines 39-41)

**Before:**

```
## Troubleshooting

If your run isn't returning output, check the [error reference](errors.md).
```

**After:**

```
## Troubleshooting

If your run isn't returning output, check the [error reference](errors.md).

**My run started but isn't completing.** Agent runs can take from a few seconds to several minutes depending on model and toolset. The synchronous `client.agents.run(...)` call blocks until the run completes or the server times out (returning `MODEL_TIMEOUT`). For runs you expect to take more than ~30 seconds, pass `stream=True` to receive intermediate events as they arrive:

```python
for event in client.agents.run(agent_id="agt_...", input="...", stream=True):
    print(event)
```

This lets you see `tool_call`, `tool_result`, and progress events live, so you can tell whether the agent is making progress or stuck on a tool call.
```

### Edit 2: `docs/errors.md` (insert_after, lines (insert after 44))

**Inserted:**

```

### (Not an error) Run started but never completes
If you see a `run.start` event in your logs but no `run.complete` within a few minutes, the run is in progress, not failed. Use `stream=True` on `client.agents.run()` to receive `tool_call` and `tool_result` events as they happen. If the run eventually fails server-side, you'll get `MODEL_TIMEOUT` (above) or `TOOL_TIMEOUT` (below).
```

## What this report is NOT

- This is a side-by-side view of every applyable hypothesis's mechanical changes — not a recommendation. The iterator does not pick a winner.
- No re-measurement is run. v1 of iterate has no eval coupling; each hypothesis's predicted lift is the hypothesis author's claim, not a measured outcome.
- The product directory is identical before and after iterate. Each hypothesis is applied against the same baseline and reverted before the next is processed.
- The operator picks which hypothesis to ship. Use the diagnose report's evidence and this comparison's mechanical diffs together.
