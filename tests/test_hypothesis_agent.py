"""Tests for hypothesis_agent using a stub Anthropic client.

Verifies message construction, token surfacing, and error paths
without any real API calls.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import pytest

from funnel_researcher.hypothesis_agent import _extract_text, generate_hypotheses
from funnel_researcher.loaders import DropoffData, FailureSignal, FunnelDefinition, FunnelStep
from funnel_researcher.product_reader import ProductArtifacts


# ---------- Stub client ----------


@dataclass
class _StubTextBlock:
    text: str
    type: str = "text"


@dataclass
class _StubToolUseBlock:
    type: str = "tool_use"
    name: str = "ignored"


@dataclass
class _StubUsage:
    input_tokens: int
    output_tokens: int


@dataclass
class _StubMessage:
    content: list
    usage: _StubUsage


class _StubMessages:
    def __init__(self, response: _StubMessage):
        self._response = response
        self.last_kwargs: dict[str, Any] | None = None

    def create(self, **kwargs) -> _StubMessage:
        self.last_kwargs = kwargs
        return self._response


class _StubClient:
    def __init__(self, response: _StubMessage):
        self.messages = _StubMessages(response)


# ---------- Fixtures ----------


def _funnel() -> FunnelDefinition:
    raw = {
        "name": "test",
        "metric": "activations",
        "target_dropoff_step": "b",
        "steps": [
            {"id": "a", "name": "A", "success_criterion": "did A"},
            {"id": "b", "name": "B", "success_criterion": "did B"},
        ],
    }
    return FunnelDefinition(
        name="test",
        metric="activations",
        target_dropoff_step="b",
        steps=[FunnelStep(**s) for s in raw["steps"]],
        raw=raw,
    )


def _dropoff() -> DropoffData:
    return DropoffData(
        cohort_name="cohort1",
        cohort_size=100,
        measurement_window_days=14,
        step_counts={"a": 100, "b": 50},
        step_pass_rates={"a_to_b": 0.5},
        target_step_failure_signals=[
            FailureSignal(signal="400 error", fraction_of_dropoffs=0.4, step="b"),
        ],
        raw={
            "cohort_name": "cohort1",
            "cohort_size": 100,
            "measurement_window_days": 14,
            "step_counts": {"a": 100, "b": 50},
            "step_pass_rates": {"a_to_b": 0.5},
            "target_step_failure_signals": [
                {"signal": "400 error", "fraction_of_dropoffs": 0.4, "step": "b"},
            ],
        },
    )


def _artifacts() -> ProductArtifacts:
    return ProductArtifacts(
        name="test_product",
        readme="hi",
        docs={"docs/quickstart.md": "Run X."},
        sdk_files={},
        error_catalog=None,
        openapi=None,
        extra_files={},
    )


# ---------- Tests ----------


def test_extract_text_single_block() -> None:
    msg = _StubMessage(
        content=[_StubTextBlock(text="hello world")],
        usage=_StubUsage(input_tokens=10, output_tokens=2),
    )
    assert _extract_text(msg) == "hello world"


def test_extract_text_filters_non_text_blocks() -> None:
    msg = _StubMessage(
        content=[
            _StubTextBlock(text="first part"),
            _StubToolUseBlock(),
            _StubTextBlock(text="second part"),
        ],
        usage=_StubUsage(input_tokens=10, output_tokens=4),
    )
    result = _extract_text(msg)
    assert "first part" in result
    assert "second part" in result
    assert "ignored" not in result


def test_generate_hypotheses_constructs_message_correctly() -> None:
    stub_response = _StubMessage(
        content=[_StubTextBlock(text="# Funnel diagnosis report\nbody")],
        usage=_StubUsage(input_tokens=5000, output_tokens=1500),
    )
    client = _StubClient(stub_response)

    report = generate_hypotheses(
        funnel=_funnel(),
        dropoff=_dropoff(),
        artifacts=_artifacts(),
        client=client,
    )

    kwargs = client.messages.last_kwargs
    assert kwargs is not None
    assert "system" in kwargs
    assert len(kwargs["system"]) > 1000  # the system prompt is substantial
    assert kwargs["messages"][0]["role"] == "user"
    user_content = kwargs["messages"][0]["content"]
    assert "test_product" not in user_content  # product name isn't in the prompt
    assert "Run X." in user_content  # docs content is

    assert report.markdown == "# Funnel diagnosis report\nbody"


def test_generate_hypotheses_surfaces_tokens_and_model() -> None:
    stub_response = _StubMessage(
        content=[_StubTextBlock(text="report body")],
        usage=_StubUsage(input_tokens=12345, output_tokens=678),
    )
    client = _StubClient(stub_response)

    report = generate_hypotheses(
        funnel=_funnel(),
        dropoff=_dropoff(),
        artifacts=_artifacts(),
        model="claude-opus-4-7",
        client=client,
    )

    assert report.markdown == "report body"
    assert report.input_tokens == 12345
    assert report.output_tokens == 678
    assert report.model == "claude-opus-4-7"


def test_generate_hypotheses_requires_api_key_or_client() -> None:
    """If no client is passed and ANTHROPIC_API_KEY is unset, raise clearly."""
    import os

    saved = os.environ.pop("ANTHROPIC_API_KEY", None)
    try:
        with pytest.raises(RuntimeError, match="Anthropic API key"):
            generate_hypotheses(
                funnel=_funnel(),
                dropoff=_dropoff(),
                artifacts=_artifacts(),
            )
    finally:
        if saved is not None:
            os.environ["ANTHROPIC_API_KEY"] = saved
