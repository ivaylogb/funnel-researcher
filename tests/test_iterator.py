"""Tests for the funnel-researcher iterator.

Covers:
- enumerate every hypothesis, in report order
- skip applyable: false with reason recorded
- apply success path, with AppliedEdit list populated
- apply errors (ExpectedContentMismatch, OverlappingEdits) caught per-hypothesis;
  iteration continues
- snapshot/revert: product dir state identical before and after iterate
- multiple hypotheses touching same file → each in isolation, not cumulative
- empty report → empty result list
- dry_run pass-through
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

from funnel_researcher.iterator import IterationResult, iterate_report


# ---------- Helpers ----------


def _report(*hypotheses: tuple[str, dict]) -> str:
    """Build a minimal diagnosis report.

    Each tuple is (title_suffix, spec_dict). title_suffix becomes the part
    after `### Hypothesis N:` so layer extraction can be exercised.
    """
    parts = ["# Diagnosis\n\n## Hypotheses\n"]
    for i, (title, blob) in enumerate(hypotheses, start=1):
        parts.append(f"### Hypothesis {i}: {title}\n")
        parts.append("**Claim:** placeholder.\n\n```json\n" + json.dumps(blob) + "\n```\n\n---\n")
    return "\n".join(parts)


def _make_product(tmp_path: Path) -> Path:
    product = tmp_path / "product"
    (product / "docs").mkdir(parents=True)
    (product / "README.md").write_text("# Product\n\nline2\nline3\nline4\n")
    (product / "docs" / "quickstart.md").write_text(
        "alpha\nbeta\ngamma\ndelta\nepsilon\n"
    )
    return product


def _sha_tree(root: Path) -> dict[str, str]:
    out: dict[str, str] = {}
    for p in sorted(root.rglob("*")):
        if p.is_file():
            out[str(p.relative_to(root))] = hashlib.sha256(p.read_bytes()).hexdigest()
    return out


# ---------- Happy path / structure ----------


def test_iterate_returns_one_result_per_hypothesis_in_order(tmp_path: Path):
    product = _make_product(tmp_path)
    h1 = ("synthetic A (Layer 3)", {
        "applyable": True,
        "edits": [{
            "file": "README.md", "action": "insert_after",
            "at_line": 1, "new_content": "X",
        }],
    })
    h2 = ("synthetic B (Layer 4)", {"applyable": False, "reason": "needs human"})
    h3 = ("synthetic C (Layer 2)", {
        "applyable": True,
        "edits": [{
            "file": "docs/quickstart.md", "action": "replace",
            "from_line_start": 2, "from_line_end": 2,
            "expected_content": "beta", "new_content": "BETA",
        }],
    })

    results = iterate_report(_report(h1, h2, h3), product)

    assert [r.hypothesis_id for r in results] == [1, 2, 3]
    assert results[0].applyable and results[0].applied_edits and not results[0].error
    assert not results[1].applyable and results[1].skip_reason == "needs human"
    assert results[2].applyable and results[2].applied_edits and not results[2].error


def test_iterate_extracts_title_and_layer(tmp_path: Path):
    product = _make_product(tmp_path)
    blob = {"applyable": False, "reason": "x"}
    report = _report(("My short claim (Layer 3)", blob))

    results = iterate_report(report, product)

    assert results[0].title == "My short claim (Layer 3)"
    assert results[0].layer == "Layer 3"


def test_iterate_handles_title_without_layer(tmp_path: Path):
    product = _make_product(tmp_path)
    blob = {"applyable": False, "reason": "x"}
    report = _report(("Just a title", blob))

    results = iterate_report(report, product)

    assert results[0].title == "Just a title"
    assert results[0].layer is None


# ---------- Skipping ----------


def test_iterate_skip_applyable_false_records_reason(tmp_path: Path):
    product = _make_product(tmp_path)
    report = _report(("h1 (Layer 3)", {
        "applyable": False, "reason": "requires a cross-cutting redesign",
    }))

    results = iterate_report(report, product)

    assert len(results) == 1
    assert results[0].applyable is False
    assert results[0].skip_reason == "requires a cross-cutting redesign"
    assert results[0].applied_edits == []
    assert results[0].error is None


def test_iterate_all_applyable_false_returns_all_skipped(tmp_path: Path):
    product = _make_product(tmp_path)
    h1 = ("h1 (Layer 3)", {"applyable": False, "reason": "r1"})
    h2 = ("h2 (Layer 4)", {"applyable": False, "reason": "r2"})

    results = iterate_report(_report(h1, h2), product)

    assert len(results) == 2
    assert all(not r.applyable for r in results)
    assert [r.skip_reason for r in results] == ["r1", "r2"]
    assert all(r.applied_edits == [] for r in results)


# ---------- Error isolation ----------


def test_iterate_apply_error_recorded_other_hypotheses_still_process(tmp_path: Path):
    product = _make_product(tmp_path)
    # h1 has wrong expected_content → ExpectedContentMismatch
    h1 = ("bad expected (Layer 3)", {
        "applyable": True,
        "edits": [{
            "file": "docs/quickstart.md", "action": "replace",
            "from_line_start": 2, "from_line_end": 2,
            "expected_content": "NOT_ACTUAL", "new_content": "X",
        }],
    })
    # h2 is valid
    h2 = ("good (Layer 4)", {
        "applyable": True,
        "edits": [{
            "file": "README.md", "action": "insert_after",
            "at_line": 1, "new_content": "ok",
        }],
    })

    results = iterate_report(_report(h1, h2), product)

    assert len(results) == 2
    assert results[0].applyable is True
    assert results[0].error is not None
    assert "expected_content" in results[0].error
    assert results[0].applied_edits == []
    # h2 still applied cleanly.
    assert results[1].applyable is True
    assert results[1].error is None
    assert len(results[1].applied_edits) == 1


# ---------- Snapshot / revert ----------


def test_iterate_does_not_mutate_product_dir_at_rest(tmp_path: Path):
    product = _make_product(tmp_path)
    pre = _sha_tree(product)

    h1 = ("real edit (Layer 3)", {
        "applyable": True,
        "edits": [{
            "file": "docs/quickstart.md", "action": "replace",
            "from_line_start": 2, "from_line_end": 2,
            "expected_content": "beta", "new_content": "BETA_REPLACED",
        }],
    })
    h2 = ("real edit 2 (Layer 4)", {
        "applyable": True,
        "edits": [{
            "file": "README.md", "action": "insert_after",
            "at_line": 1, "new_content": "INSERTED",
        }],
    })

    iterate_report(_report(h1, h2), product)

    post = _sha_tree(product)
    assert post == pre, "product dir must be byte-identical before and after iterate"


def test_iterate_isolates_overlapping_file_edits_across_hypotheses(tmp_path: Path):
    """Two hypotheses both target the same file with mutually exclusive edits.

    If each were applied cumulatively, the second's expected_content would
    fail. Snapshot isolation guarantees each starts from a clean baseline.
    """
    product = _make_product(tmp_path)
    h1 = ("rewrites quickstart line 2 (Layer 3)", {
        "applyable": True,
        "edits": [{
            "file": "docs/quickstart.md", "action": "replace",
            "from_line_start": 2, "from_line_end": 2,
            "expected_content": "beta", "new_content": "BETA_H1",
        }],
    })
    h2 = ("rewrites quickstart line 2 differently (Layer 3)", {
        "applyable": True,
        "edits": [{
            "file": "docs/quickstart.md", "action": "replace",
            "from_line_start": 2, "from_line_end": 2,
            "expected_content": "beta", "new_content": "BETA_H2",
        }],
    })

    results = iterate_report(_report(h1, h2), product)

    assert results[0].error is None and results[0].applied_edits[0].after_content == "BETA_H1"
    assert results[1].error is None and results[1].applied_edits[0].after_content == "BETA_H2"


# ---------- Edge cases ----------


def test_iterate_empty_report_returns_empty_list(tmp_path: Path):
    product = _make_product(tmp_path)
    results = iterate_report("# A report with no hypothesis headers\n", product)
    assert results == []


def test_iterate_dry_run_pass_through_does_not_write(tmp_path: Path):
    product = _make_product(tmp_path)
    pre = _sha_tree(product)
    h1 = ("real edit (Layer 3)", {
        "applyable": True,
        "edits": [{
            "file": "README.md", "action": "insert_after",
            "at_line": 1, "new_content": "INSERTED",
        }],
    })

    results = iterate_report(_report(h1), product, dry_run=True)

    assert results[0].error is None
    assert len(results[0].applied_edits) == 1
    # No mutation in dry_run mode.
    assert _sha_tree(product) == pre


def test_iterate_reads_from_path(tmp_path: Path):
    product = _make_product(tmp_path)
    report_path = tmp_path / "diag.md"
    h1 = ("real edit (Layer 3)", {
        "applyable": True,
        "edits": [{
            "file": "README.md", "action": "insert_after",
            "at_line": 1, "new_content": "X",
        }],
    })
    report_path.write_text(_report(h1))

    results = iterate_report(report_path, product)
    assert len(results) == 1 and results[0].applied_edits
