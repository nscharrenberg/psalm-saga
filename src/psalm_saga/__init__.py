"""PSALM-SAGA: synthetic story generation with langchain deepagents.

Generates stories either from scratch (optionally seeded with context) or from a source text,
using the narratological dimensions from PSALM (github.com/nscharrenberg/psalm) as a generative
brainstorming checklist instead of a similarity-scoring rubric.
"""

from psalm_saga.config import GuardStrictness, Settings
from psalm_saga.dimensions import GenerationMode, StoryBible

__version__ = "0.1.0"

__all__ = [
    "__version__",
    "Settings",
    "GuardStrictness",
    "GenerationMode",
    "StoryBible",
]
