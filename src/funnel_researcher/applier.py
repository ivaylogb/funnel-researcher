"""Apply structured edits from a funnel-researcher diagnosis to product artifacts.

A diagnosis report (Phase 1 output) contains one or more hypotheses, each with
a fenced ```json block describing either a list of mechanical edits or an
explicit `applyable: false` opt-out. This module:

1. Parses the report and extracts the spec for a chosen hypothesis.
2. Resolves every edit's `file` reference against the product directory,
   including the virtual names "error catalog" and "openapi" that the prompt
   assembler uses to label those artifacts.
3. Validates every `expected_content` against the live file verbatim.
4. Snapshots every file that will be touched before mutating; restores all
   snapshots on any failure during validation or writing.
5. Returns per-edit before/after detail for the delta report.

Discipline:
- No `expected_content` mismatch → no writes. The applier refuses to operate
  on a partially-stale spec.
- Overlapping edits within a single file are an error, not silently merged.
- Edits address line numbers in the *original* file. The implementation builds
  a per-original-line plan and emits the post-edit text in one pass, so line
  shifts from earlier edits do not corrupt later ones.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Optional


# ---------- Exceptions ----------


class ApplyError(Exception):
    """Base class for funnel-researcher apply errors."""


class ExpectedContentMismatch(ApplyError):
    """An edit's `expected_content` did not match the live file at the cited range."""


class UnknownAction(ApplyError):
    """An edit's `action` is not one of the four supported actions."""


class OverlappingEdits(ApplyError):
    """Two edits in the same file claim overlapping or duplicate line ranges."""


class NonApplyable(ApplyError):
    """The chosen hypothesis declared `applyable: false`."""


# ---------- Data shapes ----------


@dataclass
class Edit:
    """One mechanical edit. Field meaning depends on `action`."""

    action: str  # "replace" | "insert_after" | "delete" | "move"
    file: str
    from_line_start: Optional[int] = None
    from_line_end: Optional[int] = None
    at_line: Optional[int] = None
    to_line: Optional[int] = None
    expected_content: Optional[str] = None
    new_content: Optional[str] = None


@dataclass
class EditSpec:
    """A hypothesis's structured edit spec — applyable or not."""

    applyable: bool
    edits: list[Edit] = field(default_factory=list)
    reason: Optional[str] = None  # only set when applyable is False


@dataclass
class AppliedEdit:
    """One edit's before/after state, for the delta report."""

    edit: Edit
    file_path: Path           # resolved real path under product_dir
    line_range: str           # e.g. "21-32", "44", "(insert after 44)"
    before_content: str       # original snippet (empty for insert_after)
    after_content: str        # new snippet (empty for delete)
    file_before_sha256: str = ""
    file_after_sha256: str = ""


# ---------- Parsing the hypothesis report ----------


_HYPOTHESIS_HEADER_RE = re.compile(
    r"^###\s+Hypothesis\s+(\d+)\b.*$", re.MULTILINE | re.IGNORECASE
)
_JSON_FENCE_RE = re.compile(r"```json\s*\n(.*?)\n```", re.DOTALL)


def parse_hypothesis_edits(
    report: str | Path,
    hypothesis_id: str | int,
) -> EditSpec:
    """Extract the structured edit spec for one hypothesis from a diagnosis report.

    Args:
        report: either the report markdown as a string, or a Path to the file.
        hypothesis_id: int (1, 2, 3), str "1", or str "H1" / "h1".

    Returns:
        EditSpec. If the hypothesis declares `applyable: false`, the spec
        carries that flag and the supplied reason — the caller decides what
        to do with it.

    Raises:
        FileNotFoundError: report is a Path and does not exist.
        ValueError: hypothesis not found, no JSON block, malformed JSON, or
            invalid edit shape.
    """
    if isinstance(report, Path):
        if not report.is_file():
            raise FileNotFoundError(f"Hypothesis report not found: {report}")
        text = report.read_text()
    else:
        text = report

    hid = _coerce_hypothesis_id(hypothesis_id)
    section = _extract_hypothesis_section(text, hid)
    json_blob = _extract_first_json_block(section, hid)
    return _parse_edit_spec(json_blob, hid)


def _coerce_hypothesis_id(hid: str | int) -> int:
    if isinstance(hid, int):
        return hid
    if isinstance(hid, str):
        s = hid.strip()
        if s.lower().startswith("h"):
            s = s[1:]
        try:
            return int(s)
        except ValueError as e:
            raise ValueError(
                f"Invalid hypothesis id {hid!r}. Expected an int or 'H<int>'."
            ) from e
    raise ValueError(f"Invalid hypothesis id {hid!r}. Expected int or str.")


def _extract_hypothesis_section(text: str, hypothesis_id: int) -> str:
    """Slice the report down to one hypothesis's content.

    The section starts at "### Hypothesis N:" and ends at the next "###" or
    "##" header, whichever comes first.
    """
    matches = list(_HYPOTHESIS_HEADER_RE.finditer(text))
    if not matches:
        raise ValueError(
            "Report contains no '### Hypothesis N:' headers — does not look "
            "like a funnel-researcher diagnosis report."
        )

    target = next((m for m in matches if int(m.group(1)) == hypothesis_id), None)
    if target is None:
        available = [int(m.group(1)) for m in matches]
        raise ValueError(
            f"Hypothesis {hypothesis_id} not found in report. "
            f"Available hypothesis IDs: {available}"
        )

    after = text[target.end():]
    next_h3 = re.search(r"^###\s+", after, re.MULTILINE)
    next_h2 = re.search(r"^##\s+", after, re.MULTILINE)

    candidates = [m.start() for m in (next_h3, next_h2) if m is not None]
    end_offset = min(candidates) if candidates else len(after)
    return text[target.start():target.end() + end_offset]


def _extract_first_json_block(section: str, hypothesis_id: int) -> str:
    match = _JSON_FENCE_RE.search(section)
    if match is None:
        raise ValueError(
            f"Hypothesis {hypothesis_id} has no fenced ```json block — "
            "the report may predate the structured-edit retrofit."
        )
    return match.group(1)


def _parse_edit_spec(json_blob: str, hypothesis_id: int) -> EditSpec:
    try:
        data = json.loads(json_blob)
    except json.JSONDecodeError as e:
        raise ValueError(
            f"Hypothesis {hypothesis_id}'s structured block is not valid JSON: {e}"
        ) from e

    if not isinstance(data, dict):
        raise ValueError(
            f"Hypothesis {hypothesis_id}'s structured block must be a JSON object, "
            f"got {type(data).__name__}."
        )

    if "applyable" not in data:
        raise ValueError(
            f"Hypothesis {hypothesis_id}'s structured block is missing the "
            "'applyable' field."
        )

    if data["applyable"] is False:
        return EditSpec(
            applyable=False,
            reason=str(data.get("reason", "(no reason given)")),
        )

    if data["applyable"] is not True:
        raise ValueError(
            f"Hypothesis {hypothesis_id}'s 'applyable' field must be true or false."
        )

    raw_edits = data.get("edits")
    if not isinstance(raw_edits, list) or not raw_edits:
        raise ValueError(
            f"Hypothesis {hypothesis_id} declares applyable:true but has no "
            "non-empty 'edits' list."
        )

    edits = [_parse_one_edit(e, hypothesis_id, i) for i, e in enumerate(raw_edits)]
    return EditSpec(applyable=True, edits=edits)


_REQUIRED_FIELDS_BY_ACTION: dict[str, tuple[str, ...]] = {
    "replace": ("file", "from_line_start", "from_line_end", "expected_content", "new_content"),
    "insert_after": ("file", "at_line", "new_content"),
    "delete": ("file", "from_line_start", "from_line_end", "expected_content"),
    "move": ("file", "from_line_start", "from_line_end", "to_line", "expected_content"),
}


def _parse_one_edit(raw: Any, hypothesis_id: int, index: int) -> Edit:
    if not isinstance(raw, dict):
        raise ValueError(
            f"Hypothesis {hypothesis_id} edit #{index}: must be a JSON object."
        )
    action = raw.get("action")
    if action not in _REQUIRED_FIELDS_BY_ACTION:
        raise UnknownAction(
            f"Hypothesis {hypothesis_id} edit #{index}: unknown action {action!r}. "
            f"Expected one of {sorted(_REQUIRED_FIELDS_BY_ACTION)}."
        )

    missing = [f for f in _REQUIRED_FIELDS_BY_ACTION[action] if f not in raw]
    if missing:
        raise ValueError(
            f"Hypothesis {hypothesis_id} edit #{index} (action={action}): "
            f"missing required field(s) {missing}."
        )

    return Edit(
        action=action,
        file=str(raw["file"]),
        from_line_start=raw.get("from_line_start"),
        from_line_end=raw.get("from_line_end"),
        at_line=raw.get("at_line"),
        to_line=raw.get("to_line"),
        expected_content=raw.get("expected_content"),
        new_content=raw.get("new_content"),
    )


# ---------- File resolution ----------


_ERROR_CATALOG_CANDIDATES = (
    "docs/errors.md",
    "errors/error_catalog.yaml",
    "errors.yaml",
)
_OPENAPI_CANDIDATES = (
    "openapi.yaml",
    "openapi.json",
    "openapi/openapi.yaml",
)


def _build_resolver(product_dir: Path) -> Callable[[str], Path]:
    """Return a function that maps an edit's `file` field to a real path.

    Resolution order:
    1. Literal path under product_dir (the common case for real artifact paths).
    2. Virtual name "error catalog" → docs/errors.md / errors/error_catalog.yaml /
       errors.yaml (whichever exists; same precedence as product_reader).
    3. Virtual name "openapi" → openapi.yaml / openapi.json / openapi/openapi.yaml.
    4. Bare basename → unique recursive match under product_dir.
    """

    def resolve(name: str) -> Path:
        direct = product_dir / name
        if direct.is_file():
            return direct

        lowered = name.strip().lower()
        if lowered == "error catalog":
            for rel in _ERROR_CATALOG_CANDIDATES:
                candidate = product_dir / rel
                if candidate.is_file():
                    return candidate
            raise FileNotFoundError(
                f"Edit references the virtual name 'error catalog', but no error "
                f"catalog file exists under {product_dir} "
                f"(looked for: {list(_ERROR_CATALOG_CANDIDATES)})."
            )

        if lowered == "openapi":
            for rel in _OPENAPI_CANDIDATES:
                candidate = product_dir / rel
                if candidate.is_file():
                    return candidate
            raise FileNotFoundError(
                f"Edit references the virtual name 'openapi', but no OpenAPI "
                f"file exists under {product_dir} "
                f"(looked for: {list(_OPENAPI_CANDIDATES)})."
            )

        candidates = [p for p in product_dir.rglob(name) if p.is_file()]
        if len(candidates) == 1:
            return candidates[0]
        if not candidates:
            raise FileNotFoundError(
                f"Edit references file {name!r}, but no such file exists under "
                f"{product_dir}."
            )
        raise FileNotFoundError(
            f"Edit references file {name!r}, which is ambiguous under {product_dir}. "
            f"Candidates: {[str(p.relative_to(product_dir)) for p in candidates]}. "
            "Qualify the path."
        )

    return resolve


# ---------- Applying edits ----------


def apply_edits(
    spec: EditSpec,
    product_dir: Path,
    *,
    dry_run: bool = False,
) -> list[AppliedEdit]:
    """Apply a hypothesis's edits to files inside `product_dir`.

    Discipline:
    - Snapshots every file before any write.
    - Validates every `expected_content` against the original.
    - Computes the post-edit text per file with a per-line plan that handles
      replace, delete, insert_after, and move against the *original* line
      numbering — line shifts from earlier edits do not corrupt later ones.
    - If anything raises during validation or writing, restores every snapshot
      and re-raises.

    Args:
        spec: parsed EditSpec. Must be applyable; raises NonApplyable otherwise.
        product_dir: root of the product artifact directory.
        dry_run: if True, run all validation and compute new text but write
            nothing.

    Returns:
        One AppliedEdit per edit, in spec.edits order. The before/after
        content fields contain the snippet relevant to that edit (not the
        whole file); the file-level hashes are recorded for the delta report.

    Raises:
        NonApplyable, ExpectedContentMismatch, UnknownAction, OverlappingEdits,
        FileNotFoundError, ValueError.
    """
    if not spec.applyable:
        raise NonApplyable(
            f"Cannot apply a non-applyable hypothesis (reason: {spec.reason})."
        )

    product_dir = Path(product_dir)
    if not product_dir.is_dir():
        raise FileNotFoundError(f"Product directory not found: {product_dir}")

    resolver = _build_resolver(product_dir)

    # Resolve all paths up front so we fail fast on missing files.
    resolved_by_edit: list[Path] = [resolver(e.file) for e in spec.edits]

    # Group by file for per-file plan construction.
    by_file: dict[Path, list[tuple[int, Edit]]] = {}
    for index, (edit, path) in enumerate(zip(spec.edits, resolved_by_edit)):
        by_file.setdefault(path, []).append((index, edit))

    # Snapshot every file before any mutation.
    snapshots: dict[Path, str] = {path: path.read_text() for path in by_file}

    try:
        applied: list[Optional[AppliedEdit]] = [None] * len(spec.edits)
        new_contents: dict[Path, str] = {}

        for path, indexed_edits in by_file.items():
            original = snapshots[path]
            edits_only = [e for _, e in indexed_edits]
            new_text, per_edit = _apply_edits_to_text(original, edits_only, path)
            new_contents[path] = new_text
            for (original_index, _), entry in zip(indexed_edits, per_edit):
                applied[original_index] = entry

        # Write phase — atomic per file. If a write fails partway, the outer
        # except restores every snapshot.
        if not dry_run:
            for path, new_text in new_contents.items():
                if snapshots[path] != new_text:
                    path.write_text(new_text)

        # Fill in file-level hashes.
        for entry in applied:
            assert entry is not None  # all positions populated by construction
            entry.file_before_sha256 = _sha256(snapshots[entry.file_path])
            entry.file_after_sha256 = _sha256(new_contents[entry.file_path])

        return [a for a in applied if a is not None]
    except Exception:
        _restore_snapshots(snapshots)
        raise


def _restore_snapshots(snapshots: dict[Path, str]) -> None:
    for path, content in snapshots.items():
        try:
            if path.read_text() != content:
                path.write_text(content)
        except OSError:
            # Best effort: if a file disappeared, recreate it.
            path.write_text(content)


# ---------- Per-file plan ----------


def _apply_edits_to_text(
    original_text: str,
    edits: list[Edit],
    path: Path,
) -> tuple[str, list[AppliedEdit]]:
    """Compute the post-edit text for one file and the per-edit AppliedEdit list."""
    original_lines = original_text.splitlines()
    n = len(original_lines)
    had_trailing_newline = original_text.endswith("\n") or original_text == ""

    drop = [False] * n
    drop_claimed_by: list[Optional[int]] = [None] * n
    emit_after: list[list[str]] = [[] for _ in range(n)]
    emit_at_top: list[str] = []
    insert_after_edits: list[tuple[int, int]] = []  # (edit_index, at_line)

    per_edit: list[AppliedEdit] = []

    for index, edit in enumerate(edits):
        if edit.action == "replace":
            _check_range(edit, n, index)
            _check_expected(edit, original_lines, index, path)
            for i in range(edit.from_line_start, edit.from_line_end + 1):
                _claim_drop(drop, drop_claimed_by, i, index)
            _record_insert_before(
                edit.from_line_start, edit.new_content,
                emit_after, emit_at_top, index,
            )
            per_edit.append(AppliedEdit(
                edit=edit,
                file_path=path,
                line_range=f"{edit.from_line_start}-{edit.from_line_end}",
                before_content=_slice(original_lines, edit.from_line_start, edit.from_line_end),
                after_content=edit.new_content or "",
            ))

        elif edit.action == "delete":
            _check_range(edit, n, index)
            _check_expected(edit, original_lines, index, path)
            for i in range(edit.from_line_start, edit.from_line_end + 1):
                _claim_drop(drop, drop_claimed_by, i, index)
            per_edit.append(AppliedEdit(
                edit=edit,
                file_path=path,
                line_range=f"{edit.from_line_start}-{edit.from_line_end}",
                before_content=_slice(original_lines, edit.from_line_start, edit.from_line_end),
                after_content="",
            ))

        elif edit.action == "insert_after":
            if edit.at_line is None or not (1 <= edit.at_line <= n):
                raise ValueError(
                    f"Edit #{index} (insert_after) on {path}: at_line={edit.at_line} "
                    f"out of range 1..{n}."
                )
            emit_after[edit.at_line - 1].append(edit.new_content or "")
            insert_after_edits.append((index, edit.at_line))
            per_edit.append(AppliedEdit(
                edit=edit,
                file_path=path,
                line_range=f"(insert after {edit.at_line})",
                before_content="",
                after_content=edit.new_content or "",
            ))

        elif edit.action == "move":
            _check_range(edit, n, index)
            _check_expected(edit, original_lines, index, path)
            if edit.to_line is None or not (1 <= edit.to_line <= n):
                raise ValueError(
                    f"Edit #{index} (move) on {path}: to_line={edit.to_line} "
                    f"out of range 1..{n}."
                )
            if edit.from_line_start <= edit.to_line <= edit.from_line_end:
                raise ValueError(
                    f"Edit #{index} (move) on {path}: to_line={edit.to_line} falls "
                    f"inside the source range [{edit.from_line_start}..{edit.from_line_end}]."
                )
            captured = _slice(original_lines, edit.from_line_start, edit.from_line_end)
            for i in range(edit.from_line_start, edit.from_line_end + 1):
                _claim_drop(drop, drop_claimed_by, i, index)
            emit_after[edit.to_line - 1].append(captured)
            insert_after_edits.append((index, edit.to_line))
            per_edit.append(AppliedEdit(
                edit=edit,
                file_path=path,
                line_range=f"{edit.from_line_start}-{edit.from_line_end} → after {edit.to_line}",
                before_content=captured,
                after_content=captured,
            ))

        else:
            raise UnknownAction(
                f"Edit #{index} on {path}: unknown action {edit.action!r}."
            )

    # Post-pass: every insert_after's anchor line must still exist in the output.
    # If another edit dropped that line, the insertion would have no anchor and
    # would float untethered into a range the operator already removed.
    for ins_index, at_line in insert_after_edits:
        if drop[at_line - 1]:
            conflicting = drop_claimed_by[at_line - 1]
            raise OverlappingEdits(
                f"Edit #{ins_index} (insert/move targeting line {at_line}) anchors "
                f"on a line that edit #{conflicting} drops — the insertion would "
                "have no anchor in the post-edit output."
            )

    # Compose final text from the plan.
    result_lines: list[str] = []
    for chunk in emit_at_top:
        result_lines.extend(chunk.split("\n"))
    for i in range(n):
        if not drop[i]:
            result_lines.append(original_lines[i])
        for chunk in emit_after[i]:
            result_lines.extend(chunk.split("\n"))

    new_text = "\n".join(result_lines)
    if had_trailing_newline and not new_text.endswith("\n"):
        new_text += "\n"
    return new_text, per_edit


def _check_range(edit: Edit, n: int, index: int) -> None:
    if edit.from_line_start is None or edit.from_line_end is None:
        raise ValueError(f"Edit #{index} ({edit.action}): line range is missing.")
    if edit.from_line_start < 1 or edit.from_line_end > n:
        raise ValueError(
            f"Edit #{index} ({edit.action}): line range "
            f"[{edit.from_line_start}..{edit.from_line_end}] out of file bounds 1..{n}."
        )
    if edit.from_line_start > edit.from_line_end:
        raise ValueError(
            f"Edit #{index} ({edit.action}): from_line_start "
            f"({edit.from_line_start}) > from_line_end ({edit.from_line_end})."
        )


def _check_expected(edit: Edit, original_lines: list[str], index: int, path: Path) -> None:
    actual = _slice(original_lines, edit.from_line_start, edit.from_line_end)
    expected = edit.expected_content or ""
    if actual != expected:
        raise ExpectedContentMismatch(
            f"Edit #{index} ({edit.action}) on {path}: expected_content does not "
            f"match lines {edit.from_line_start}..{edit.from_line_end}.\n"
            f"--- expected ---\n{expected!r}\n"
            f"--- actual ---\n{actual!r}"
        )


def _claim_drop(
    drop: list[bool],
    drop_claimed_by: list[Optional[int]],
    one_indexed_line: int,
    edit_index: int,
) -> None:
    i = one_indexed_line - 1
    if drop[i]:
        raise OverlappingEdits(
            f"Edit #{edit_index} overlaps a prior edit at line {one_indexed_line} "
            "— two edits cannot delete, replace, or move the same line."
        )
    drop[i] = True
    drop_claimed_by[i] = edit_index


def _record_insert_before(
    one_indexed_line: int,
    new_content: Optional[str],
    emit_after: list[list[str]],
    emit_at_top: list[str],
    edit_index: int,
) -> None:
    if new_content is None:
        raise ValueError(f"Edit #{edit_index}: new_content is required but missing.")
    if one_indexed_line == 1:
        emit_at_top.append(new_content)
    else:
        emit_after[one_indexed_line - 2].append(new_content)


def _slice(original_lines: list[str], start: int, end: int) -> str:
    """1-indexed inclusive slice → joined string."""
    return "\n".join(original_lines[start - 1:end])


def _sha256(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()
