"""Tests for the funnel-researcher comparison renderer."""

from __future__ import annotations

from pathlib import Path

from funnel_researcher.applier import AppliedEdit, Edit
from funnel_researcher.comparison import render_comparison
from funnel_researcher.iterator import IterationResult


def _applied(file_path: Path, lines: str, before: str, after: str) -> AppliedEdit:
    return AppliedEdit(
        edit=Edit(action="replace", file=str(file_path)),
        file_path=file_path,
        line_range=lines,
        before_content=before,
        after_content=after,
        file_before_sha256="a" * 64,
        file_after_sha256="b" * 64,
    )


def test_render_comparison_includes_all_three_statuses(tmp_path: Path):
    product = tmp_path / "product"
    product.mkdir()
    (product / "README.md").write_text("x")

    results = [
        IterationResult(
            hypothesis_id=1, title="applied path (Layer 3)", layer="Layer 3",
            applyable=True,
            applied_edits=[_applied(product / "README.md", "1-1", "x", "y")],
        ),
        IterationResult(
            hypothesis_id=2, title="skipped path (Layer 4)", layer="Layer 4",
            applyable=False, skip_reason="needs human review",
        ),
        IterationResult(
            hypothesis_id=3, title="errored path (Layer 2)", layer="Layer 2",
            applyable=True, error="expected_content mismatch on line 5",
        ),
    ]

    out = render_comparison(results, product_dir=product)

    assert "# Iteration comparison" in out
    assert "Hypotheses in report: 3" in out
    assert "Applied cleanly: 1" in out
    assert "Skipped (applyable: false): 1" in out
    assert "Errored during apply: 1" in out

    assert "Hypothesis 1 — Layer 3" in out
    assert "applied (1 edit(s))" in out
    assert "applied path (Layer 3)" in out  # title rendered

    assert "Hypothesis 2 — Layer 4" in out
    assert "skipped (applyable: false)" in out
    assert "needs human review" in out

    assert "Hypothesis 3 — Layer 2" in out
    assert "errored (apply)" in out
    assert "expected_content mismatch on line 5" in out


def test_render_comparison_empty_results_is_graceful():
    out = render_comparison([])
    assert "# Iteration comparison" in out
    assert "Hypotheses in report: 0" in out
    assert "no `### Hypothesis N:` headers" in out
    # Footer present.
    assert "What this report is NOT" in out


def test_render_comparison_hypothesis_with_multiple_edits(tmp_path: Path):
    product = tmp_path / "product"
    product.mkdir()
    (product / "a.md").write_text("a")
    (product / "b.md").write_text("b")

    results = [
        IterationResult(
            hypothesis_id=1, title="multi-file (Layer 3)", layer="Layer 3",
            applyable=True,
            applied_edits=[
                _applied(product / "a.md", "1-1", "a", "A"),
                _applied(product / "b.md", "1-1", "b", "B"),
            ],
        ),
    ]

    out = render_comparison(results, product_dir=product)

    assert "applied (2 edit(s))" in out
    assert "`a.md`" in out
    assert "`b.md`" in out
    # Per-edit section renders both.
    assert "Edit 1:" in out
    assert "Edit 2:" in out


def test_render_comparison_files_modified_table_lists_each_file(tmp_path: Path):
    product = tmp_path / "product"
    product.mkdir()
    (product / "x.md").write_text("x")

    results = [
        IterationResult(
            hypothesis_id=1, title="t (Layer 3)", layer="Layer 3",
            applyable=True,
            applied_edits=[_applied(product / "x.md", "1-1", "x", "X")],
        ),
    ]

    out = render_comparison(results, product_dir=product)

    assert "## Files modified" in out
    assert "| `x.md` | 1 | 1-1 | yes |" in out


def test_render_comparison_what_this_is_not_section_present():
    out = render_comparison([])
    assert "## What this report is NOT" in out
    assert "does not pick a winner" in out.lower() or "not pick a winner" in out.lower()
    assert "No re-measurement" in out
    assert "identical before and after" in out
