"""Tests for the funnel-researcher delta renderer."""

from __future__ import annotations

from pathlib import Path

import pytest

from funnel_researcher.applier import AppliedEdit, Edit, EditSpec, apply_edits
from funnel_researcher.delta import render_delta


def _make_product(tmp_path: Path) -> Path:
    product = tmp_path / "product"
    (product / "docs").mkdir(parents=True)
    (product / "README.md").write_text("# Product\nline2\nline3\nline4\n")
    (product / "docs" / "quickstart.md").write_text("a\nb\nc\nd\n")
    return product


def test_render_delta_lists_files_modified(tmp_path: Path):
    product = _make_product(tmp_path)
    spec = EditSpec(applyable=True, edits=[
        Edit(
            action="replace", file="README.md",
            from_line_start=1, from_line_end=1,
            expected_content="# Product",
            new_content="# RENAMED",
        ),
    ])
    applied = apply_edits(spec, product)
    md = render_delta(applied, "H1: rename product (Layer 3)", product_dir=product)
    assert "## Files modified" in md
    assert "`README.md`" in md
    assert "1-1" in md


def test_render_delta_includes_hypothesis_summary(tmp_path: Path):
    product = _make_product(tmp_path)
    spec = EditSpec(applyable=True, edits=[
        Edit(action="insert_after", file="README.md", at_line=1, new_content="X"),
    ])
    applied = apply_edits(spec, product)
    md = render_delta(applied, "H2: testing the summary line (Layer 4)", product_dir=product)
    assert "H2: testing the summary line (Layer 4)" in md
    assert "## Hypothesis applied" in md


def test_render_delta_per_edit_section_shows_before_and_after_for_replace(tmp_path: Path):
    product = _make_product(tmp_path)
    spec = EditSpec(applyable=True, edits=[
        Edit(
            action="replace", file="docs/quickstart.md",
            from_line_start=2, from_line_end=2,
            expected_content="b",
            new_content="B",
        ),
    ])
    applied = apply_edits(spec, product)
    md = render_delta(applied, "H1: capitalize", product_dir=product)
    assert "**Before:**" in md
    assert "**After:**" in md
    assert "```\nb\n```" in md
    assert "```\nB\n```" in md


def test_render_delta_per_edit_section_for_insert_after_shows_inserted_block(tmp_path: Path):
    product = _make_product(tmp_path)
    spec = EditSpec(applyable=True, edits=[
        Edit(action="insert_after", file="README.md", at_line=2, new_content="INSERTED"),
    ])
    applied = apply_edits(spec, product)
    md = render_delta(applied, "H1: add note", product_dir=product)
    assert "**Inserted:**" in md
    assert "INSERTED" in md
    # Insert-after shouldn't show a "Before" block (there's no before content)
    assert "**Before:**" not in md


def test_render_delta_per_edit_section_for_delete_shows_deleted_block(tmp_path: Path):
    product = _make_product(tmp_path)
    spec = EditSpec(applyable=True, edits=[
        Edit(
            action="delete", file="docs/quickstart.md",
            from_line_start=2, from_line_end=2,
            expected_content="b",
        ),
    ])
    applied = apply_edits(spec, product)
    md = render_delta(applied, "H1: prune", product_dir=product)
    assert "**Deleted:**" in md
    assert "**After:**" not in md


def test_render_delta_dry_run_header_and_revert(tmp_path: Path):
    product = _make_product(tmp_path)
    spec = EditSpec(applyable=True, edits=[
        Edit(action="insert_after", file="README.md", at_line=1, new_content="X"),
    ])
    applied = apply_edits(spec, product, dry_run=True)
    md = render_delta(applied, "H1: test", product_dir=product, dry_run=True)
    assert "(dry run)" in md
    assert "Nothing to revert" in md


def test_render_delta_revert_section_lists_modified_files(tmp_path: Path):
    product = _make_product(tmp_path)
    spec = EditSpec(applyable=True, edits=[
        Edit(action="insert_after", file="README.md", at_line=1, new_content="X"),
        Edit(action="insert_after", file="docs/quickstart.md", at_line=1, new_content="Y"),
    ])
    applied = apply_edits(spec, product)
    md = render_delta(applied, "H1", product_dir=product)
    assert "## How to revert" in md
    assert "`README.md`" in md
    assert "`docs/quickstart.md`" in md
    assert "git checkout HEAD --" in md


def test_render_delta_handles_empty_applied_list_defensively():
    md = render_delta([], "H1: skipped before any apply")
    assert "Files modified" in md
    assert "(none)" in md
