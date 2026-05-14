"""funnel-researcher: structured diagnosis for developer-API funnel dropoff.

Same methodology as agent-researcher, applied to a different problem class:
why developers drop off at a specific step in an API activation funnel.

The diagnose subcommand reads:
- a funnel definition (YAML)
- dropoff data (JSON with per-step counts and failure signals)
- the product's artifacts (docs, SDK source, error catalog)

...and produces a structured hypothesis report categorized against a four-layer
model (funnel definition, API/SDK surface, docs/context, workflow/sequence),
with file:line evidence and applyable edit specs.
"""

__version__ = "0.1.0"
