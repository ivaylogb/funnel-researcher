"""CLI entry point for funnel-researcher.

Phase 1 ships the `diagnose` subcommand. `apply` and `iterate` follow the
same pattern as agent-researcher and will be added once `diagnose`'s
hypothesis quality is the gated bar.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

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

    args = parser.parse_args(argv)

    if args.command == "diagnose":
        return _run_diagnose(args)

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


if __name__ == "__main__":
    sys.exit(main())
