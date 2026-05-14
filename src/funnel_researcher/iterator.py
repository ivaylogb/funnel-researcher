"""Iterate over every hypothesis in a diagnose report against one product.

The flow per hypothesis:

1. Parse the hypothesis's structured edit spec via the applier.
2. If `applyable: false`, record the skip reason and move on.
3. Snapshot every file the edits will touch.
4. Apply the edits via the applier. Capture the AppliedEdit list (the delta
   artifact). Errors during apply (ExpectedContentMismatch, OverlappingEdits,
   etc.) are caught and recorded on the per-hypothesis result — iteration
   continues to the next hypothesis.
5. Restore the snapshot. The product directory returns to its pre-iterate
   state before the next hypothesis is processed.

Best-effort by design: one failing hypothesis does not abort the run. The
operator gets a comparison report covering every hypothesis the diagnose
report proposed.

There is no eval re-run in v1. The comparison report is a mechanical diff;
the operator decides which (if any) hypothesis to ship.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from .applier import (
    AppliedEdit,
    ApplyError,
    EditSpec,
    _build_resolver,
    apply_edits,
    parse_hypothesis_edits,
)


@dataclass
class IterationResult:
    """One hypothesis's outcome from iterate_report.

    Exactly one of `skip_reason`, `error`, or `applied_edits` (non-empty) is
    populated for any given result, depending on the path through the flow.
    """

    hypothesis_id: int
    title: str
    layer: Optional[str]
    applyable: bool
    skip_reason: Optional[str] = None
    applied_edits: list[AppliedEdit] = field(default_factory=list)
    error: Optional[str] = None


_HEADER_RE = re.compile(
    r"^###\s+Hypothesis\s+(\d+)\s*:?\s*(.*)$",
    re.MULTILINE | re.IGNORECASE,
)
_LAYER_RE = re.compile(r"\(Layer\s+(\d+)[^)]*\)", re.IGNORECASE)


def iterate_report(
    report: str | Path,
    product_dir: Path,
    *,
    dry_run: bool = False,
) -> list[IterationResult]:
    """Process every hypothesis in `report` against `product_dir`.

    Args:
        report: report markdown as string, or Path to the file.
        product_dir: root of the product artifact directory.
        dry_run: passed through to apply_edits. When True, the applier
            validates and computes deltas without writing. When False, the
            applier writes files but iterate restores the snapshot afterward
            — the on-disk end state is the same either way.

    Returns:
        A list of IterationResult, one per `### Hypothesis N:` header found
        in the report, in report order.

    Raises:
        FileNotFoundError: report or product_dir does not exist.
    """
    if isinstance(report, Path):
        if not report.is_file():
            raise FileNotFoundError(f"Hypothesis report not found: {report}")
        text = report.read_text()
    else:
        text = report

    product_dir = Path(product_dir)
    if not product_dir.is_dir():
        raise FileNotFoundError(f"Product directory not found: {product_dir}")

    headers = _enumerate_headers(text)
    return [
        _process_hypothesis(text, hid, title, layer, product_dir, dry_run)
        for hid, title, layer in headers
    ]


def _enumerate_headers(text: str) -> list[tuple[int, str, Optional[str]]]:
    """Find every `### Hypothesis N:` header and extract id, title, layer."""
    out: list[tuple[int, str, Optional[str]]] = []
    for match in _HEADER_RE.finditer(text):
        hid = int(match.group(1))
        title = match.group(2).strip()
        layer_m = _LAYER_RE.search(title)
        layer = f"Layer {layer_m.group(1)}" if layer_m else None
        out.append((hid, title, layer))
    return out


def _process_hypothesis(
    text: str,
    hid: int,
    title: str,
    layer: Optional[str],
    product_dir: Path,
    dry_run: bool,
) -> IterationResult:
    try:
        spec = parse_hypothesis_edits(text, hid)
    except (ValueError, FileNotFoundError) as e:
        return IterationResult(
            hypothesis_id=hid, title=title, layer=layer,
            applyable=False, error=f"parse failed: {e}",
        )

    if not spec.applyable:
        return IterationResult(
            hypothesis_id=hid, title=title, layer=layer,
            applyable=False, skip_reason=spec.reason,
        )

    snapshot = _snapshot_for_spec(spec, product_dir)
    try:
        applied = apply_edits(spec, product_dir, dry_run=dry_run)
    except (ApplyError, FileNotFoundError, ValueError) as e:
        _restore(snapshot)
        return IterationResult(
            hypothesis_id=hid, title=title, layer=layer,
            applyable=True, error=str(e),
        )

    _restore(snapshot)
    return IterationResult(
        hypothesis_id=hid, title=title, layer=layer,
        applyable=True, applied_edits=applied,
    )


def _snapshot_for_spec(spec: EditSpec, product_dir: Path) -> dict[Path, str]:
    """Read every file the spec's edits will touch into an in-memory snapshot.

    Unresolvable file references are skipped; apply_edits will surface those
    via FileNotFoundError, which we record on the IterationResult.
    """
    resolver = _build_resolver(product_dir)
    paths: set[Path] = set()
    for edit in spec.edits:
        try:
            paths.add(resolver(edit.file))
        except FileNotFoundError:
            continue
    return {p: p.read_text() for p in paths}


def _restore(snapshot: dict[Path, str]) -> None:
    for path, content in snapshot.items():
        try:
            current = path.read_text()
        except OSError:
            current = None
        if current != content:
            path.write_text(content)
