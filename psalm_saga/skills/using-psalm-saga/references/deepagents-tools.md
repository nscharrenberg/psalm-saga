## LangChain Deep Agents tool mapping

This skill set runs on `deepagents`, an "agent harness" library on top of
LangGraph/LangChain. There is no interactive IDE session the way there is in
an editor plugin — your human partner is the CLI (`psalm-saga`) or
application that constructed you with `create_deep_agent(...)`.

### File operations

- **Read a file** → `read_file(file_path, offset=0, limit=1000)`. The
  default `limit` is 100 lines, too small for most `SKILL.md` bodies or
  spec/plan files — pass `limit=1000` (or higher) when reading one.
- **Create or fully overwrite a file** → `write_file(file_path, content)`.
  Use this for the spec, the plan, and each chapter's prose file.
- **Edit part of a file** → `edit_file(file_path, old_string, new_string)`
  (exact string replacement).
- **List a directory** → `ls(directory_path)`.
- **Find files by name** → `glob(pattern)`.
- **Search file contents** → `grep(pattern, ...)`.

### Dispatch a subagent

- **Dispatch** → the `task` tool: `task(description="...", subagent_type="...")`.
  `description` is the entire brief — the subagent is stateless and sees
  nothing else, so put everything a skill's dispatch instructions say to
  include (spec excerpts, chapter brief, continuity summary, etc.) directly
  in `description`.
- `subagent_type` must be one of the agent types listed in the `task` tool's
  own description at call time. This pack registers `chapter-writer` and
  `dimension-reviewer` as named subagents for `drafting-chapters` and
  `reviewing-story-dimensions` to target; `general-purpose` is always
  available too if a task doesn't fit either named role.
- `task` is synchronous: the call blocks until the subagent returns its
  final report. There's no separate wait/poll step.
- The subagent's report is not shown to your human partner automatically —
  relay a summary yourself.

### Todos / task tracking

- **Create / update todos** → `write_todos`. Use this for tracking dimension
  checklists during `story-brainstorming` and chapter checklists during
  `drafting-chapters`.

### Invoke a skill

This harness surfaces every skill's `name` and `description` in your system
prompt at startup (progressive disclosure) but has no dedicated `Skill`
tool — loading a skill's full body is done with `read_file`. Check the
"Available Skills" section already in your system prompt, then
`read_file(file_path=<path shown there>, limit=1000)` to load the full
`SKILL.md` when a skill applies. `using-psalm-saga` itself is the one
exception — you're reading its content right now because it was force-loaded
into your system prompt at construction time; don't `read_file` it again.

### What's intentionally absent

This pack does not assume shell execution or web search tools exist. Story
drafting, planning, and review don't need either — every skill's actions map
onto the file and subagent tools above. If your application registered
additional tools (e.g. a web-research tool for fact-checking a
historical-fiction setting), use them where a skill's instructions call for
research; otherwise treat research-dependent steps as something to ask your
human partner about directly.
