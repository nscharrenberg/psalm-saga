"""Plain-language help for the web app: what every preset, stage, policy, tab and term means.

One place for the wording, served with /api/meta, so the interface explains itself the same way
everywhere (tooltips, info buttons, the help panel). Written for a researcher who has not read the
code or the paper.
"""

from __future__ import annotations

PRESETS: dict[str, dict] = {
    "full": {"title": "Full pipeline", "kind": "main", "recommended": True,
             "summary": "Analyse the source, decide per dimension what carries over, plan, write chapter by chapter from "
                        "the story graph, measure every chapter and correct its style and content, remove copied "
                        "wording, and evaluate.",
             "when": "The default for producing a synthetic counterpart of a text."},
    "no_graph": {"title": "Without the story graph", "kind": "paper",
                 "summary": "As the full pipeline, but planning, writing and checking do not see the story graph "
                            "(characters, places, relations, events, causes) — only the specification and a synopsis per "
                            "chapter. The graph is still built, so the evaluation can measure it.",
                 "when": "Shows what the knowledge graph contributes."},
    "no_feedback": {"title": "Without measuring and correcting", "kind": "paper",
                    "summary": "As the full pipeline, but drafts are kept as written: neither style matching nor "
                               "check-and-repair runs. The writer is still told the source's measured style once.",
                    "when": "Shows what steering by the measured data properties contributes."},
    "paraphrase": {"title": "Rename and paraphrase", "kind": "paper",
                   "summary": "Rename the characters and places, then paraphrase the source passage by passage. Keeps "
                              "everything by construction; the question is how much of the source's wording it keeps "
                              "too. Always keeps every dimension.",
                   "when": "The naive way to make a synthetic text."},
    "flat": {"title": "Single call", "kind": "paper",
             "summary": "The model gets the source and what should carry over, and writes the counterpart in one call. "
                        "No analysis, plan, checks or copy guard.",
             "when": "What one model call achieves on its own."},
    "no_review": {"title": "Without check-and-repair only", "kind": "more",
                  "summary": "As the full pipeline without checking chapters against the plan and design; style "
                             "matching still runs. (\"Without measuring and correcting\" turns off both.)",
                  "when": "Separates the content check from the style correction."},
    "no_conform": {"title": "Without style matching only", "kind": "more",
                   "summary": "As the full pipeline without the step that corrects the prose towards the source's "
                              "measured rhythm, and without style numbers for the writer; check-and-repair still runs.",
                   "when": "Separates the style correction from the content check."},
    "no_spec": {"title": "Without the specification", "kind": "more",
                "summary": "No description of the six dimensions: the story is planned from the chapter outline only.",
                "when": "What the dimension specification contributes."},
    "flat_spec": {"title": "Single call from the design", "kind": "more",
                  "summary": "Analyse and transform as usual, then write the whole story in one call from the "
                             "specification and outline — no planning, no checks.",
                  "when": "What planning and chapter-by-chapter writing add."},
    "flat_refine": {"title": "Single call + self-revision", "kind": "more",
                    "summary": "The single call, then rounds of self-critique and revision against the source, so that "
                               "it uses about as much inference as the full pipeline.",
                    "when": "Separates the pipeline's design from simply using more compute."},
    "agents_room": {"title": "Agents' Room", "kind": "more",
                    "summary": "A published multi-agent story-writing method (Huot et al., 2024): planners for conflict, "
                               "character, setting and plot, then writers per part of the story arc.",
                    "when": "Comparison with a published generation method."},
    "fast": {"title": "Quick test", "kind": "more",
             "summary": "The full pipeline with the expensive checks left out and a small model for the analysis. "
                        "Cheaper and faster, lower quality.",
             "when": "Trying settings or a new text before a real run."},
}

KINDS = {"main": "Recommended", "paper": "Compared in the paper's experiments",
         "more": "Other ablations and baselines"}

STAGES: dict[str, dict] = {
    "extract": {"title": "Analyse the source",
                "what": "Reads the source in passages (in parallel) and records who appears, where, what happens and why, "
                        "and how the text is written. Merges the passages into the story bible and measures the style "
                        "(sentence lengths, dialogue, punctuation, form, language variety).",
                "produces": "story bible of the source, measured style profile, language variety", "calls": "one per passage of ~4,000 words, plus a few"},
    "spec": {"title": "Describe the six dimensions",
             "what": "Writes a specification of the source along six dimensions (writing style, narrative voice, "
                     "characters, plot, scene sequence, world) — concrete behaviours and mechanisms, in the analyst's own words.",
             "produces": "source specification", "calls": "one per dimension"},
    "transform": {"title": "Decide what carries over",
                  "what": "Applies your transform policy: renames every character and place, keeps preserved dimensions, "
                          "re-invents abstracted ones and replaces regenerated ones. This is the clean-room boundary: "
                          "nothing after this step sees the source text.",
                  "produces": "synthetic specification, story design (renamed bible), rename table", "calls": "a few"},
    "plan": {"title": "Plan the story",
             "what": "Outlines the whole story, then plans each chapter scene by scene with beats and word budgets, "
                     "following the design's chapter outline.",
             "produces": "story plan", "calls": "one for the outline, one per chapter"},
    "draft": {"title": "Write the chapters",
              "what": "Writes each chapter (long chapters scene by scene) from its plan, the cast, the facts it must "
                      "show and the source's measured rhythm. Checks language, form and variety, and retries if needed.",
              "produces": "chapter texts", "calls": "one per chapter or scene, plus retries"},
    "conform": {"title": "Match the source's style",
                "what": "Measures each chapter's rhythm (sentence lengths and their spread, the sentence- and "
                        "paragraph-length distributions, dialogue, punctuation; lines, stanzas and rhyme for verse) and "
                        "asks for a revision towards the source's numbers. A revision is kept only if it gets closer "
                        "without changing length, language or content, and without making a prioritised measure worse. "
                        "A chapter that review later redrafts is matched again before it is accepted.",
                "produces": "revised chapters, style log per chapter", "calls": "up to two revisions per chapter"},
    "review": {"title": "Check and repair",
               "what": "An editor checks each chapter against its plan, the specification and the design checklist "
                       "(events, causes, relations, places). Real problems are fixed where they come from: in the text, "
                       "in the chapter plan, or — once — in the specification.",
               "produces": "review per chapter, design coverage", "calls": "one or two per chapter"},
    "guard": {"title": "Remove copied wording",
              "what": "Finds passages shared word-for-word with the source and original names that survived, and "
                      "rewrites only those paragraphs.",
              "produces": "copy report", "calls": "only for flagged paragraphs"},
    "assemble": {"title": "Put the book together",
                 "what": "Joins the chapters into one text with title and chapter headings.", "produces": "story", "calls": "none"},
    "recover": {"title": "Analyse the synthetic text",
                "what": "Analyses the finished synthetic text once, with the same procedure as the source, and relates "
                        "it back to the story design (which keeps the source's identities): by names, then by a model for "
                        "what names cannot pair, and finally by checking the synthetic chapters for design items the "
                        "analysis missed. So the evaluation knows, for every source item, whether it was kept, changed or "
                        "lost — without analysing the source again.",
                "produces": "story bible of the synthetic text, its alignment with the design",
                "calls": "one per passage, plus a few alignment calls per chapter"},
    "evaluate": {"title": "Evaluate",
                 "what": "Measures how far the synthetic text keeps the source's properties and how far it is from the "
                         "source's wording. If you enabled the judges, language models also compare the texts: the PSALM "
                         "judge dimension by dimension, and two judges on story and style.",
                 "produces": "evaluation", "calls": "none, or up to eight with the judges"},
}

POLICIES: dict[str, dict] = {
    "preserve": {"title": "Keep", "short": "kept as in the source",
                 "what": "The dimension is kept as it is in the source: the same behaviour, structure and details, "
                         "only with new names."},
    "abstract": {"title": "Re-invent", "short": "same function, new particulars",
                 "what": "What the dimension does is kept, but its concrete particulars are re-invented: the same kind "
                         "of character, scene or world playing the same role, with different specifics (a rigged contest "
                         "stays a rigged contest, but with another contest and another trick). Measures that compare "
                         "the source's own values for this dimension are then not graded; the PSALM judge should find "
                         "the same function (4–5) and different particulars (expression 1–2)."},
    "regenerate": {"title": "Replace", "short": "invented anew",
                   "what": "The dimension is invented anew, as for a different story: the writer's design is made "
                           "without seeing the source's values for it (a replaced plot gets a new skeleton of events and "
                           "scenes; a replaced cast gets new roles and relationships). Source-side measures for it are "
                           "not graded; the PSALM judge should find neither the function nor the particulars (1–2)."},
}

DIMENSION_EXAMPLES: dict[str, dict[str, str]] = {
    "writing_style": {"preserve": "same sentence rhythm, register and imagery",
                      "abstract": "comparable register and rhythm, own imagery",
                      "regenerate": "any style"},
    "narrative_voice": {"preserve": "same narrator, point of view, tense and distance",
                        "abstract": "same kind of narration, different narrator persona",
                        "regenerate": "any narration"},
    "character": {"preserve": "same people (renamed), same traits and ties",
                  "abstract": "people with the same roles and relations, different traits",
                  "regenerate": "a new cast"},
    "plot_structure": {"preserve": "same events, order and outcome",
                       "abstract": "same kind of arc and turning points, different events",
                       "regenerate": "a new plot"},
    "scene_sequence": {"preserve": "same scenes in the same order",
                       "abstract": "scenes with the same function and order, new content",
                       "regenerate": "free scene structure"},
    "world_building": {"preserve": "same places and objects (renamed)",
                       "abstract": "a comparable setting, different places",
                       "regenerate": "a new world"},
}

TABS: dict[str, str] = {
    "story": "The synthetic text as it stands.",
    "spec": "The specification: the six dimensions described in words, for the source and for the synthetic story. "
            "You can edit it; everything after it is then redone.",
    "bible": "The story as knowledge graphs — characters, places, scenes, events and how they connect — for the source, "
             "the design the writer worked from and the synthetic text as written; any two side by side with every "
             "difference listed; and a trace of where each difference arose (in the design or in the writing).",
    "plan": "The plan the writer followed: outline, chapters, scenes and beats.",
    "chapters": "Each chapter with how it was made: style matching, review issues and how they were fixed, design facts shown.",
    "evaluation": "How far the synthetic text keeps the source's properties, and how far it is from the source's wording.",
    "usage": "Model calls, tokens, cost and time, per stage.",
    "activity": "A live log of the run: every step and model call, with its full input and output.",
    "config": "The exact settings this run used.",
}

GLOSSARY: dict[str, str] = {
    "source": "The text you start from (in copyright, not to be redistributed).",
    "synthetic text": "The new text the pipeline writes: same research-relevant properties, new expression.",
    "dimension": "One of six aspects of a narrative the method controls separately: writing style, narrative voice, "
                 "characters, plot structure, scene sequence, world.",
    "transform policy": "Per dimension, what carries over from the source: keep, re-invent or replace.",
    "specification (spec)": "A description of the six dimensions in words — behaviours and mechanisms, no quotations.",
    "story bible": "Who appears, where, what happens and why, chapter by chapter, and how people and things relate.",
    "story design": "The bible after renaming and applying the policies: what the writer is asked to realise.",
    "knowledge graph": "The bible drawn as nodes (people, places, objects, scenes, events) and links (relations, "
                       "causes, appearances).",
    "clean-room boundary": "After the transform step, no stage sees the source text — only the specification, design "
                           "and measured numbers. Wording cannot be copied from what is not seen.",
    "style profile": "Numbers measured on the source: sentence and paragraph lengths and their spread, dialogue share, "
                     "punctuation, word length, pronouns; lines, stanzas and rhyme for verse.",
    "design checklist": "Per chapter, the design's events, causes, relations and places that the chapter must show.",
    "alignment": "How the synthetic text's story graph is related back to the design: names first, then a model "
                 "pairing what names cannot, then a check of the chapter text for what the analysis missed.",
    "second analysis (calibration)": "Optional: the source analysed a second time, to see how far two analyses of one "
                                     "text agree (a noise ceiling for experiments). Off by default.",
    "ceiling": "With the optional second analysis: how far it agrees with the first. Graph scores can then also be "
               "shown relative to it.",
    "self-agreement": "The source's first half compared with its second half. No synthetic text can match the author "
                      "more closely than the author matches themself, so style thresholds allow for it.",
    "score": "Every measure converted to 0–1 where 1 is best, with its formula shown. Green ≥ 0.80, orange ≥ 0.60 "
             "unless the measure says otherwise.",
    "judge": "A language model asked a precise question (does this tell the same story?) and to rate it 1–5. Optional, "
             "and best with a model of a different family from the one that wrote the text.",
    "PSALM judge": "A judge that compares the two texts on the six dimensions and their 36 aspects. For each aspect it "
                   "describes both texts, quotes short evidence, argues its verdict and rates function (does it do the "
                   "same thing?) and expression (are the concrete particulars the same?) separately.",
    "model library": "Every model is described once (Models, top right): its id, where it runs, how much it reasons, "
                     "its limits and price. Everywhere a model is needed — the writer, a step, the judges, an experiment's "
                     "writers — you choose it by name. A run keeps a copy of the settings it was made with.",
    "judge panel": "Further judge models next to the primary one (judges.panel). Each runs the same judges; the primary "
                   "judge still decides the grades, and the evaluation shows every judge's results side by side with "
                   "their agreement (Krippendorff's α on the 36 PSALM ratings: ≥ 0.8 reliable, below 0.667 the judges "
                   "disagree). A self-hosted judge is given as `model-id @ endpoint`.",
    "time limit": "limits.max_minutes: the run stops after this many minutes of work, keeps everything done so far, and "
                  "Continue picks up where it stopped. The pre-flight check warns when a configuration can rewrite each "
                  "chapter many times (strict style priorities, re-planning, going back to planning).",
    "core measure": "A primary measure of the experiments: a property the method keeps (some it steers on purpose: "
                    "the sentence- and paragraph-length distributions, the design's events, causes, characters and "
                    "relations), a measure no stage steers that checks them (frequent-word profile, salience, the "
                    "judges), or a guardrail (length, form, names). The rest is diagnostic detail.",
    "fix": "A targeted redo suggested by the evaluation. It makes a new version of the run (the original stays as it "
           "was) and redoes everything from the stage it names, so the two versions can be compared and the better "
           "one kept. Versions are marked, because their measurements are no longer independent.",
    "priorities": "Evaluation measures you mark as most important for your study (default: none — all count equally). "
                  "The generation works harder on them (more style rounds, stricter checks, more guard rounds), weighs "
                  "them 3× when choosing between revisions, and the evaluation shows a priority score.",
    "pre-flight check": "Before a run starts or continues, its settings are checked: stage names, policies, priorities, "
                        "API keys, and one tiny test call per model. A run with a problem waits (settings need "
                        "attention) instead of failing halfway; change the settings and continue.",
    "pause / stop": "Pause holds every new model call until you resume (calls in flight finish); 'pause after this "
                    "stage' stops at the next stage boundary. Stop ends the run cleanly — finished work is kept and "
                    "Continue carries on, also with changed settings. Abort drops the calls in flight.",
    "trace": "Every source item followed through the design to the synthetic text: kept throughout, changed or left out "
             "by the design (the policy — intended), or changed, lost or added in the writing (the generation).",
    "real-world names": "Names of the real, shared world — countries, seas, historical events, public legends — are not "
                        "the author's invention. When world building is kept, they stay as they are; only invented names "
                        "are replaced.",
    "function / expression (1–5)": "The PSALM judge's two ratings per aspect: 1 unrelated · 2 loosely related · 3 clearly "
                                   "related with substantial differences · 4 largely the same · 5 the same. Targets: Keep "
                                   "— function 4–5, expression 3–4 (the same particulars in new words); Re-invent — function "
                                   "4–5, expression 1–2; Replace — function 1–2, expression 1–2.",
    "version": "A copy of a run with one or more fixes applied. Versions are listed under the run they come from; "
               "the evaluation of a version shows each measure's change against the version it was made from.",
}

MODES: dict[str, str] = {
    "auto": "Decide from the input: a long text is a source, a short paragraph a premise, JSON a specification.",
    "source": "A text to make a synthetic counterpart of (the main use).",
    "premise": "A short idea to write a new story from (no source to compare with).",
    "spec": "A specification in JSON, full or partial; missing dimensions are filled in.",
}


def help_bundle() -> dict:
    return {"presets": PRESETS, "kinds": KINDS, "stages": STAGES, "policies": POLICIES, "levels": LEVELS,
            "dimension_examples": DIMENSION_EXAMPLES, "tabs": TABS, "glossary": GLOSSARY, "modes": MODES}


# Ready-made answers to "what carries over?", offered as one click in the interface (new runs and
# experiment plans). `policy` lists the dimensions; `psalm` is what the PSALM judge should find on
# the story dimensions.
_STYLE = {"writing_style": "preserve", "narrative_voice": "preserve"}
_STORY = ("character", "plot_structure", "scene_sequence", "world_building")
LEVELS: list[dict] = [
    {"key": "keep_all", "title": "Keep everything", "summary": "Same story, people, places and style, told in new words "
     "with new names.", "psalm": "function high, expression moderate (same particulars, new words)",
     "policy": {**_STYLE, **{d: "preserve" for d in _STORY}}},
    {"key": "new_people", "title": "New people and places", "summary": "Keep the plot and the style; re-invent the "
     "characters, scenes and world. The default.", "psalm": "plot kept; people, scenes and world re-invented",
     "policy": {**_STYLE, "plot_structure": "preserve", "character": "abstract", "scene_sequence": "abstract",
                "world_building": "abstract"}},
    {"key": "reinvent_story", "title": "Re-invent the story", "summary": "Keep the style; keep what every part of the "
     "story does, with new particulars.", "psalm": "function high, expression low",
     "policy": {**_STYLE, **{d: "abstract" for d in _STORY}}},
    {"key": "replace_story", "title": "Replace the story", "summary": "Keep only the style and voice; write a different "
     "story.", "psalm": "function low, expression low",
     "policy": {**_STYLE, **{d: "regenerate" for d in _STORY}}},
    {"key": "structure_only", "title": "Only the structure", "summary": "Keep the plot and the order of scenes; "
     "re-invent the style, voice, people and world.", "psalm": "plot and scenes kept, everything else re-invented",
     "policy": {"writing_style": "abstract", "narrative_voice": "abstract", "character": "abstract",
                "plot_structure": "preserve", "scene_sequence": "preserve", "world_building": "abstract"}},
    {"key": "reinvent_all", "title": "Re-invent everything", "summary": "Every dimension does what it did, with new "
     "particulars — style included.", "psalm": "function high, expression low on all six",
     "policy": {d: "abstract" for d in ("writing_style", "narrative_voice", *_STORY)}},
    {"key": "replace_all", "title": "Replace everything", "summary": "Only the length and the number of chapters carry "
     "over: a new story in a new style.", "psalm": "function low, expression low on all six",
     "policy": {d: "regenerate" for d in ("writing_style", "narrative_voice", *_STORY)}},
]
