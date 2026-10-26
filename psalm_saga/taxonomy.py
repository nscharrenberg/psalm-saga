"""The dimension taxonomy, loaded from YAML so experiments can swap it."""

from __future__ import annotations

from functools import cache
from importlib import resources
from pathlib import Path

import yaml
from pydantic import BaseModel, Field


class SubDimension(BaseModel):
    key: str
    label: str
    guidance: str = ""
    surface: bool = False


class Dimension(BaseModel):
    key: str
    label: str
    description: str = ""
    subdimensions: list[SubDimension] = Field(default_factory=list)


class Taxonomy(BaseModel):
    name: str
    dimensions: list[Dimension]

    def keys(self) -> list[str]:
        return [d.key for d in self.dimensions]

    def get(self, key: str) -> Dimension:
        for d in self.dimensions:
            if d.key == key:
                return d
        raise KeyError(key)

    def render(self, only: list[str] | None = None) -> str:
        """Compact prompt rendering: one line per sub-dimension."""
        lines = []
        for d in self.dimensions:
            if only and d.key not in only:
                continue
            lines.append(f"## {d.label} [{d.key}]: {d.description}")
            for s in d.subdimensions:
                mark = " (surface)" if s.surface else ""
                lines.append(f"- {s.label} [{s.key}]{mark}: {s.guidance}")
        return "\n".join(lines)


@cache
def load_taxonomy(name_or_path: str = "psalm") -> Taxonomy:
    p = Path(name_or_path)
    if p.suffix in {".yaml", ".yml"} and p.exists():
        raw = p.read_text(encoding="utf-8")
    else:
        raw = (resources.files("psalm_saga") / "taxonomies" / f"{name_or_path}.yaml").read_text(encoding="utf-8")
    return Taxonomy.model_validate(yaml.safe_load(raw))
