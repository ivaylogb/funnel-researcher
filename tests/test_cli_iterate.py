"""End-to-end tests for the `funnel-researcher iterate` subcommand."""

from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from pathlib import Path


def _run_cli(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, "-m", "funnel_researcher", "iterate", *args],
        capture_output=True,
        text=True,
    )


def _report(*hypotheses: tuple[str, dict]) -> str:
    parts = ["# Diagnosis\n\n## Hypotheses\n"]
    for i, (title, blob) in enumerate(hypotheses, start=1):
        parts.append(f"### Hypothesis {i}: {title}\n")
        parts.append("**Claim:** placeholder.\n\n```json\n" + json.dumps(blob) + "\n```\n\n---\n")
    return "\n".join(parts)


def _make_product(root: Path) -> Path:
    product = root / "product"
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


def test_iterate_happy_path_mixed_hypotheses(tmp_path: Path):
    product = _make_product(tmp_path)
    pre = _sha_tree(product)

    report = tmp_path / "diag.md"
    report.write_text(_report(
        ("applyable one (Layer 3)", {
            "applyable": True,
            "edits": [{
                "file": "docs/quickstart.md", "action": "replace",
                "from_line_start": 2, "from_line_end": 2,
                "expected_content": "beta", "new_content": "BETA",
            }],
        }),
        ("skipped (Layer 4)", {"applyable": False, "reason": "needs design"}),
        ("applyable two (Layer 2)", {
            "applyable": True,
            "edits": [{
                "file": "README.md", "action": "insert_after",
                "at_line": 1, "new_content": "INSERTED",
            }],
        }),
    ))
    output = tmp_path / "comparison.md"

    result = _run_cli(
        "--hypothesis-report", str(report),
        "--product", str(product),
        "--output-file", str(output),
    )

    assert result.returncode == 0, f"stderr: {result.stderr}\nstdout: {result.stdout}"
    assert output.is_file()
    md = output.read_text()
    assert "# Iteration comparison" in md
    assert "Hypotheses in report: 3" in md
    assert "Applied cleanly: 2" in md
    assert "Skipped (applyable: false): 1" in md
    # CLI summary line.
    assert "3 hypothesis(es)" in result.stdout
    assert "2 applied" in result.stdout
    # Product reverted to baseline.
    assert _sha_tree(product) == pre


def test_iterate_all_applyable_false_exits_0_with_skipped_report(tmp_path: Path):
    product = _make_product(tmp_path)
    report = tmp_path / "diag.md"
    report.write_text(_report(
        ("h1 (Layer 3)", {"applyable": False, "reason": "r1"}),
        ("h2 (Layer 4)", {"applyable": False, "reason": "r2"}),
    ))
    output = tmp_path / "comparison.md"

    result = _run_cli(
        "--hypothesis-report", str(report),
        "--product", str(product),
        "--output-file", str(output),
    )

    assert result.returncode == 0, f"stderr: {result.stderr}\nstdout: {result.stdout}"
    md = output.read_text()
    assert "Applied cleanly: 0" in md
    assert "Skipped (applyable: false): 2" in md
    # Both reasons rendered.
    assert "r1" in md and "r2" in md


def test_iterate_missing_product_exits_2(tmp_path: Path):
    report = tmp_path / "diag.md"
    report.write_text(_report(
        ("h1 (Layer 3)", {"applyable": False, "reason": "r"}),
    ))
    output = tmp_path / "comparison.md"

    result = _run_cli(
        "--hypothesis-report", str(report),
        "--product", str(tmp_path / "does_not_exist"),
        "--output-file", str(output),
    )

    assert result.returncode == 2, f"stdout: {result.stdout}\nstderr: {result.stderr}"
    assert "product directory not found" in result.stderr
    assert not output.exists()


def test_iterate_empty_report_exits_5(tmp_path: Path):
    product = _make_product(tmp_path)
    report = tmp_path / "diag.md"
    report.write_text("# A diagnosis with no hypothesis headers.\n\nNothing here.\n")
    output = tmp_path / "comparison.md"

    result = _run_cli(
        "--hypothesis-report", str(report),
        "--product", str(product),
        "--output-file", str(output),
    )

    assert result.returncode == 5, f"stdout: {result.stdout}\nstderr: {result.stderr}"
    assert "no hypotheses found in report" in result.stderr
    # Comparison still written, so the operator sees an empty-but-explanatory report.
    assert output.is_file()
    assert "Hypotheses in report: 0" in output.read_text()
