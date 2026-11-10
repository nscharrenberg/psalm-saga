"""Every setting of a run, described for the interface: the run-level fields of PipelineConfig and the
parameters each stage reads (`stages.<stage>.params.<name>`), with type, default, allowed values and a
plain-language explanation. The web app renders its "All settings" editor from this, so nothing a run
can do needs a code change or a hand-written key=value line.

A test checks that every `params.get("...")` in psalm_saga/stages is listed here, so the catalogue
cannot fall behind the code.
"""

from __future__ import annotations


def _p(type_: str, default, help_: str, choices: list | None = None, impl: str | None = None, **kw) -> dict:
    d = {"type": type_, "default": default, "help": help_}
    if choices:
        d["choices"] = choices
    if impl:
        d["impl"] = impl
    d.update(kw)
    return d


STAGE_PARAMS: dict[str, dict[str, dict]] = {
    "extract": {
        "chunk_words": _p("int", 4000, "Words per passage the analysis reads at a time (map step)."),
        "parallel": _p("int", 8, "Passages analysed at the same time."),
        "consolidate": _p("bool", True, "Merge aliases of the same character or place after the passages are analysed."),
        "classify": _p("bool", True, "First decide what kind of text it is (novel, stories, poems, drama)."),
        "pseudo_chapter_words": _p("int", 5000, "A text without chapter headings is split into parts of this size."),
        "detect_variety": _p("bool", True, "Detect the language variety (dialect, historical spelling) of the source."),
        "temperature": _p("float", 0.2, "Sampling temperature of the analysis calls."),
    },
    "transform": {
        "parallel": _p("int", 8, "Chapters of the design transformed at the same time."),
        "max_entities": _p("int", 120, "At most this many characters, places and objects are renamed and transformed."),
        "reskin_retries": _p("int", 1, "When a re-invented chapter stays too close to the source, ask again this often."),
    },
    "plan": {
        "parallel": _p("int", 6, "Chapter plans written at the same time."),
        "extra_instruction": _p("text", "", "Free-text instruction added to every planning prompt."),
    },
    "draft": {
        "continuity": _p("choice", "plan", "What a chapter sees of the previous one: its plan (chapters can be written "
                         "in parallel) or the end of its prose (sequential, slower).", ["plan", "prose"], impl="chapter"),
        "rhythm": _p("choice", "scaffold", "Measured style targets in the drafting prompt: a paragraph-by-paragraph "
                     "scaffold, a short brief, or none.", ["scaffold", "brief", "off"], impl="chapter"),
        "top_up": _p("bool", True, "Continue a clearly too short chapter once instead of accepting it.", impl="chapter"),
        "extra_instruction": _p("text", "", "Free-text instruction added to every drafting prompt.", impl="chapter"),
        "inputs": _p("list", ["spec"], "What the single call gets: the source, the specification, the chapter "
                     "skeleton, a premise.", ["source", "spec", "skeleton", "premise"], impl="oneshot"),
        "continuations": _p("int", 3, "How often a single call may continue when it hits the output limit.", impl="oneshot"),
        "refine_rounds": _p("int", 0, "Rounds of self-critique and revision after the single call (compute-matched "
                            "baseline).", impl="oneshot"),
        "chunk_words": _p("int", 700, "Words per paraphrased passage.", impl="paraphrase"),
        "parallel": _p("int", 8, "Passages paraphrased at the same time.", impl="paraphrase"),
        "use_spec": _p("bool", True, "Agents' Room planners get the transformed specification.", impl="agents_room"),
    },
    "conform": {
        "rounds": _p("int", 2, "At most this many style revisions per chapter (each rewrites the chapter)."),
        "tolerance": _p("float", 0.12, "Stop when the chapter is this close to the source's measured style (0 = exact)."),
        "max_length_change": _p("float", 0.12, "A revision may change the chapter's length by at most this share."),
        "patience": _p("int", 2, "Stop after this many rejected revisions in a row."),
        "min_gain": _p("float", 0.005, "Stop after a kept revision that improved the style distance by less than this."),
        "passage_words": _p("int", 1800, "A long chapter is revised in passages of about this size."),
        "parallel": _p("int", 4, "Passages of one chapter revised at the same time."),
        "parallel_chapters": _p("int", 4, "Chapters conformed at the same time."),
    },
    "review": {
        "rounds": _p("int", 1, "Prose repairs per chapter after the check."),
        "threshold": _p("choice", "major", "Lowest severity that triggers a repair.", ["blocker", "major", "minor"]),
        "max_issues": _p("int", 6, "At most this many issues per chapter are reported."),
        "repair_mode": _p("choice", "edits", "Repair by editing paragraphs, or by rewriting the chapter.", ["edits", "rewrite"]),
        "keep_if_not_worse": _p("bool", True, "Keep a repair only if the re-check finds no more blocking issues."),
        "replan": _p("bool", True, "When the chapter plan is at fault, revise it and redraft the chapter."),
        "max_backtracks": _p("int", 1, "Times the run may go back to planning when problems trace back to the design "
                             "(each redoes every chapter)."),
        "backtrack_threshold": _p("choice", "blocker", "Lowest severity of a design problem that sends the run back.",
                                  ["blocker", "major", "minor"]),
        "coverage": _p("bool", True, "Check every chapter against the design checklist (events, causes, relations, places)."),
        "strict_coverage": _p("bool", False, "Missing places, objects and relations count as major, not minor."),
        "style_slack": _p("float", 0.05, "A repair may loosen the measured style by at most this much."),
        "restyle_rounds": _p("int", 2, "Style rounds of the touch-up after repairs."),
        "parallel": _p("int", 4, "Chapters checked at the same time."),
    },
    "guard": {
        "min_span": _p("int", 10, "Passages copied from the source from this many words on are reworded."),
        "rounds": _p("int", 2, "Rounds of rewording copied passages."),
    },
    "assemble": {
        "numbered": _p("bool", True, "Number the chapters in the assembled text (default: not for collections)."),
    },
    "recover": {
        "align": _p("choice", "model", "How the text's analysis is matched with the design: by the model, or by names only.",
                    ["model", "rules"]),
        "check_text": _p("bool", True, "Look up unmatched design items in the chapter text before counting them lost."),
        "calibrate": _p("bool", False, "Also analyse the source a second time, to measure the analysis' own agreement."),
    },
    "spec": {},
    "evaluate": {"judges": _p("bool", False, "Run the judges even when judges.enabled is off.")},
}

MODEL_FIELDS: dict[str, dict] = {
    "name": _p("str", "anthropic/claude-sonnet-5-5", "LiteLLM model id (provider/model)."),
    "temperature": _p("float", 0.8, "Sampling temperature (empty = provider default)."),
    "extra.reasoning_effort": _p("choice", None, "How much a reasoning model thinks before answering.",
                                 [None, "none", "minimal", "low", "medium", "high"]),
    "extra.provider_order": _p("str", None, "OpenRouter: hosts to use, in order, comma-separated (e.g. 'deepinfra, "
                               "together'); empty = OpenRouter chooses."),
    "extra.provider_sort": _p("choice", None, "OpenRouter: prefer the host with the best of this (empty = OpenRouter's "
                              "default balance).", [None, "throughput", "latency", "price"]),
    "extra.provider_fallbacks": _p("choice", None, "OpenRouter: may other hosts serve the call when the listed ones "
                                   "cannot (empty = yes)?", [None, True, False]),
    "extra.api_base": _p("str", None, "Endpoint of a self-hosted model (vLLM, Ollama)."),
    "max_output_tokens": _p("int", 8000, "Largest answer per call; 0 = no limit of our own (the provider's maximum, "
                            "within the run's budget)."),
    "min_output_tokens": _p("int", 2048, "Smallest output allowance per call (reasoning models need room)."),
    "reasoning": _p("choice", None, "Treat as a reasoning model (empty = detect).", [None, True, False]),
    "reasoning_headroom": _p("int", 8000, "Extra output tokens for a reasoning model's hidden reasoning."),
    "reasoning_max_tokens": _p("int", None, "Most hidden reasoning per call, where the provider takes a limit (OpenRouter, "
                               "Anthropic); empty = the provider's default for the reasoning effort."),
    "context_window": _p("int", 200000, "Input the model accepts, in tokens."),
    "timeout_s": _p("float", 600, "Seconds before a call is abandoned."),
    "timeout_retries": _p("int", 2, "Retries after a timeout."),
    "max_retries": _p("int", 8, "Retries after other temporary errors (rate limits, server errors)."),
    "max_concurrency": _p("int", 4, "Calls in flight at once."),
    "rpm": _p("int", None, "Requests per minute (empty = no limit)."),
    "tpm": _p("int", None, "Tokens per minute (empty = no limit)."),
    "stream": _p("bool", True, "Stream long answers (avoids idle-connection timeouts)."),
    "prompt_cache": _p("bool", True, "Mark the stable prompt prefix cacheable."),
    "input_cost_per_mtok": _p("float", None, "Price per million input tokens (empty = LiteLLM's table)."),
    "output_cost_per_mtok": _p("float", None, "Price per million output tokens."),
}

RUN_FIELDS: list[dict] = [
    {"group": "Story design", "key": "use_graph", **_p("bool", True, "Planning, drafting and review see the story graph "
                                                       "(off = the knowledge-graph ablation).")},
    {"group": "Story design", "key": "transform.rename_entities", **_p("bool", True, "Give every named entity a new name.")},
    {"group": "Story design", "key": "transform.keep_cultural_setting",
     **_p("bool", True, "New names fit the source's culture and period.")},
    {"group": "Story design", "key": "transform.keep_real_names",
     **_p("choice", None, "Keep real places and events (empty = when world building is kept).", [None, True, False])},
    {"group": "Story design", "key": "transform.notes", **_p("text", "", "Free-text instruction for the transformation.")},
    {"group": "Length", "key": "length.target_words", **_p("int", None, "Target length (empty = the source's).")},
    {"group": "Length", "key": "length.tolerance", **_p("float", 0.15, "Allowed deviation from the target length.")},
    {"group": "Length", "key": "length.chapters", **_p("str", "match", "Chapters: match, auto, or a number.")},
    {"group": "Length", "key": "length.max_chapter_words", **_p("int", 6000, "Longer chapters are written scene by scene.")},
    {"group": "Language", "key": "language.output", **_p("str", "auto", "Output language (auto = the source's; else an ISO code).")},
    {"group": "Language", "key": "language.variety", **_p("str", "auto", "Language variety: auto, modern, or a description.")},
    {"group": "Language", "key": "language.enforce", **_p("bool", True, "Check the language of every chapter and retry.")},
    {"group": "Language", "key": "language.max_retries", **_p("int", 2, "Retries for a chapter in the wrong language.")},
    {"group": "Limits", "key": "limits.max_cost_usd", **_p("float", None, "Stop when this much is spent (US dollars).")},
    {"group": "Limits", "key": "limits.max_minutes", **_p("float", None, "Stop after this many minutes of work (continue later).")},
    {"group": "Limits", "key": "limits.max_parallel_chapters", **_p("int", 3, "Chapters drafted at the same time.")},
    {"group": "Judges", "key": "judges.enabled", **_p("bool", False, "Run the judges in the evaluation.")},
    {"group": "Judges", "key": "judges.model", **_p("str", None, "Primary judge model (decides the grades).")},
    {"group": "Judges", "key": "judges.panel", **_p("panel", [], "Further judges, one per line: model id, or id @ endpoint.")},
    {"group": "Judges", "key": "judges.instruments", **_p("list", ["psalm", "content", "style"], "Which judges run.",
                                                          ["psalm", "content", "style"])},
    {"group": "Judges", "key": "judges.full_text_words", **_p("int", 6000, "PSALM reads both texts in full up to this length.")},
    {"group": "Judges", "key": "judges.excerpt_words", **_p("int", 700, "Otherwise excerpts of this length.")},
    {"group": "Judges", "key": "judges.excerpts", **_p("int", 3, "Number of excerpts.")},
    {"group": "Run", "key": "preflight", **_p("bool", True, "Check the settings before the run starts.")},
    {"group": "Run", "key": "preflight_live", **_p("bool", True, "Include one tiny test call per model in the check.")},
    {"group": "Run", "key": "cache", **_p("bool", True, "Keep model answers on disk (resume without paying twice).")},
    {"group": "Run", "key": "cache_scope", **_p("choice", "run", "Replay only this run's answers, or any identical earlier "
                                                "answer.", ["run", "shared"])},
    {"group": "Run", "key": "log_calls", **_p("bool", True, "Record every model call with its input and output.")},
    {"group": "Run", "key": "seed", **_p("int", None, "Seed passed to providers that support it.")},
    {"group": "Run", "key": "taxonomy", **_p("str", "psalm", "Dimension taxonomy (built-in name or a YAML path).")},
    {"group": "Run", "key": "prompts_dir", **_p("str", None, "Folder whose prompt templates override the built-in ones.")},
]


def catalogue() -> dict:
    from psalm_saga.stages import available

    return {"stages": STAGE_PARAMS, "model_fields": MODEL_FIELDS, "run_fields": RUN_FIELDS, "impls": available()}
