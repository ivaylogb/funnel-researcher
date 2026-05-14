"""The hypothesis-generation agent.

Calls the Anthropic API with the assembled system prompt + user message,
returns the markdown report and token usage.

Defaults to Opus for the cognitive task. Override via --model on the CLI.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any

from .loaders import DropoffData, FunnelDefinition
from .product_reader import ProductArtifacts
from .prompt_assembler import build_user_message, load_system_prompt


DEFAULT_MODEL = "claude-opus-4-7"
DEFAULT_MAX_TOKENS = 8000


@dataclass
class HypothesisReport:
    """The output of one diagnose run."""

    markdown: str
    input_tokens: int
    output_tokens: int
    model: str


def generate_hypotheses(
    *,
    funnel: FunnelDefinition,
    dropoff: DropoffData,
    artifacts: ProductArtifacts,
    model: str = DEFAULT_MODEL,
    max_tokens: int = DEFAULT_MAX_TOKENS,
    client: Any = None,
) -> HypothesisReport:
    """Call the model and return a HypothesisReport.

    The `client` parameter is a seam for testing — pass a stub with
    `.messages.create(...)` returning a `Message`-shaped object.
    """
    if client is None:
        client = _build_client()

    system_prompt = load_system_prompt()
    user_message = build_user_message(
        funnel=funnel,
        dropoff=dropoff,
        artifacts=artifacts,
    )

    response = client.messages.create(
        model=model,
        max_tokens=max_tokens,
        system=system_prompt,
        messages=[{"role": "user", "content": user_message}],
    )

    text = _extract_text(response)
    return HypothesisReport(
        markdown=text,
        input_tokens=response.usage.input_tokens,
        output_tokens=response.usage.output_tokens,
        model=model,
    )


def _build_client():
    """Construct an Anthropic client using ANTHROPIC_API_KEY from the environment."""
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        raise RuntimeError(
            "Anthropic API key not found. Set ANTHROPIC_API_KEY in the environment."
        )
    # Import locally so the package can be imported without anthropic installed
    # in test-only contexts.
    from anthropic import Anthropic

    return Anthropic(api_key=api_key)


def _extract_text(message: Any) -> str:
    """Concatenate text blocks from a Message response, ignoring non-text blocks."""
    parts: list[str] = []
    for block in message.content:
        block_type = getattr(block, "type", None)
        if block_type == "text":
            parts.append(getattr(block, "text", ""))
    return "\n".join(parts).strip()
