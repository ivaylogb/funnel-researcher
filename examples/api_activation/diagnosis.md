# Funnel diagnosis report: pluma_api_activation / first_successful_agent_run

## Dropoff summary

Of 612 developers who made a first API call, only 287 reached a successful agent run — a 46.9% pass rate, the worst conversion in the funnel. The top failure signals at this step:

- **31%** — first call returns 400 `MISSING_AGENT_ID` (median 4 calls before quit; they retry, fail, retry, quit)
- **18%** — first call returns 401 `INVALID_AGENT_SCOPE` (median 2 calls; they quit fast)
- **24%** — `run.start` succeeds but no `run.complete` within 5 minutes (median 1 call; one-shot, no follow-up)
- **14%** — `tool_call` event with missing required parameter, no retry
- **13%** — successful first API call but no agent run attempted within 24h

Qualitative: support tickets mentioning `agent_id` 4x baseline; SDK getting-started issues tripled; survey free text clusters on "unclear what agent_id should be" and "docs jump to advanced examples."

## Layer categorization

**Primary: Layer 3 (Docs/Context delivered at decision time) and Layer 4 (Workflow/Onboarding sequence).** The dominant failures (`MISSING_AGENT_ID` 31% + `INVALID_AGENT_SCOPE` 18% = 49% of dropoffs) are concentrated around developers not having (or not having the correct) `agent_id` at the moment they call `agents.run()`. The product artifacts make agent creation a hard precondition, but the quickstart presents it as a "what's next" step *after* the run example, with a placeholder `agent_id="agt_xxxxxxxx"` that developers literally copy-paste and run.

Secondary: **Layer 2** for the 24% `run.start`-without-`run.complete` cohort — the SDK and error catalog give the developer no actionable next step when a run hangs (no `MODEL_TIMEOUT` was returned to them since `run.start` succeeded; they just see nothing happen).

Layer 1 was considered and rejected: the step success criterion (`run.complete` event) is a legitimate, observable outcome.

## Hypotheses

### Hypothesis 1: Quickstart presents `agent_id` as a placeholder rather than a prerequisite, so developers copy-paste-and-run the placeholder and hit `MISSING_AGENT_ID` (Layer 3)

**Claim:** The quickstart's "Run your first agent" code block uses `agent_id="agt_xxxxxxxx"` as a literal-looking string, with no preceding instruction that the developer must first create an agent. The link to `agents.md` appears in the "What's next" section *below* the run example. Developers copy the example verbatim, send `"agt_xxxxxxxx"` (or a similarly fake value) to the API, and receive `MISSING_AGENT_ID` or `INVALID_AGENT_SCOPE`. This is the mechanism behind the combined 49% of dropoffs from those two error codes and the 4x spike in `agent_id` support tickets.

**Evidence:**
- `docs/quickstart.md:21-30` — "Run your first agent" code block uses `agent_id="agt_xxxxxxxx"` with no prerequisite text above it. The developer reaches this code immediately after the auth step on line 19.
- `docs/quickstart.md:34-36` — Agent configuration is relegated to "What's next" *after* the run example, framed as optional follow-up reading.
- `docs/agents.md:3` — confirms agent creation is a hard prerequisite ("Before you can run an agent, you need to create an agent configuration and retrieve its `agent_id`"), so the quickstart's ordering inverts the actual dependency.
- error catalog:`17-18` — `MISSING_AGENT_ID` returns HTTP 400 telling the developer to "Set it to a valid agent ID issued by the dashboard or `agents.create`" — but the developer has *already* set it (to the placeholder); the message doesn't flag that placeholder-shaped strings are the failure mode.
- Dropoff signal: 31% `MISSING_AGENT_ID` with median 4 calls before quit (consistent with copy-paste-retry-retry), plus 18% `INVALID_AGENT_SCOPE` with median 2 calls (consistent with developers who guessed/typed a malformed but plausible ID). Qualitative survey: "unclear what agent_id should be" and "docs jump to advanced examples" directly name this.

**Proposed change:** Insert a prerequisite block before the run example in quickstart.md explaining that `agent_id` must be created first, and replace the placeholder with text that makes it obvious the developer must substitute a real value. Keep the existing run example so the page flow is preserved.

```json
{
  "applyable": true,
  "edits": [
    {
      "file": "docs/quickstart.md",
      "action": "replace",
      "from_line_start": 21,
      "from_line_end": 32,
      "expected_content": "## Run your first agent\n\n```python\nrun = client.agents.run(\n    agent_id=\"agt_xxxxxxxx\",\n    input=\"What's the weather like in San Francisco?\",\n)\n\nprint(run.output)\n```\n\nThat's it.",
      "new_content": "## Create an agent (required before running)\n\nPluma agents are pre-configured: each agent has a name, a model, a toolset, and a system prompt. You must create one before calling `agents.run()`. This takes about 2 minutes.\n\nThe fastest path: go to https://dashboard.pluma.dev/agents, click \"Create agent,\" and copy the `agent_id` (it looks like `agt_8x3kqp2n`) from the top of the detail page. For programmatic creation, see [Configure your agent](agents.md).\n\nIf you call `agents.run()` without a valid `agent_id`, you will receive a `MISSING_AGENT_ID` or `INVALID_AGENT_SCOPE` error.\n\n## Run your first agent\n\nReplace `agt_REPLACE_WITH_YOUR_ID` below with the `agent_id` you just created:\n\n```python\nrun = client.agents.run(\n    agent_id=\"agt_REPLACE_WITH_YOUR_ID\",\n    input=\"What's the weather like in San Francisco?\",\n)\n\nprint(run.output)\n```\n\nThat's it."
    }
  ]
}
```

**How to verify:** `first_api_call_to_first_successful_agent_run` should rise from 46.9% toward the 70%+ range seen at other steps. Specifically, the `MISSING_AGENT_ID` signal (31% of dropoffs) should drop substantially and the `INVALID_AGENT_SCOPE` signal (18%) should drop partially. Support tickets mentioning `agent_id` should return toward baseline within one cohort cycle.

---

### Hypothesis 2: The README's top-level quickstart has the same placeholder problem and is the developer's first impression — many developers never reach `docs/quickstart.md` with a corrected mental model (Layer 3)

**Claim:** The README is the canonical landing page for the SDK (and is rendered on PyPI and GitHub). Its quickstart shows `agent_id="agt_xxxxxxxx"` in a runnable code block (line 13), with the agent-configuration link appearing *after* the example as a passing reference (line 21). Developers who install via `pip install pluma-sdk` and copy from the README will hit the same `MISSING_AGENT_ID` failure mode before they even land on `docs/quickstart.md`. This is structurally distinct from Hypothesis 1 because the README is reached through a different path (PyPI/GitHub, not the docs site) and the dropoff data shows 13% of failures are "successful first_api_call but no agent run attempted within 24h" — consistent with a developer who tried something from the README, got confused, and never came back.

**Evidence:**
- `README.md:12-19` — quickstart code block uses `agent_id="agt_xxxxxxxx"` with no preceding "you must create an agent first" line.
- `README.md:21` — agent-creation link is presented as supplementary ("See the [agent configuration guide]..."), not as a required prior step.
- Dropoff signal: 13% of dropoffs reach `first_api_call` but never attempt an agent run in 24 hours. This is consistent with developers who tried the README example, got a 400, and gave up without finding `docs/quickstart.md`. Combined with the GitHub-issues-tripled signal (developers are filing issues against the SDK repo, where the README lives, not the docs site), this points at the README as a distinct surface from the docs quickstart.

**Proposed change:** Reorder the README so the agent-creation prerequisite appears before the run example, and clarify the placeholder.

```json
{
  "applyable": true,
  "edits": [
    {
      "file": "README.md",
      "action": "replace",
      "from_line_start": 5,
      "from_line_end": 21,
      "expected_content": "## Quickstart\n\n```python\nfrom pluma import PlumaClient\n\nclient = PlumaClient(api_key=\"sk_pluma_...\")\n\nrun = client.agents.run(\n    agent_id=\"agt_xxxxxxxx\",\n    input=\"Summarize the Q3 earnings call transcript attached.\",\n    attachments=[\"earnings_q3.pdf\"],\n)\n\nprint(run.output)\n```\n\nSee the [agent configuration guide](docs/agents.md) for how to create an `agent_id` before running.",
      "new_content": "## Quickstart\n\nPluma agents are pre-configured. Before you can call `agents.run()`, you need an `agent_id` — create one at https://dashboard.pluma.dev/agents (about 2 minutes) or via [`client.agents.create()`](docs/agents.md). Then:\n\n```python\nfrom pluma import PlumaClient\n\nclient = PlumaClient(api_key=\"sk_pluma_...\")\n\n# Replace agt_REPLACE_WITH_YOUR_ID with the agent_id you created above.\nrun = client.agents.run(\n    agent_id=\"agt_REPLACE_WITH_YOUR_ID\",\n    input=\"Summarize the Q3 earnings call transcript attached.\",\n    attachments=[\"earnings_q3.pdf\"],\n)\n\nprint(run.output)\n```\n\nSee the [agent configuration guide](docs/agents.md) for full details on creating and managing agents."
    }
  ]
}
```

**How to verify:** The "successful first_api_call but no agent run attempted within 24h" signal (13% of dropoffs) should fall substantially — this cohort's behavior pattern (try once, give up, don't return) is most consistent with a bad first impression from the README. GitHub issues tagged "getting-started" on `pluma-sdk-python` should return toward baseline.

---

### Hypothesis 3: When a run starts but stalls, neither the SDK nor the error catalog tells the developer how to diagnose it, so 24% of dropoffs occur one-shot with no retry (Layer 2)

**Claim:** 24% of dropoffs at this step are developers whose `run.start` succeeded but who never saw a `run.complete` event within 5 minutes — and the median number of calls before they quit is 1. They make a single attempt, see nothing happen, and leave. The SDK's `agents.run()` method has no documented timeout, no documented streaming/progress affordance surfaced at decision time, and the error catalog's `MODEL_TIMEOUT` (504) only fires after the *server* gives up — it doesn't help a developer whose client is hanging waiting for a long synchronous response. The docstring at `sdk/agents.py:35-48` does not mention what to do when a run takes a long time, and the `stream` parameter is documented in one line with no link to when to use it. The quickstart's troubleshooting section just points back to the error reference, which has no entry for "my run is hanging."

**Evidence:**
- `sdk/agents.py:28-34` — `run()` signature has `stream: bool = False` but the developer-facing decision of when to use it is documented only as "If True, returns a streaming iterator instead of a final AgentRun" (line 41), with no guidance that long-running agents should use streaming or check intermediate events.
- `sdk/agents.py:35-48` — docstring covers args and return type but says nothing about expected duration, polling, or what to do if the call appears to hang.
- error catalog:`43-44` — `MODEL_TIMEOUT` is the only timeout-adjacent error documented, and it's a server-side outcome, not a client-side diagnostic for "I'm waiting and nothing is happening."
- `docs/quickstart.md:39-41` — Troubleshooting section says only "If your run isn't returning output, check the [error reference]" — but a stalled run produces no error, so this advice is a dead end for exactly this failure mode.
- Dropoff signal: 24% of dropoffs see `run.start` succeed and no `run.complete` within 5 minutes; median 1 call before quitting. The single-shot quit pattern is the tell that developers had no diagnostic affordance.

**Proposed change:** Add a "Long-running runs" troubleshooting entry to quickstart.md that points developers at streaming and at the `events` field on `AgentRun`, and add an entry to the error catalog covering the stalled-run case (even though it isn't an error, developers expect to look up "my run isn't completing" there).

```json
{
  "applyable": true,
  "edits": [
    {
      "file": "docs/quickstart.md",
      "action": "replace",
      "from_line_start": 39,
      "from_line_end": 41,
      "expected_content": "## Troubleshooting\n\nIf your run isn't returning output, check the [error reference](errors.md).",
      "new_content": "## Troubleshooting\n\nIf your run isn't returning output, check the [error reference](errors.md).\n\n**My run started but isn't completing.** Agent runs can take from a few seconds to several minutes depending on model and toolset. The synchronous `client.agents.run(...)` call blocks until the run completes or the server times out (returning `MODEL_TIMEOUT`). For runs you expect to take more than ~30 seconds, pass `stream=True` to receive intermediate events as they arrive:\n\n```python\nfor event in client.agents.run(agent_id=\"agt_...\", input=\"...\", stream=True):\n    print(event)\n```\n\nThis lets you see `tool_call`, `tool_result`, and progress events live, so you can tell whether the agent is making progress or stuck on a tool call."
    },
    {
      "file": "error catalog",
      "action": "insert_after",
      "at_line": 44,
      "new_content": "\n### (Not an error) Run started but never completes\nIf you see a `run.start` event in your logs but no `run.complete` within a few minutes, the run is in progress, not failed. Use `stream=True` on `client.agents.run()` to receive `tool_call` and `tool_result` events as they happen. If the run eventually fails server-side, you'll get `MODEL_TIMEOUT` (above) or `TOOL_TIMEOUT` (below)."
    }
  ]
}
```

**How to verify:** The "run.start succeeds but no run.complete within 5 minutes" signal (24% of dropoffs, median 1 call) should drop as developers either (a) use streaming and observe their run progressing, or (b) wait longer with confidence. If this hypothesis is correct, the median-calls-before-quit for the stalled-run cohort should rise from 1 toward 2-3 (developers retry with `stream=True`) even before the overall dropoff fraction falls.

## What this report is NOT

- These are hypotheses, not verified fixes. Each requires re-measurement after the change ships.
- These are the strongest candidates the investigation surfaced. Hypotheses such as "the `tool_call` missing-parameter dropoff (14%) is caused by under-specified system prompts" were considered but rejected as second-order: that failure occurs *inside* a run, which means the developer already cleared the `agent_id` hurdles — fixing the upstream Layer 3/4 issues will change which developers reach that failure mode and is a prerequisite to diagnosing it cleanly.
- This report does not prescribe priority order. The Hypothesis 1 edit is the cheapest and addresses the largest combined signal (49% of dropoffs), but apply-cost vs. expected-lift is the operator's call.