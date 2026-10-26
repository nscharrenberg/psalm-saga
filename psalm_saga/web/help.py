"""Plain-language help for the web app: what every preset, stage, policy, tab and term means.

One place for the wording, served with /api/meta, so the interface explains itself the same way
everywhere (tooltips, info buttons, the help panel). Written for a researcher who has not read the
code or the paper.
"""

from __future__ import annotations

PRESETS: dict[str, dict] = {
    "full": {"title": "Full pipeline", "kind": "main", "recommended": True,
             "summary": "Analyse the source, decide per dimension what carries over, plan, write chapter by chapter, "
                        "match the source's measured style, check against the plan and the story design, remove any "
                        "copied wording, and evaluate.",
             "when": "The default for producing a synthetic counterpart of a text."},
    "fast": {"title": "Quick test", "kind": "quick",
             "summary": "The full pipeline with the expensive checks left out (no alias merging, no review) and a small "
                        "model for the analysis. Cheaper and faster, lower quality.",
             "when": "Trying settings or a new text before a real run."},
    "no_review": {"title": "Without review (ablation)", "kind": "ablation",
                  "summary": "The full pipeline without the review-and-repair step.",
                  "when": "Experiments: what does the review step contribute?"},
    "no_spec": {"title": "Without specification (ablation)", "kind": "ablation",
                "summary": "No dimension specification: the story is planned from the chapter outline only.",
                "when": "Experiments: what does the specification contribute?"},
    "no_conform": {"title": "Without style matching (ablation)", "kind": "ablation",
                   "summary": "The full pipeline without the step that steers the prose towards the source's measured "
                              "rhythm (and without numeric style targets for the writer).",
                   "when": "Experiments: what do measured style targets contribute?"},
    "flat_spec": {"title": "One call from the specification (baseline)", "kind": "baseline",
                  "summary": "Analyse and transform as usual, then write the whole story in one call from the "
                             "specification and outline — no planning, no review.",
                  "when": "Experiments: what do planning and review add?"},
    "flat": {"title": "One call from the source (baseline)", "kind": "baseline",
             "summary": "The model gets the source and is asked for a synthetic counterpart in one call. No analysis, "
                        "specification, plan or review; no copy guard.",
             "when": "Experiments: the naive approach every method should beat."},
    "paraphrase": {"title": "Rename and paraphrase (baseline)", "kind": "baseline",
                   "summary": "Rename the characters and places, then paraphrase the source passage by passage. Keeps the "
                              "structure trivially; the question is how much wording leaks.",
                   "when": "Experiments: the naive synthetic-corpus method."},
    "agents_room": {"title": "Agents' Room (baseline)", "kind": "baseline",
                    "summary": "A published multi-agent story-writing method (Huot et al., 2024): planners for conflict, "
                               "character, setting and plot, then writers per part of the story arc.",
                    "when": "Experiments: comparison with a state-of-the-art generation method."},
}

KINDS = {"main": "Recommended", "quick": "For trying things out", "baseline": "Baselines (for experiments)",
         "ablation": "Ablations (for experiments)"}

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
                "what": "Measures each chapter's rhythm (sentence lengths and their spread, paragraphs, dialogue, "
                        "punctuation; lines, stanzas and rhyme for verse) and asks for a revision towards the source's "
                        "numbers. A revision is kept only if it gets closer without changing length, language or content.",
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
                "what": "Analyses the finished synthetic text with exactly the same procedure as the source, and the "
                        "source a second time, so the evaluation can compare like with like and knows how much of any "
                        "difference is analysis noise.",
                "produces": "story bible of the synthetic text, second analysis of the source", "calls": "one per passage, twice"},
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
                         "of character, scene or world playing the same role, with different specifics."},
    "regenerate": {"title": "Replace", "short": "freely replaced",
                   "what": "The dimension is written anew, without following the source. Measures for it are then "
                           "not expected to match."},
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
    "bible": "The story bible as a knowledge graph — characters, places, scenes, events and how they connect — for the "
             "source, the design the writer worked from, and comparisons between them.",
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
    "second analysis (calibration)": "The source analysed a second time with the same procedure. Two analyses never "
                                     "agree fully; their agreement is the best any comparison can show.",
    "ceiling": "How far the source's second analysis agrees with the first. Graph scores are shown relative to it.",
    "self-agreement": "The source's first half compared with its second half. No synthetic text can match the author "
                      "more closely than the author matches themself, so style thresholds allow for it.",
    "score": "Every measure converted to 0–1 where 1 is best, with its formula shown. Green ≥ 0.80, orange ≥ 0.60 "
             "unless the measure says otherwise.",
    "judge": "A language model asked a precise question (does this tell the same story?) and to rate it 1–5. Optional, "
             "and best with a model of a different family from the one that wrote the text.",
    "PSALM judge": "A judge that compares the two texts on the six dimensions and their 36 aspects. For each aspect it "
                   "describes both texts, quotes short evidence, argues its verdict and rates function (does it do the "
                   "same thing?) and expression (are the concrete particulars the same?) separately.",
    "core measure": "One of the compact set of measures used to compare conditions in experiments.",
    "fix": "A targeted redo suggested by the evaluation. It makes a new version of the run (the original stays as it "
           "was) and redoes everything from the stage it names, so the two versions can be compared and the better "
           "one kept. Versions are marked, because their measurements are no longer independent.",
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
    return {"presets": PRESETS, "kinds": KINDS, "stages": STAGES, "policies": POLICIES,
            "dimension_examples": DIMENSION_EXAMPLES, "tabs": TABS, "glossary": GLOSSARY, "modes": MODES}
