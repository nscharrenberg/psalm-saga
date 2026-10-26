"""Prompt templates (Jinja, one .md per prompt) with per-run override directories."""

from __future__ import annotations

from importlib import resources
from pathlib import Path

import jinja2

_BUILTIN = Path(str(resources.files("psalm_saga") / "prompts"))


class Prompts:
    def __init__(self, override_dir: str | Path | None = None):
        dirs = [str(override_dir)] if override_dir else []
        self.env = jinja2.Environment(
            loader=jinja2.FileSystemLoader([*dirs, str(_BUILTIN)]),
            undefined=jinja2.ChainableUndefined,
            keep_trailing_newline=False,
            trim_blocks=False,
            autoescape=False,
        )

    def render(self, name: str, **kw) -> str:
        return self.env.get_template(f"{name}.md").render(**kw).strip()
