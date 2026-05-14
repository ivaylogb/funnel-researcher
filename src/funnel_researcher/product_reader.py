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
