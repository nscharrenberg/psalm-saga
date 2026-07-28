"""
System prompts, kept as versioned markdown files rather than inline strings.

Use :func:`load_prompt` to fetch one by name (without the ``.md`` extension).
"""

from functools import lru_cache
from importlib import resources


@lru_cache(maxsize=None)
def load_prompt(name: str) -> str:
    """
    Load a prompt template by name, e.g. ``load_prompt("writer")``.
    :param name: The name of the prompt template to load.
    :return: The loaded prompt template.
    """

    package = resources.files(__package__)
    return (package / f"{name}.md").read_text(encoding="utf-8")