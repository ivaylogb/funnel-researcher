"""Tests for product artifact reader."""

from __future__ import annotations

from pathlib import Path

from funnel_researcher.product_reader import read_product


def _write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content)


def test_read_product_finds_readme_and_docs(tmp_path: Path) -> None:
    product = tmp_path / "myapi"
    _write(product / "README.md", "# MyAPI\nA thing.")
    _write(product / "docs" / "quickstart.md", "# Quickstart\nSteps.")
    _write(product / "docs" / "agents.md", "# Agents\nMore steps.")

    artifacts = read_product(product)

    assert artifacts.name == "myapi"
    assert artifacts.readme == "# MyAPI\nA thing."
    assert "docs/quickstart.md" in artifacts.docs
    assert "docs/agents.md" in artifacts.docs
    assert artifacts.docs["docs/quickstart.md"] == "# Quickstart\nSteps."


def test_read_product_finds_sdk_files(tmp_path: Path) -> None:
    product = tmp_path / "myapi"
    _write(product / "sdk" / "client.py", "class Client: pass")
    _write(product / "sdk" / "agents.py", "class Agents: pass")
    _write(product / "sdk" / "ignored.txt", "not picked up")

    artifacts = read_product(product)

    assert "sdk/client.py" in artifacts.sdk_files
    assert "sdk/agents.py" in artifacts.sdk_files
    assert "sdk/ignored.txt" not in artifacts.sdk_files


def test_read_product_finds_error_catalog_in_multiple_locations(tmp_path: Path) -> None:
    # docs/errors.md
    product1 = tmp_path / "api1"
    _write(product1 / "docs" / "errors.md", "## Errors\n400 BAD")
    artifacts1 = read_product(product1)
    assert artifacts1.error_catalog == "## Errors\n400 BAD"

    # errors/error_catalog.yaml
    product2 = tmp_path / "api2"
    _write(product2 / "errors" / "error_catalog.yaml", "errors: []")
    artifacts2 = read_product(product2)
    assert artifacts2.error_catalog == "errors: []"


def test_read_product_handles_missing_directories(tmp_path: Path) -> None:
    product = tmp_path / "minimal"
    product.mkdir()
    _write(product / "README.md", "minimal")

    artifacts = read_product(product)

    assert artifacts.readme == "minimal"
    assert artifacts.docs == {}
    assert artifacts.sdk_files == {}
    assert artifacts.error_catalog is None
    assert artifacts.openapi is None


def test_read_product_accepts_extra_files(tmp_path: Path) -> None:
    product = tmp_path / "api"
    product.mkdir()
    extra = tmp_path / "elsewhere" / "weird.cfg"
    _write(extra, "key=value")

    artifacts = read_product(product, extra_files=[extra])

    # extra files outside the product dir are stored under their basename
    assert "weird.cfg" in artifacts.extra_files
    assert artifacts.extra_files["weird.cfg"] == "key=value"


def test_read_product_deduplicates_errors_md_between_docs_and_error_catalog(tmp_path: Path) -> None:
    """When docs/errors.md is promoted to error_catalog, it must not also
    remain in the docs dict — otherwise the assembled prompt shows the same
    content twice with independently restarted line numbering, which lets
    the model emit two valid-looking citations to the same content at
    different line numbers."""
    product = tmp_path / "api"
    _write(product / "docs" / "quickstart.md", "# Quickstart")
    _write(product / "docs" / "errors.md", "## Errors\n400 BAD")

    artifacts = read_product(product)

    assert artifacts.error_catalog == "## Errors\n400 BAD"
    assert "docs/errors.md" not in artifacts.docs
    # Sibling docs files are unaffected by the dedup.
    assert "docs/quickstart.md" in artifacts.docs


def test_read_product_supports_typescript_sdk(tmp_path: Path) -> None:
    product = tmp_path / "tsapi"
    _write(product / "sdk" / "client.ts", "export class Client {}")
    _write(product / "sdk" / "agents.ts", "export class Agents {}")

    artifacts = read_product(product)

    assert "sdk/client.ts" in artifacts.sdk_files
    assert "sdk/agents.ts" in artifacts.sdk_files
