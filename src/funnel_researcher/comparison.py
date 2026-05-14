"""Render iterate results into a side-by-side comparison report.

Each applied hypothesis gets a block with its mechanical diff; skipped and
errored hypotheses get short status blocks so the operator can see at a
glance which hypotheses were viable. There is no recommendation — the
applier does not pick a winner.

The per-edit diff rendering is shared with delta.py via two helpers from
that module. They are package-internal (leading underscore) but used here
intentionally; iterate and apply both render AppliedEdit lists and the
shape is identical.
"""

from __future__ import annotations

from pathlib import Path
from typing import Optional

from .delta import _files_modified_section, _per_edit_section
from .iterator import IterationResult


def render_comparison(
    results: list[IterationResult],
    *,
    report_path: Optional[Path] = None,
    product_dir: Optional[Path] = None,
    dry_run: bool = False,
) -> str:
    """Render a markdown comparison covering every hypothesis in `results`."""
    n_applied = sum(
        1 for r in results
        if r.applyable and r.applied_edits and not r.error
    )
    n_skipped = sum(1 for r in results if not r.applyable and not r.error)
    n_errored = sum(1 for r in results if r.error)

    parts: list[str] = []
    title_suffix = " (dry run)" if dry_run else ""
    parts.append(f"# Iteration comparison{title_suffix}")
    parts.append("")
    parts.append("## Summary")
    parts.append("")
    parts.append(f"- Hypotheses in report: {len(results)}")
    parts.append(f"- Applied cleanly: {n_applied}")
    parts.append(f"- Skipped (applyable: false): {n_skipped}")
    parts.append(f"- Errored during apply: {n_errored}")
    if report_path is not None:
        parts.append(f"- Source report: `{report_path}`")
    parts.append("")

    if not results:
        parts.append("_The report contained no `### Hypothesis N:` headers._")
        parts.append("")
    else:
        for result in results:
            parts.append(_hypothesis_block(result, product_dir))
            parts.append("")

    parts.append(_what_this_is_not_section())

    return "\n".join(parts).rstrip() + "\n"


def _hypothesis_block(
    result: IterationResult,
    product_dir: Optional[Path],
) -> str:
    lines: list[str] = []
    layer = f" — {result.layer}" if result.layer else ""
    lines.append(f"## Hypothesis {result.hypothesis_id}{layer}")
    lines.append("")
    if result.title:
        lines.append(f"**Title:** {result.title}")
        lines.append("")

    if not result.applyable and not result.error:
        lines.append("**Status:** skipped (applyable: false)")
        lines.append("")
        if result.skip_reason:
            lines.append(f"**Reason:** {result.skip_reason}")
        return "\n".join(lines).rstrip()

    if result.error:
        status = "errored (parse)" if not result.applyable else "errored (apply)"
        lines.append(f"**Status:** {status}")
        lines.append("")
        lines.append("```")
        lines.append(result.error)
        lines.append("```")
        return "\n".join(lines).rstrip()

    lines.append(f"**Status:** applied ({len(result.applied_edits)} edit(s))")
    lines.append("")
    lines.append(_files_modified_section(result.applied_edits, product_dir))
    lines.append("")
    lines.append(_per_edit_section(result.applied_edits, product_dir))
    return "\n".join(lines).rstrip()


def _what_this_is_not_section() -> str:
    return (
        "## What this report is NOT\n"
        "\n"
        "- This is a side-by-side view of every applyable hypothesis's "
        "mechanical changes — not a recommendation. The iterator does not "
        "pick a winner.\n"
        "- No re-measurement is run. v1 of iterate has no eval coupling; "
        "each hypothesis's predicted lift is the hypothesis author's claim, "
        "not a measured outcome.\n"
        "- The product directory is identical before and after iterate. "
        "Each hypothesis is applied against the same baseline and reverted "
        "before the next is processed.\n"
        "- The operator picks which hypothesis to ship. Use the diagnose "
        "report's evidence and this comparison's mechanical diffs together."
    )
