"""End-to-end tests for the `funnel-researcher apply` subcommand.

Each test invokes the CLI in a subprocess so the test exercises argument
parsing, file IO, and exit codes — the same surface a real operator hits.
The product directory and diagnosis report are built per-test in tmp_path so
no test mutates a checked-in fixture.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path


def _run_cli(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, "-m", "funnel_researcher", "apply", *args],
        capture_output=True,
        text=True,
    )


def _report_with(hypotheses: list[dict]) -> str:
    parts = ["# Diagnosis\n\n## Hypotheses\n"]
    for i, blob in enumerate(hypotheses, start=1):
        parts.append(f"### Hypothesis {i}: synthetic claim (Layer 3)\n")
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


def test_apply_happy_path_writes_delta_and_modifies_file(tmp_path: Path):
    product = _make_product(tmp_path)
    report = tmp_path / "diag.md"
    report.write_text(_report_with([
        {
            "applyable": True,
            "edits": [{
                "file": "docs/quickstart.md",
                "action": "replace",
                "from_line_start": 2,
                "from_line_end": 2,
                "expected_content": "beta",
                "new_content": "BETA_NEW",
            }],
        },
    ]))
    output = tmp_path / "delta.md"

    result = _run_cli(
        "--hypothesis-report", str(report),
        "--hypothesis-id", "H1",
        "--product", str(product),
        "--output-file", str(output),
    )

    assert result.returncode == 0, f"stderr: {result.stderr}\nstdout: {result.stdout}"
    assert output.is_file()
    delta_text = output.read_text()
    assert "# Apply delta" in delta_text
    assert "docs/quickstart.md" in delta_text
    # File was actually mutated.
    assert "BETA_NEW" in (product / "docs" / "quickstart.md").read_text()
    # Success summary printed.
    assert "hypothesis H1" in result.stdout
    assert "delta report" in result.stdout


def test_apply_non_applyable_hypothesis_exits_4_with_reason(tmp_path: Path):
    product = _make_product(tmp_path)
    report = tmp_path / "diag.md"
    report.write_text(_report_with([
        {"applyable": False, "reason": "needs a cross-cutting refactor"},
    ]))
    output = tmp_path / "delta.md"

    result = _run_cli(
        "--hypothesis-report", str(report),
        "--hypothesis-id", "1",
        "--product", str(product),
        "--output-file", str(output),
    )

    assert result.returncode == 4, f"stdout: {result.stdout}\nstderr: {result.stderr}"
    assert "not applyable" in result.stderr
    assert "needs a cross-cutting refactor" in result.stderr
    assert not output.exists()
    # Product file untouched.
    assert (product / "docs" / "quickstart.md").read_text() == "alpha\nbeta\ngamma\ndelta\nepsilon\n"


def test_apply_unknown_hypothesis_id_exits_3(tmp_path: Path):
    product = _make_product(tmp_path)
    report = tmp_path / "diag.md"
    report.write_text(_report_with([
        {
            "applyable": True,
            "edits": [{
                "file": "README.md",
                "action": "insert_after",
                "at_line": 1,
                "new_content": "INSERTED",
            }],
        },
    ]))
    output = tmp_path / "delta.md"

    result = _run_cli(
        "--hypothesis-report", str(report),
        "--hypothesis-id", "H99",
        "--product", str(product),
        "--output-file", str(output),
    )

    assert result.returncode == 3, f"stdout: {result.stdout}\nstderr: {result.stderr}"
    assert "apply failed" in result.stderr
    assert "Hypothesis 99 not found" in result.stderr
    assert not output.exists()


def test_apply_dry_run_renders_delta_without_mutating_files(tmp_path: Path):
    product = _make_product(tmp_path)
    qs_path = product / "docs" / "quickstart.md"
    original = qs_path.read_text()

    report = tmp_path / "diag.md"
    report.write_text(_report_with([
        {
            "applyable": True,
            "edits": [{
                "file": "docs/quickstart.md",
                "action": "replace",
                "from_line_start": 2,
                "from_line_end": 2,
                "expected_content": "beta",
                "new_content": "BETA_NEW",
            }],
        },
    ]))
    output = tmp_path / "delta.md"

    result = _run_cli(
        "--hypothesis-report", str(report),
        "--hypothesis-id", "H1",
        "--product", str(product),
        "--output-file", str(output),
        "--dry-run",
    )

    assert result.returncode == 0, f"stderr: {result.stderr}\nstdout: {result.stdout}"
    # Delta report still written.
    assert output.is_file()
    delta_text = output.read_text()
    assert "(dry run)" in delta_text
    # Product file not modified.
    assert qs_path.read_text() == original
    assert "dry run" in result.stdout


def test_apply_missing_product_directory_exits_2(tmp_path: Path):
    report = tmp_path / "diag.md"
    report.write_text(_report_with([
        {
            "applyable": True,
            "edits": [{
                "file": "README.md",
                "action": "insert_after",
                "at_line": 1,
                "new_content": "x",
            }],
        },
    ]))
    output = tmp_path / "delta.md"

    result = _run_cli(
        "--hypothesis-report", str(report),
        "--hypothesis-id", "H1",
        "--product", str(tmp_path / "does_not_exist"),
        "--output-file", str(output),
    )

    assert result.returncode == 2, f"stdout: {result.stdout}\nstderr: {result.stderr}"
    assert "product directory not found" in result.stderr
    assert not output.exists()
