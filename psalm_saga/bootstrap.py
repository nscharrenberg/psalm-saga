"""Assembles the psalm-saga bootstrap for a deepagents `system_prompt`.

Why this module exists
-----------------------
deepagents' own `SkillsMiddleware` only ever surfaces a skill's *name* and
*description* in the system prompt at startup (progressive disclosure); the
full body of a skill is loaded on demand via `read_file`. That's fine for
ordinary skills, but `using-psalm-saga` is special: it's the
behavior-shaping bootstrap that teaches the model the spec-first workflow
exists at all and that it must be followed *before* doing anything else,
including asking a clarifying question. Leaving that to chance (an entry in
a skill list the model might not read closely) is a much weaker guarantee
than force-injecting it.

This module reads the real `using-psalm-saga/SKILL.md` off disk, strips its
YAML frontmatter, appends its tool-mapping reference, and returns a single
string meant to be concatenated onto the application's own `system_prompt`
before calling `create_deep_agent(...)`.

This is *not* a copy of the skill's content baked into this file — it reads
the real files at call time, so editing the vendored `skills/` directory
automatically changes what gets injected, with zero edits here.
"""

import re
from pathlib import Path

SKILLS_DIR = Path(__file__).resolve().parent / "skills"
BOOTSTRAP_SKILL = "using-psalm-saga"
TOOL_MAPPING_PATH = "references/deepagents-tools.md"

_FRONTMATTER_RE = re.compile(r"\A---\n.*?\n---\n", re.DOTALL)

_PREAMBLE = (
    "<EXTREMELY_IMPORTANT>\n"
    f"The `{BOOTSTRAP_SKILL}` skill below is already active for this "
    "conversation — it was injected here at agent-construction time. Do "
    f"not try to read or invoke `{BOOTSTRAP_SKILL}` again; it is not a "
    "step you need to take. Every *other* skill it mentions still follows "
    'the normal progressive-disclosure flow: check the "Skills System" '
    "section of this prompt for what's available, and `read_file` a "
    "skill's `SKILL.md` when it applies.\n"
    "</EXTREMELY_IMPORTANT>\n"
)


def _strip_frontmatter(skill_md_text: str) -> str:
    """Remove the YAML frontmatter block from a SKILL.md's raw text."""
    return _FRONTMATTER_RE.sub("", skill_md_text, count=1).strip()


def build_bootstrap(skills_dir: str | Path = SKILLS_DIR) -> str:
    """Return the psalm-saga bootstrap fragment for a deepagents `system_prompt`.

    Args:
        skills_dir: Path to the vendored `skills/` directory (defaults to
            the one shipped alongside this package). Point this at your own
            copy if you've forked or extended the skills separately.

    Raises:
        FileNotFoundError: if `using-psalm-saga/SKILL.md` is missing from
            `skills_dir` — this fails loudly rather than silently shipping
            an agent with no bootstrap.

    """
    skills_dir = Path(skills_dir)
    skill_md_path = skills_dir / BOOTSTRAP_SKILL / "SKILL.md"
    tool_mapping_path = skills_dir / BOOTSTRAP_SKILL / TOOL_MAPPING_PATH

    if not skill_md_path.is_file():
        raise FileNotFoundError(
            f"{BOOTSTRAP_SKILL}/SKILL.md not found under {skills_dir}. "
            "Did you vendor the skills/ directory correctly?"
        )

    body = _strip_frontmatter(skill_md_path.read_text(encoding="utf-8"))

    tool_mapping_section = ""
    if tool_mapping_path.is_file():
        tool_mapping = tool_mapping_path.read_text(encoding="utf-8").strip()
        tool_mapping_section = (
            f"\n\n## Tool mapping for this harness (LangChain Deep Agents)\n\n{tool_mapping}\n"
        )

    return f"{_PREAMBLE}\n{body}{tool_mapping_section}"


def compose_system_prompt(
    application_prompt: str = "",
    skills_dir: str | Path = SKILLS_DIR,
) -> str:
    """Concatenate the caller's own instructions with the psalm-saga bootstrap.

    `using-psalm-saga`'s own text notes user instructions take precedence
    over skills, which override default behavior — so the application's
    prompt goes first, the bootstrap after, matching that precedence order.
    """
    bootstrap = build_bootstrap(skills_dir)
    if not application_prompt.strip():
        return bootstrap
    return f"{application_prompt.strip()}\n\n{bootstrap}"
