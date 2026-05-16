"""Reader for the product artifacts (docs, SDK source, error catalog, openapi).

Walks a product directory and pulls the files the model needs to see.
The expected layout is conventional but flexible:

    product/
      README.md
      docs/*.md
      sdk/**/*.py  (or .ts, .js, etc.)
      docs/errors.md  (or errors/error_catalog.yaml — both supported)
      openapi.yaml  (optional)

Files outside these conventions are not loaded. Anything unconventional
should be explicitly named via --extra-file at the CLI.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path


SUPPORTED_SDK_EXTENSIONS = {".py", ".ts", ".js", ".tsx", ".jsx", ".rb", ".go", ".java"}

# Text-like extensions ingested when a file sits at the product root.
TOP_LEVEL_TEXT_EXTENSIONS = {
    ".md", ".markdown", ".rst", ".txt", ".yaml", ".yml", ".json",
}

# Top-level files owned by a dedicated ProductArtifacts field. The generic
# root scan skips these so they are not ingested twice: README is `readme`,
# openapi.* is `openapi`, and errors.yaml is an `error_catalog` candidate.
_TOP_LEVEL_RESERVED = {"README.md", "openapi.yaml", "openapi.json", "errors.yaml"}


def _is_ingestable_top_level(path: Path) -> bool:
    """True for a root-level product file that should join the doc surface.

    Generic by extension, not by a fixed name list. Hidden files, backups,
    and compiled artifacts are excluded — none of those forms carry an
    extension in TOP_LEVEL_TEXT_EXTENSIONS (e.g. `.foo`, `errors.md.bak`,
    `errors.md~`, `*.pyc` all fail the suffix check). Files already owned by
    a dedicated field are skipped.
    """
    if not path.is_file():
        return False
    if path.name.startswith("."):
        return False
    if path.name in _TOP_LEVEL_RESERVED:
        return False
    return path.suffix.lower() in TOP_LEVEL_TEXT_EXTENSIONS


@dataclass
class ProductArtifacts:
    """Everything the model needs to read about the product."""

    name: str
    readme: str | None
    docs: dict[str, str] = field(default_factory=dict)  # path -> content
    sdk_files: dict[str, str] = field(default_factory=dict)  # path -> content
    error_catalog: str | None = None
    openapi: str | None = None
    extra_files: dict[str, str] = field(default_factory=dict)


def read_product(product_dir: Path, extra_files: list[Path] | None = None) -> ProductArtifacts:
    """Walk a product directory and assemble ProductArtifacts."""
    name = product_dir.name

    readme = _read_if_exists(product_dir / "README.md")

    docs = {}
    docs_dir = product_dir / "docs"
    if docs_dir.is_dir():
        for f in sorted(docs_dir.rglob("*.md")):
            rel = f.relative_to(product_dir).as_posix()
            docs[rel] = f.read_text()

    # Top-level documentation files (e.g. a root-level errors.md or
    # glossary.md) are part of the product surface too. Ingest them
    # generically by extension so callers don't have to know which exact
    # filenames the loader special-cases; files owned by a dedicated field
    # (README, openapi, errors.yaml) are skipped. setdefault keeps any
    # docs/ entry authoritative if names ever collide.
    for f in sorted(product_dir.iterdir()):
        if _is_ingestable_top_level(f):
            docs.setdefault(f.relative_to(product_dir).as_posix(), f.read_text())

    sdk_files = {}
    sdk_dir = product_dir / "sdk"
    if sdk_dir.is_dir():
        for f in sorted(sdk_dir.rglob("*")):
            if f.is_file() and f.suffix in SUPPORTED_SDK_EXTENSIONS:
                rel = f.relative_to(product_dir).as_posix()
                sdk_files[rel] = f.read_text()

    error_catalog = None
    error_catalog_path: Path | None = None
    for candidate in [
        product_dir / "docs" / "errors.md",
        product_dir / "errors" / "error_catalog.yaml",
        product_dir / "errors.yaml",
    ]:
        if candidate.is_file():
            error_catalog = candidate.read_text()
            error_catalog_path = candidate
            break

    # If the error catalog came from a file that the docs glob also picked up
    # (i.e. docs/errors.md), drop it from `docs` so it isn't shown to the model
    # twice with independently restarted line numbering.
    if error_catalog_path is not None:
        try:
            rel = error_catalog_path.relative_to(product_dir).as_posix()
        except ValueError:
            rel = None
        if rel:
            docs.pop(rel, None)

    openapi = None
    for candidate in [
        product_dir / "openapi.yaml",
        product_dir / "openapi.json",
        product_dir / "openapi" / "openapi.yaml",
    ]:
        if candidate.is_file():
            openapi = candidate.read_text()
            break

    extras: dict[str, str] = {}
    for path in extra_files or []:
        try:
            rel = path.relative_to(product_dir).as_posix()
        except ValueError:
            rel = path.name
        extras[rel] = path.read_text()

    return ProductArtifacts(
        name=name,
        readme=readme,
        docs=docs,
        sdk_files=sdk_files,
        error_catalog=error_catalog,
        openapi=openapi,
        extra_files=extras,
    )


def _read_if_exists(path: Path) -> str | None:
    if path.is_file():
        return path.read_text()
    return None
