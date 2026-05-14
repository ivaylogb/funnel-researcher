"""Render the delta report for a funnel-researcher apply run.

After `apply` modifies product artifact files, the operator needs a structured
record of what changed: which files were touched, which lines, what the
before/after content was, and how to revert. There is no re-eval coupling — v1
of apply does not run anything against the modified product. The delta is a
record of the mechanical change; the operator decides whether to ship it.
"""

from __future__ import annotations

from pathlib import Path
from typing import Iterable

from .applier import AppliedEdit


def render_delta(
    applied_edits: list[AppliedEdit],
    hypothesis_summary: str,
    *,
    product_dir: Path | None = None,
    dry_run: bool = False,
) -> str:
    """Render an apply run into a markdown delta report.

    Args:
        applied_edits: the AppliedEdit list returned by apply_edits().
        hypothesis_summary: a one-paragraph summary of which hypothesis was
            applied (claim + layer). Goes near the top so the report reads
            standalone.
        product_dir: optional product root; if given, file paths in the report
            are shown relative to it.
        dry_run: if True, the report header notes that no files were written.
    """
    parts: list[str] = []
    title_suffix = " (dry run)" if dry_run else ""
    parts.append(f"# Apply delta{title_suffix}")
    parts.append("")
    parts.append("## Hypothesis applied")
    parts.append("")
    parts.append(hypothesis_summary.strip())
    parts.append("")
    parts.append(_files_modified_section(applied_edits, product_dir))
    parts.append("")
    parts.append(_per_edit_section(applied_edits, product_dir))
    parts.append("")
    parts.append(_revert_section(applied_edits, product_dir, dry_run))
    return "\n".join(parts).rstrip() + "\n"


def _files_modified_section(
    applied_edits: list[AppliedEdit],
    product_dir: Path | None,
) -> str:
    if not applied_edits:
        return "## Files modified\n\n(none)"

    # One row per file (collapse multi-edit files), with the union of line ranges.
    by_file: dict[Path, list[AppliedEdit]] = {}
    for entry in applied_edits:
        by_file.setdefault(entry.file_path, []).append(entry)

    lines = [
        "## Files modified",
        "",
        "| File | Edits | Lines affected | Changed |",
        "|---|---|---|---|",
    ]
    for path, entries in by_file.items():
        rel = _rel(path, product_dir)
        ranges = ", ".join(e.line_range for e in entries)
        changed = "yes" if entries[0].file_before_sha256 != entries[0].file_after_sha256 else "no"
        lines.append(f"| `{rel}` | {len(entries)} | {ranges} | {changed} |")
    return "\n".join(lines)


def _per_edit_section(
    applied_edits: list[AppliedEdit],
    product_dir: Path | None,
) -> str:
    if not applied_edits:
        return "## Per-edit detail\n\n(no edits applied)"

    blocks: list[str] = ["## Per-edit detail", ""]
    for i, entry in enumerate(applied_edits, start=1):
        rel = _rel(entry.file_path, product_dir)
        blocks.append(f"### Edit {i}: `{rel}` ({entry.edit.action}, lines {entry.line_range})")
        blocks.append("")
        if entry.edit.action == "insert_after":
            blocks.append("**Inserted:**")
            blocks.append("")
            blocks.append(_fenced(entry.after_content))
        elif entry.edit.action == "delete":
            blocks.append("**Deleted:**")
            blocks.append("")
            blocks.append(_fenced(entry.before_content))
        elif entry.edit.action == "move":
            blocks.append("**Moved (content unchanged, location changed):**")
            blocks.append("")
            blocks.append(_fenced(entry.before_content))
        else:  # replace
            blocks.append("**Before:**")
            blocks.append("")
            blocks.append(_fenced(entry.before_content))
            blocks.append("")
            blocks.append("**After:**")
            blocks.append("")
            blocks.append(_fenced(entry.after_content))
        blocks.append("")
    return "\n".join(blocks).rstrip()


def _revert_section(
    applied_edits: list[AppliedEdit],
    product_dir: Path | None,
    dry_run: bool,
) -> str:
    if dry_run:
        return (
            "## How to revert\n\n"
            "Dry run — no files were modified. Nothing to revert."
        )

    files = _unique_paths(applied_edits)
    if not files:
        return "## How to revert\n\n(no files written)"

    lines = ["## How to revert", ""]
    lines.append(
        "The applier did NOT revert these edits. The operator decides whether "
        "to keep them. Files written by this run:"
    )
    lines.append("")
    for f in files:
        lines.append(f"- `{_rel(f, product_dir)}`")
    lines.append("")
    lines.append(
        "To revert, run `git checkout HEAD --` followed by the file paths "
        "above (inside the product's git repo, if any), or restore from your "
        "own backup."
    )
    return "\n".join(lines)


def _unique_paths(applied_edits: list[AppliedEdit]) -> list[Path]:
    seen: set[Path] = set()
    ordered: list[Path] = []
    for entry in applied_edits:
        if entry.file_path not in seen:
            seen.add(entry.file_path)
            ordered.append(entry.file_path)
    return ordered


def _rel(path: Path, product_dir: Path | None) -> str:
    if product_dir is None:
        return str(path)
    try:
        return str(path.relative_to(product_dir))
    except ValueError:
        return str(path)


def _fenced(content: str) -> str:
    return f"```\n{content}\n```"
