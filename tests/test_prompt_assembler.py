"""Tests for prompt assembler. Covers line numbering, file ordering,
placeholder substitution, and survival of brace-containing content
(the str.format trap that bit agent-researcher twice).
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from funnel_researcher.loaders import DropoffData, FailureSignal, FunnelDefinition, FunnelStep
from funnel_researcher.product_reader import ProductArtifacts
from funnel_researcher.prompt_assembler import (
    _code_block,
    _format_files,
    _number_lines,
    build_user_message,
    load_system_prompt,
    load_user_template,
)


def _funnel() -> FunnelDefinition:
    steps = [
        FunnelStep(id="a", name="A", success_criterion="did A"),
        FunnelStep(id="b", name="B", success_criterion="did B"),
    ]
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
        steps=steps,
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
        qualitative_signals=["Support tickets up."],
        raw={
            "cohort_name": "cohort1",
            "cohort_size": 100,
            "measurement_window_days": 14,
            "step_counts": {"a": 100, "b": 50},
            "step_pass_rates": {"a_to_b": 0.5},
            "target_step_failure_signals": [
                {"signal": "400 error", "fraction_of_dropoffs": 0.4, "step": "b"},
            ],
            "qualitative_signals": ["Support tickets up."],
        },
    )


def _artifacts(**overrides) -> ProductArtifacts:
    defaults = dict(
        name="test_product",
        readme="line1\nline2\nline3",
        docs={},
        sdk_files={},
        error_catalog=None,
        openapi=None,
        extra_files={},
    )
    defaults.update(overrides)
    return ProductArtifacts(**defaults)


def test_load_system_prompt_returns_substantial_content() -> None:
    sys_prompt = load_system_prompt()
    assert len(sys_prompt) > 1000
    assert "four-layer model" in sys_prompt
    assert "Forbidden hypotheses" in sys_prompt


def test_load_user_template_has_required_placeholders() -> None:
    tmpl = load_user_template()
    for placeholder in [
        "{funnel_yaml}",
        "{target_dropoff_step}",
        "{dropoff_json}",
        "{readme_content}",
        "{docs_section}",
        "{sdk_section}",
        "{errors_section}",
        "{additional_files_section}",
    ]:
        assert placeholder in tmpl


def test_number_lines_format() -> None:
    out = _number_lines("alpha\nbeta\ngamma")
    assert "   1  alpha" in out
    assert "   2  beta" in out
    assert "   3  gamma" in out


def test_number_lines_handles_blank_lines() -> None:
    out = _number_lines("alpha\n\ngamma")
    assert "   1  alpha" in out
    assert "   2  " in out  # numbered blank
    assert "   3  gamma" in out


def test_number_lines_padding_for_large_files() -> None:
    big = "\n".join(["x"] * 1234)
    out = _number_lines(big)
    assert "1000  x" in out  # 4-char gutter holds 4-digit numbers
    assert "1234  x" in out


def test_code_block_includes_label_and_numbered_content() -> None:
    out = _code_block("docs/quickstart.md", "hello\nworld", lang="markdown")
    assert "#### docs/quickstart.md" in out
    assert "```markdown" in out
    assert "   1  hello" in out
    assert "   2  world" in out


def test_build_user_message_substitutes_all_fields() -> None:
    msg = build_user_message(
        funnel=_funnel(),
        dropoff=_dropoff(),
        artifacts=_artifacts(),
    )

    # No unsubstituted placeholders
    for placeholder in [
        "{funnel_yaml}",
        "{target_dropoff_step}",
        "{dropoff_json}",
        "{readme_content}",
        "{docs_section}",
        "{sdk_section}",
        "{errors_section}",
    ]:
        assert placeholder not in msg

    # Key fields appear in the output
    assert "name: test" in msg
    assert "target_dropoff_step: b" in msg or '"b"' in msg
    assert '"signal": "400 error"' in msg
    assert "   1  line1" in msg  # README is numbered


def test_build_user_message_survives_braces_in_docs() -> None:
    """If a docs file contains literal { or { N }, format() must not break."""
    docs = {
        "docs/template.md": "Use {var} like this. And {{escaped}} too.",
    }
    msg = build_user_message(
        funnel=_funnel(),
        dropoff=_dropoff(),
        artifacts=_artifacts(docs=docs),
    )
    # The literal braces in the docs must round-trip
    assert "{var}" in msg or "{{var}}" in msg  # accept either; the point is no crash


def test_build_user_message_omits_additional_section_when_empty() -> None:
    msg = build_user_message(
        funnel=_funnel(),
        dropoff=_dropoff(),
        artifacts=_artifacts(),
    )
    assert "### Additional artifacts" not in msg


def test_build_user_message_includes_openapi_when_present() -> None:
    msg = build_user_message(
        funnel=_funnel(),
        dropoff=_dropoff(),
        artifacts=_artifacts(openapi="openapi: 3.0.0"),
    )
    assert "### Additional artifacts" in msg
    assert "openapi: 3.0.0" in msg or "   1  openapi: 3.0.0" in msg


def test_format_files_orders_alphabetically_and_numbers_each() -> None:
    files = {
        "docs/zebra.md": "z line",
        "docs/alpha.md": "a line",
    }
    out = _format_files(files, lang="markdown")

    # Alpha appears before zebra (sorted)
    assert out.index("docs/alpha.md") < out.index("docs/zebra.md")
    # Each file is independently numbered starting from 1
    assert out.count("   1  ") == 2


def test_format_files_with_lang_by_ext_for_sdk() -> None:
    files = {"sdk/client.py": "class C: pass"}
    out = _format_files(files, lang_by_ext=True)
    assert "```python" in out


def test_build_user_message_handles_no_readme() -> None:
    msg = build_user_message(
        funnel=_funnel(),
        dropoff=_dropoff(),
        artifacts=_artifacts(readme=None),
    )
    assert "[no README.md found]" in msg


def test_build_user_message_handles_no_docs() -> None:
    msg = build_user_message(
        funnel=_funnel(),
        dropoff=_dropoff(),
        artifacts=_artifacts(docs={}),
    )
    assert "[no docs/ files found]" in msg
