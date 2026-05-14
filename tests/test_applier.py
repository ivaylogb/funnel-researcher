"""Tests for the funnel-researcher applier.

Covers:
- parse_hypothesis_edits: extraction by id, applyable: false, error paths
- apply_edits: all 4 actions, expected-content verification, overlap detection,
  snapshot/restore on failure, dry-run, virtual-name resolution ("error catalog")
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from funnel_researcher.applier import (
    AppliedEdit,
    ApplyError,
    Edit,
    EditSpec,
    ExpectedContentMismatch,
    NonApplyable,
    OverlappingEdits,
    UnknownAction,
    apply_edits,
    parse_hypothesis_edits,
)


# ---------- Helpers ----------


def _report(*hypotheses_jsons: str) -> str:
    """Build a minimal diagnosis report with N hypotheses, each carrying a JSON block."""
    parts = ["# Report\n\n## Hypotheses\n"]
    for i, blob in enumerate(hypotheses_jsons, start=1):
        parts.append(f"### Hypothesis {i}: synthetic (Layer 3)\n")
        parts.append("**Claim:** placeholder.\n\n```json\n" + blob + "\n```\n\n---\n")
    return "\n".join(parts)


def _make_product(tmp_path: Path) -> Path:
    """Build a minimal product directory mirroring product_reader's layout."""
    product = tmp_path / "product"
    (product / "docs").mkdir(parents=True)
    (product / "sdk").mkdir()
    (product / "README.md").write_text(
        "# Product\n\nline2\nline3\nline4\nline5\n"
    )
    (product / "docs" / "quickstart.md").write_text(
        "alpha\nbeta\ngamma\ndelta\nepsilon\n"
    )
    (product / "docs" / "errors.md").write_text(
        "## Error A\nLine 2 of errors\nLine 3 of errors\n"
    )
    (product / "sdk" / "agents.py").write_text(
        "def run():\n    pass\n"
    )
    return product


# ---------- parse_hypothesis_edits ----------


def test_parse_extracts_hypothesis_by_int_id():
    blob = json.dumps({
        "applyable": True,
        "edits": [{
            "file": "README.md",
            "action": "insert_after",
            "at_line": 1,
            "new_content": "extra",
        }],
    })
    spec = parse_hypothesis_edits(_report(blob), 1)
    assert spec.applyable is True
    assert len(spec.edits) == 1
    assert spec.edits[0].action == "insert_after"
    assert spec.edits[0].at_line == 1


def test_parse_extracts_hypothesis_by_h_prefix_string():
    blob = json.dumps({
        "applyable": True,
        "edits": [{
            "file": "README.md",
            "action": "delete",
            "from_line_start": 2,
            "from_line_end": 3,
            "expected_content": "x",
        }],
    })
    spec = parse_hypothesis_edits(_report(blob), "H1")
    assert spec.applyable is True
    assert spec.edits[0].action == "delete"


def test_parse_picks_correct_hypothesis_from_multi_hypothesis_report():
    h1 = json.dumps({"applyable": False, "reason": "h1 skip"})
    h2 = json.dumps({"applyable": True, "edits": [{
        "file": "README.md", "action": "insert_after", "at_line": 1, "new_content": "x",
    }]})
    h3 = json.dumps({"applyable": False, "reason": "h3 skip"})
    report = _report(h1, h2, h3)

    spec1 = parse_hypothesis_edits(report, 1)
    spec2 = parse_hypothesis_edits(report, 2)
    spec3 = parse_hypothesis_edits(report, 3)

    assert spec1.applyable is False and spec1.reason == "h1 skip"
    assert spec2.applyable is True and len(spec2.edits) == 1
    assert spec3.applyable is False and spec3.reason == "h3 skip"


def test_parse_returns_applyable_false_spec_with_reason():
    blob = json.dumps({"applyable": False, "reason": "needs cross-file refactor"})
    spec = parse_hypothesis_edits(_report(blob), 1)
    assert spec.applyable is False
    assert spec.reason == "needs cross-file refactor"
    assert spec.edits == []


def test_parse_raises_when_hypothesis_not_found():
    blob = json.dumps({"applyable": True, "edits": [{
        "file": "README.md", "action": "insert_after", "at_line": 1, "new_content": "x",
    }]})
    with pytest.raises(ValueError, match="Hypothesis 9 not found"):
        parse_hypothesis_edits(_report(blob), 9)


def test_parse_raises_on_missing_json_block():
    text = "### Hypothesis 1: no json here\n\nSome prose with no fenced block.\n"
    with pytest.raises(ValueError, match="no fenced ```json block"):
        parse_hypothesis_edits(text, 1)


def test_parse_raises_on_malformed_json():
    text = "### Hypothesis 1: bad\n\n```json\n{not valid json\n```\n"
    with pytest.raises(ValueError, match="not valid JSON"):
        parse_hypothesis_edits(text, 1)


def test_parse_raises_on_unknown_action():
    blob = json.dumps({"applyable": True, "edits": [{
        "file": "README.md", "action": "frobnicate", "at_line": 1, "new_content": "x",
    }]})
    with pytest.raises(UnknownAction, match="unknown action"):
        parse_hypothesis_edits(_report(blob), 1)


def test_parse_reads_from_file_path(tmp_path: Path):
    blob = json.dumps({"applyable": True, "edits": [{
        "file": "README.md", "action": "insert_after", "at_line": 1, "new_content": "x",
    }]})
    report_file = tmp_path / "diag.md"
    report_file.write_text(_report(blob))
    spec = parse_hypothesis_edits(report_file, 1)
    assert spec.applyable is True


# ---------- apply_edits: actions ----------


def test_apply_insert_after_inserts_at_correct_position(tmp_path: Path):
    product = _make_product(tmp_path)
    spec = EditSpec(applyable=True, edits=[
        Edit(action="insert_after", file="README.md", at_line=2, new_content="INSERTED"),
    ])
    applied = apply_edits(spec, product)
    assert len(applied) == 1
    expected = "# Product\n\nINSERTED\nline2\nline3\nline4\nline5\n"
    assert (product / "README.md").read_text() == expected
    assert applied[0].after_content == "INSERTED"
    assert applied[0].before_content == ""
    assert applied[0].line_range == "(insert after 2)"


def test_apply_replace_replaces_range_with_new_content(tmp_path: Path):
    product = _make_product(tmp_path)
    spec = EditSpec(applyable=True, edits=[
        Edit(
            action="replace", file="docs/quickstart.md",
            from_line_start=2, from_line_end=4,
            expected_content="beta\ngamma\ndelta",
            new_content="NEW1\nNEW2",
        ),
    ])
    apply_edits(spec, product)
    assert (product / "docs/quickstart.md").read_text() == "alpha\nNEW1\nNEW2\nepsilon\n"


def test_apply_delete_removes_range(tmp_path: Path):
    product = _make_product(tmp_path)
    spec = EditSpec(applyable=True, edits=[
        Edit(
            action="delete", file="docs/quickstart.md",
            from_line_start=2, from_line_end=3,
            expected_content="beta\ngamma",
        ),
    ])
    apply_edits(spec, product)
    assert (product / "docs/quickstart.md").read_text() == "alpha\ndelta\nepsilon\n"


def test_apply_move_relocates_range(tmp_path: Path):
    product = _make_product(tmp_path)
    spec = EditSpec(applyable=True, edits=[
        Edit(
            action="move", file="docs/quickstart.md",
            from_line_start=2, from_line_end=3,
            to_line=5,
            expected_content="beta\ngamma",
        ),
    ])
    apply_edits(spec, product)
    # "beta\ngamma" moves from lines 2-3 to after line 5
    assert (product / "docs/quickstart.md").read_text() == "alpha\ndelta\nepsilon\nbeta\ngamma\n"


# ---------- apply_edits: validation ----------


def test_apply_raises_on_expected_content_mismatch(tmp_path: Path):
    product = _make_product(tmp_path)
    spec = EditSpec(applyable=True, edits=[
        Edit(
            action="replace", file="docs/quickstart.md",
            from_line_start=2, from_line_end=3,
            expected_content="WRONG\nGUESS",
            new_content="X",
        ),
    ])
    original = (product / "docs/quickstart.md").read_text()
    with pytest.raises(ExpectedContentMismatch):
        apply_edits(spec, product)
    # File must be untouched
    assert (product / "docs/quickstart.md").read_text() == original


def test_apply_raises_on_overlapping_edits_within_same_file(tmp_path: Path):
    product = _make_product(tmp_path)
    spec = EditSpec(applyable=True, edits=[
        Edit(
            action="replace", file="docs/quickstart.md",
            from_line_start=2, from_line_end=3,
            expected_content="beta\ngamma",
            new_content="X",
        ),
        Edit(
            action="delete", file="docs/quickstart.md",
            from_line_start=3, from_line_end=4,
            expected_content="gamma\ndelta",
        ),
    ])
    original = (product / "docs/quickstart.md").read_text()
    with pytest.raises(OverlappingEdits):
        apply_edits(spec, product)
    assert (product / "docs/quickstart.md").read_text() == original


def test_apply_raises_when_insert_after_targets_a_deleted_line(tmp_path: Path):
    """An insert_after at line N when another edit drops line N has no anchor."""
    product = tmp_path / "product"
    (product / "docs").mkdir(parents=True)
    lines = [f"line{i}" for i in range(1, 21)]
    (product / "docs" / "quickstart.md").write_text("\n".join(lines) + "\n")
    expected_5_to_15 = "\n".join(lines[4:15])  # 1-indexed lines 5..15

    spec = EditSpec(applyable=True, edits=[
        Edit(
            action="delete", file="docs/quickstart.md",
            from_line_start=5, from_line_end=15,
            expected_content=expected_5_to_15,
        ),
        Edit(
            action="insert_after", file="docs/quickstart.md",
            at_line=10,
            new_content="this should have nowhere to land",
        ),
    ])
    original = (product / "docs/quickstart.md").read_text()
    with pytest.raises(OverlappingEdits, match="line 10"):
        apply_edits(spec, product)
    assert (product / "docs/quickstart.md").read_text() == original


def test_apply_handles_multiple_non_overlapping_edits_in_same_file(tmp_path: Path):
    product = _make_product(tmp_path)
    spec = EditSpec(applyable=True, edits=[
        Edit(
            action="replace", file="docs/quickstart.md",
            from_line_start=1, from_line_end=1,
            expected_content="alpha",
            new_content="ALPHA",
        ),
        Edit(
            action="replace", file="docs/quickstart.md",
            from_line_start=5, from_line_end=5,
            expected_content="epsilon",
            new_content="EPSILON",
        ),
    ])
    apply_edits(spec, product)
    assert (product / "docs/quickstart.md").read_text() == "ALPHA\nbeta\ngamma\ndelta\nEPSILON\n"


def test_apply_raises_on_non_applyable_spec(tmp_path: Path):
    product = _make_product(tmp_path)
    spec = EditSpec(applyable=False, reason="needs cross-cutting work")
    with pytest.raises(NonApplyable, match="needs cross-cutting work"):
        apply_edits(spec, product)


def test_apply_raises_on_unresolvable_file(tmp_path: Path):
    product = _make_product(tmp_path)
    spec = EditSpec(applyable=True, edits=[
        Edit(action="insert_after", file="does_not_exist.md", at_line=1, new_content="x"),
    ])
    with pytest.raises(FileNotFoundError, match="does_not_exist.md"):
        apply_edits(spec, product)


# ---------- apply_edits: virtual-name resolution ----------


def test_apply_resolves_error_catalog_virtual_name_to_docs_errors_md(tmp_path: Path):
    product = _make_product(tmp_path)
    spec = EditSpec(applyable=True, edits=[
        Edit(
            action="insert_after", file="error catalog",
            at_line=3, new_content="### Error B\nNew error doc",
        ),
    ])
    applied = apply_edits(spec, product)
    assert applied[0].file_path == product / "docs/errors.md"
    assert (product / "docs/errors.md").read_text() == (
        "## Error A\nLine 2 of errors\nLine 3 of errors\n### Error B\nNew error doc\n"
    )


def test_apply_resolves_bare_basename_when_unique(tmp_path: Path):
    """A bare basename like 'agents.py' should resolve to sdk/agents.py when unique."""
    product = _make_product(tmp_path)
    spec = EditSpec(applyable=True, edits=[
        Edit(action="insert_after", file="agents.py", at_line=2, new_content="    # appended"),
    ])
    applied = apply_edits(spec, product)
    assert applied[0].file_path == product / "sdk/agents.py"


# ---------- apply_edits: snapshot/restore and dry-run ----------


def test_apply_snapshot_restores_when_a_later_edit_fails(tmp_path: Path):
    """If validation fails on edit #2, edit #1's file state must be restored."""
    product = _make_product(tmp_path)
    original_readme = (product / "README.md").read_text()
    original_quickstart = (product / "docs/quickstart.md").read_text()
    spec = EditSpec(applyable=True, edits=[
        # Edit #1: valid, on README.md
        Edit(
            action="replace", file="README.md",
            from_line_start=1, from_line_end=1,
            expected_content="# Product",
            new_content="# RENAMED",
        ),
        # Edit #2: invalid expected_content, on docs/quickstart.md
        Edit(
            action="replace", file="docs/quickstart.md",
            from_line_start=1, from_line_end=1,
            expected_content="WRONG",
            new_content="X",
        ),
    ])
    with pytest.raises(ExpectedContentMismatch):
        apply_edits(spec, product)
    # Both files must be untouched
    assert (product / "README.md").read_text() == original_readme
    assert (product / "docs/quickstart.md").read_text() == original_quickstart


def test_apply_dry_run_validates_but_writes_nothing(tmp_path: Path):
    product = _make_product(tmp_path)
    original = (product / "README.md").read_text()
    spec = EditSpec(applyable=True, edits=[
        Edit(
            action="replace", file="README.md",
            from_line_start=1, from_line_end=1,
            expected_content="# Product",
            new_content="# RENAMED",
        ),
    ])
    applied = apply_edits(spec, product, dry_run=True)
    assert len(applied) == 1
    assert applied[0].after_content == "# RENAMED"
    # File on disk is untouched
    assert (product / "README.md").read_text() == original


def test_apply_dry_run_still_raises_on_mismatch(tmp_path: Path):
    product = _make_product(tmp_path)
    spec = EditSpec(applyable=True, edits=[
        Edit(
            action="replace", file="README.md",
            from_line_start=1, from_line_end=1,
            expected_content="WRONG",
            new_content="X",
        ),
    ])
    with pytest.raises(ExpectedContentMismatch):
        apply_edits(spec, product, dry_run=True)


def test_apply_returns_file_hashes_reflecting_change(tmp_path: Path):
    product = _make_product(tmp_path)
    spec = EditSpec(applyable=True, edits=[
        Edit(action="insert_after", file="README.md", at_line=1, new_content="X"),
    ])
    applied = apply_edits(spec, product)
    assert applied[0].file_before_sha256 != applied[0].file_after_sha256
