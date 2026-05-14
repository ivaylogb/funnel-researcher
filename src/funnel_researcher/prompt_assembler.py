"""Assembles the user-facing prompt from funnel + dropoff + product artifacts.

Discipline from agent-researcher: every source file shown to the model is
prefixed with its 1-indexed line number, so the model can cite operator-
verifiable file:line evidence rather than fabricating coordinates.

Format: each line prefixed as "{N:4d}  {line}" — four-digit gutter,
two-space separator. Files up to 9999 lines fit.
"""

from __future__ import annotations

import json
from importlib import resources
from pathlib import Path

import yaml

from .loaders import DropoffData, FunnelDefinition
from .product_reader import ProductArtifacts


SYSTEM_PROMPT_FILE = "hypothesis_system.md"
USER_TEMPLATE_FILE = "hypothesis_user.md"


def load_system_prompt() -> str:
    """Load the methodology system prompt from the package's prompts/ directory."""
    return _load_prompt(SYSTEM_PROMPT_FILE)


def load_user_template() -> str:
    """Load the user-message template."""
    return _load_prompt(USER_TEMPLATE_FILE)


def _load_prompt(filename: str) -> str:
    # Resolve via the package's installed location.
    pkg = resources.files("funnel_researcher.prompts")
    return (pkg / filename).read_text()


def build_user_message(
    *,
    funnel: FunnelDefinition,
    dropoff: DropoffData,
    artifacts: ProductArtifacts,
) -> str:
    """Build the final user message by substituting fields into the template."""
    template = load_user_template()

    funnel_yaml = yaml.safe_dump(funnel.raw, sort_keys=False, default_flow_style=False)
    dropoff_json = json.dumps(dropoff.raw, indent=2)

    readme_content = _number_lines(artifacts.readme) if artifacts.readme else "[no README.md found]"
    docs_section = _format_files(artifacts.docs, lang="markdown") if artifacts.docs else "[no docs/ files found]"
    sdk_section = _format_files(artifacts.sdk_files, lang_by_ext=True) if artifacts.sdk_files else "[no sdk/ files found]"
    errors_section = (
        _format_single("error catalog", artifacts.error_catalog, lang="markdown")
        if artifacts.error_catalog
        else "[no error catalog found]"
    )

    additional_blocks: list[str] = []
    if artifacts.openapi:
        additional_blocks.append(_format_single("openapi", artifacts.openapi, lang="yaml"))
    if artifacts.extra_files:
        for path, content in sorted(artifacts.extra_files.items()):
            additional_blocks.append(_code_block(path, content, lang=""))

    additional_files_section = (
        "### Additional artifacts\n\n" + "\n\n".join(additional_blocks)
        if additional_blocks
        else ""
    )

    return template.format(
        funnel_yaml=funnel_yaml,
        target_dropoff_step=funnel.target_dropoff_step,
        dropoff_json=dropoff_json,
        readme_content=readme_content,
        docs_section=docs_section,
        sdk_section=sdk_section,
        errors_section=errors_section,
        additional_files_section=additional_files_section,
    )


def _format_files(files: dict[str, str], lang: str = "", lang_by_ext: bool = False) -> str:
    """Format a dict of file path -> content into labeled, numbered code blocks."""
    blocks = []
    for path in sorted(files.keys()):
        chosen_lang = lang
        if lang_by_ext:
            ext = Path(path).suffix.lstrip(".")
            chosen_lang = {"py": "python", "ts": "typescript", "js": "javascript"}.get(ext, ext)
        blocks.append(_code_block(path, files[path], lang=chosen_lang))
    return "\n\n".join(blocks)


def _format_single(label: str, content: str, lang: str = "") -> str:
    return _code_block(label, content, lang=lang)


def _code_block(label: str, content: str, lang: str = "") -> str:
    """Render a labeled, line-numbered fenced block."""
    numbered = _number_lines(content)
    return f"#### {label}\n\n```{lang}\n{numbered}\n```"


def _number_lines(content: str) -> str:
    """Prefix every line with its 1-indexed number in a 4-char gutter.

    Format: '{N:4d}  {line}'. Same convention as agent-researcher.
    """
    lines = content.splitlines()
    return "\n".join(f"{i + 1:4d}  {line}" for i, line in enumerate(lines))
