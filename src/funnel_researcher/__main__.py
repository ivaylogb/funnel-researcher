"""CLI entry point for funnel-researcher.

Phase 1 shipped the `diagnose` subcommand. Phase 2 adds `apply`, which
takes a hypothesis report + ID, validates and applies the structured edits
mechanically, and writes a delta report. `iterate` follows in Phase 3.
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

from .applier import ApplyError, apply_edits, parse_hypothesis_edits
from .delta import render_delta
from .hypothesis_agent import DEFAULT_MAX_TOKENS, DEFAULT_MODEL, generate_hypotheses
from .loaders import load_dropoff, load_funnel
from .product_reader import read_product


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="funnel-researcher",
        description="Structured failure-diagnosis for developer-API activation funnels.",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    diagnose = subparsers.add_parser(
        "diagnose",
        help="Generate a hypothesis report explaining why developers drop off at a funnel step.",
    )
    diagnose.add_argument(
        "--funnel",
        required=True,
        type=Path,
        help="Path to the funnel definition YAML.",
    )
    diagnose.add_argument(
        "--dropoff",
        required=True,
        type=Path,
        help="Path to the dropoff data JSON.",
    )
    diagnose.add_argument(
        "--product",
        required=True,
        type=Path,
        help="Path to the product artifact directory (containing docs/, sdk/, errors).",
    )
    diagnose.add_argument(
        "--output-file",
        required=True,
        type=Path,
        help="Where to write the hypothesis report (markdown).",
    )
    diagnose.add_argument(
        "--model",
        default=DEFAULT_MODEL,
        help=f"Model to use (default: {DEFAULT_MODEL}).",
    )
    diagnose.add_argument(
        "--max-tokens",
        default=DEFAULT_MAX_TOKENS,
        type=int,
        help=f"Max output tokens (default: {DEFAULT_MAX_TOKENS}).",
    )
    diagnose.add_argument(
        "--extra-file",
        action="append",
        type=Path,
        default=[],
        help="Optional extra artifact file to include (relative or absolute path). Can be passed multiple times.",
    )

    apply_cmd = subparsers.add_parser(
        "apply",
        help="Apply the structured edits from one hypothesis in a diagnosis report.",
    )
    apply_cmd.add_argument(
        "--hypothesis-report",
        required=True,
        type=Path,
        help="Path to the markdown diagnosis report produced by `diagnose`.",
    )
    apply_cmd.add_argument(
        "--hypothesis-id",
        required=True,
        type=str,
        help='Which hypothesis to apply, e.g. "H1" or "1".',
    )
    apply_cmd.add_argument(
        "--product",
        required=True,
        type=Path,
        help="Path to the product artifact directory the edits target.",
    )
    apply_cmd.add_argument(
        "--output-file",
        required=True,
        type=Path,
        help="Where to write the markdown delta report.",
    )
    apply_cmd.add_argument(
        "--dry-run",
        action="store_true",
        help="Validate and render the delta report without writing changes to product files.",
    )

    args = parser.parse_args(argv)

    if args.command == "diagnose":
        return _run_diagnose(args)
    if args.command == "apply":
        return _run_apply(args)

    parser.error(f"Unknown command: {args.command}")
    return 2


def _run_diagnose(args) -> int:
    funnel_path: Path = args.funnel
    dropoff_path: Path = args.dropoff
    product_dir: Path = args.product
    output_path: Path = args.output_file

    if not funnel_path.is_file():
        print(f"funnel definition not found: {funnel_path}", file=sys.stderr)
        return 2
    if not dropoff_path.is_file():
        print(f"dropoff data not found: {dropoff_path}", file=sys.stderr)
        return 2
    if not product_dir.is_dir():
        print(f"product directory not found: {product_dir}", file=sys.stderr)
        return 2

    funnel = load_funnel(funnel_path)
    dropoff = load_dropoff(dropoff_path)
    artifacts = read_product(product_dir, extra_files=args.extra_file)

    try:
        report = generate_hypotheses(
            funnel=funnel,
            dropoff=dropoff,
            artifacts=artifacts,
            model=args.model,
            max_tokens=args.max_tokens,
        )
    except RuntimeError as e:
        print(f"diagnose failed: {e}", file=sys.stderr)
        return 3

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(report.markdown)
    print(report.markdown)
    print(
        f"\n[wrote report to {output_path}]\n"
        f"[input_tokens={report.input_tokens}, output_tokens={report.output_tokens}]"
    )
    return 0


def _run_apply(args) -> int:
    report_path: Path = args.hypothesis_report
    hypothesis_id: str = args.hypothesis_id
    product_dir: Path = args.product
    output_path: Path = args.output_file
    dry_run: bool = args.dry_run

    if not report_path.is_file():
        print(f"hypothesis report not found: {report_path}", file=sys.stderr)
        return 2
    if not product_dir.is_dir():
        print(f"product directory not found: {product_dir}", file=sys.stderr)
        return 2

    try:
        spec = parse_hypothesis_edits(report_path, hypothesis_id)
    except (ValueError, FileNotFoundError) as e:
        print(f"apply failed: {e}", file=sys.stderr)
        return 3

    if not spec.applyable:
        print(
            f"hypothesis {hypothesis_id} is not applyable: {spec.reason}",
            file=sys.stderr,
        )
        return 4

    try:
        applied = apply_edits(spec, product_dir, dry_run=dry_run)
    except ApplyError as e:
        print(f"apply failed: {e}", file=sys.stderr)
        return 3
    except (FileNotFoundError, ValueError) as e:
        print(f"apply failed: {e}", file=sys.stderr)
        return 3

    summary = _hypothesis_summary(report_path, hypothesis_id)
    delta_md = render_delta(applied, summary, product_dir=product_dir, dry_run=dry_run)

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(delta_md)

    n_files = len({a.file_path for a in applied})
    suffix = " (dry run, product files unchanged)" if dry_run else ""
    print(
        f"[apply: hypothesis {hypothesis_id}, {len(applied)} edit(s) across "
        f"{n_files} file(s){suffix}; delta report → {output_path}]"
    )
    return 0


_TITLE_RE = re.compile(r"^###\s+Hypothesis\s+(\d+)\s*:?\s*(.*)$", re.MULTILINE | re.IGNORECASE)


def _hypothesis_summary(report_path: Path, hypothesis_id: str) -> str:
    """Build the one-paragraph summary the delta report prints at the top.

    Pulls the matching `### Hypothesis N:` title line out of the report so the
    delta is self-describing. Falls back to a minimal placeholder if the title
    cannot be located.
    """
    try:
        wanted = int(hypothesis_id.lstrip("Hh")) if isinstance(hypothesis_id, str) else int(hypothesis_id)
    except ValueError:
        wanted = None

    text = report_path.read_text()
    for match in _TITLE_RE.finditer(text):
        if wanted is None or int(match.group(1)) == wanted:
            return f"Hypothesis {match.group(1)}: {match.group(2).strip()}"
    return f"Hypothesis {hypothesis_id} from {report_path}"


if __name__ == "__main__":
    sys.exit(main())
