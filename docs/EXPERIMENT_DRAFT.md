# Experimental Setup

## Corpus design

**Source materials:**
- 15 English stories from Project Gutenberg + 14 Dutch stories from DBNL (29 total), all public domain. Self-contained short stories, single chapters, or coherent excerpts, normalised to ~7,000 words (~41k characters); each read in full to confirm it stands as a complete scene/arc. Item list and per-item rationale: **CORPUS.md (Appendix)**.
- Stratify into 5 genre buckets per language, 3 items each, fixed before selection. Dutch Detective/Mystery has 2 items — DBNL's public-domain catalogue has no full-text representation of the genre (see CORPUS.md).
- 10 additional scratch-mode items (5 English, 5 Dutch) where the system elicits and authors a specification with human review, then generates variants. No source text.

**Specification annotation:**
- Gold specifications for all 29 source items: model draft + author rewrite for all 36 sub-dimensions
- Double-annotation on 10 items (5 per language) to establish human-to-human agreement as a ceiling for RQ3
- Log what fraction of each gold spec was machine-drafted versus human-rewritten, per sub-dimension

**Language design:**
- Two independent corpora (do not translate stories, as this overwrites Writing Style and Narrative Voice)
- Translate 6 gold specifications (3 per language) into the other language, adapting Writing Style sub-dimensions where language-specific. Log adaptations.
- Generate from these parallel specs in both languages to get a content-matched cross-language comparison without multiplying by six stories

## Generation tasks and conditions

Run three generation tasks across seven conditions:

**Conditions:**
- C1: Full pipeline (spec → plan → draft → review → repair)
- C2: −Review (spec → plan → draft, skip repair loop)
- C3: Flat+Spec (single call, spec in prompt)
- C4: −Spec (premise → plan → draft → generic review)
- C5: Flat (single call from premise)
- C6: Agents' Room baseline (if feasible; otherwise drop)
- C7: Human source items (gold standard)


**Tasks:**
- Task A: Premise → Story. All conditions generate. C1/C2 write their own spec first.
- Task B: Specification → Story. Only C1/C2/C3. Gold spec supplied directly to test spec-following without confounding it with spec-writing.
- Task C: Source story → Variants. C1 only. Extract spec from human story, generate 6 variants (one per dimension, lock the rest).
- Task D: Scratch spec → Variants. C1 only. Same as C3 but starting from an authored spec, with no extraction step. Isolates extraction error and test self-selection.

Run with 2 generator families minimum (frontier API + open-weight), optionally a 3rd EU multilingual model if it clears the pilot.

## Research questions and hypotheses

**RQ1 (Adherence)**: primary.
- H1a: Dimension identification above chance (1/6)
- H1b: Spec-story matching above chance (1/2)
- H1c: Lower accuracy for functional sub-dimensions than concrete ones
- H1d: When judges identify the correct dimension, they report no change on the locked dimensions at a rate above false-alarm baseline (test the lock)

**RQ2 (Pipeline contribution)**: primary.
- H2a: C1 > C4 on adherence (spec helps)
- H2b: C1 > C3 on adherence (pipeline helps beyond pasting spec in prompt)
- H2c: C1 > C2 on adherence (review-repair loop helps)

**RQ3 (Specification recovery)**: secondary/diagnostic.
- H3a: System-to-gold agreement ≥ human-to-human agreement (using the double-annotated ceiling)
- H3b: Recovery lower for functional sub-dimensions (mirrors H1c)
- H3c: Recovery lower in Dutch than English

**RQ4 (Quality guardrail)**: must not be negative, not a contribution.
- H4a: Full pipeline non-inferior to flat baseline by pre-registered margin (two one-sided tests)
- H4b: Adherence and quality do not correlate negatively within condition
- H4c: Human items preferred over all systems (scale anchor and instrument validity)

**RQ5 (Specification provenance)**: secondary/diagnostic.
- H5a: Adherence higher for system-authored specs than extracted specs (constraint self-selection)
- H5b: Lock fidelity higher in Task D (scratch, no extraction) than Task C (extracted)

## Evaluation instruments

Design instruments to be objective and economical. Every primary measure must have ground truth by construction.

**Mechanical checks (no judge needed):**
- Lock verification: diff source/variant spec, confirm byte-identity for locked dimensions and change for unlocked. Screen unlocked for semantic non-equivalence via embedding threshold + audit.
- Verbatim overlap: 8-gram overlap between generated story and source item vs. matched non-source baseline. Pre-registered exclusion threshold.

**Specification level:**
- Specificity screening: Binary checks on every spec value (names property? testable? commits?) to measure spec quality independently
- Recovery against gold: For each source item, judge the extracted spec against gold on a 3-level scale (matches / partially matches / conflicts or omits)

**Adherence (objective ground truth):**
- Dimension identification (A1, primary): Show source + one variant, ask which dimension was regenerated. Chance = 1/6. Includes confusion matrix and "cannot tell" option.
- Non-target drift (A2): Follow-up to A1 -- did any locked dimensions change? Hit rate + false-alarm rate, summarise as d′.
- Spec-story matching (A3): Show spec + 2 stories (one from it, one from different spec), identify correct one. Chance = 1/2. Run on Task B for H2b, Task A for H2a.
- Story-spec attribution (A4): Show story + 3 specs (true + 2 from same language/genre bucket), identify which the story was written from. Chance = 1/3. Cheaper for humans than A3. Convergent validity check when run on overlap.
- Sub-dimension recovery (A5): Show story + 4 candidate values for a sub-dimension, identify the true one. Chance = 1/4. Automatic only, subset sampling.
- Premise attribution (A6, calibration only): Show story + 3 premises, identify true one. Chance = 1/3. Not a result; establishes judge ceiling so readers can interpret the dimension-ID score.

**Quality:**
- Pairwise preference (Q1): Subset of ~174 comparisons (3 contrasts × 29 items × 2 generators, both orders). Non-inferiority margin pre-registered. Test H4b via within-condition correlation with adherence outcomes.

**Note on design:**
- All instruments with ground truth (A1–A6) run identically for model judges and humans, so agreement is directly interpretable
- Distractors drawn from real specs in same language/genre bucket, embedding-filtered for semantic distance, 10% audited
- "Cannot tell" and "I don't know" options allowed for raters to avoid false guessing
- For human raters: 5 training items with feedback, 10% catch trials (unmistakable manipulations), raters <80% excluded

## Judge and rater setup

**Model judges:** 3 families, none from generator set (design out self-preference). All produce rationales before verdicts, structured JSON output. Randomised item order, both presentation orders for pairwise tasks.

**Human raters:**
- Stratified subset, same instruments (never a separate rubric)
- Floor ~150 items, target ~300, allocated first to A1 (dimension ID), then A4 (attribution), then Q1 (quality)
- Can be authors, colleagues, crowdworkers, domain experts -- blinding and ground truth make rater identity inert
- Authors who wrote gold specs do not judge items derived from them
- Two gates before pool entry: catch-trial performance, and 95% parseable structured output on test calls

## Pilot

3 items per language through all tasks and conditions before confirmatory run. Pilot data excluded from analysis.

Pilot determines: whether open-weight models produce coherent stories and valid 36-field specs; which model judges clear performance gates; observed abstention rate on dimension ID (for sample-size check); median human time per item (to translate rater budget into item count). If a model fails, drop it and report why. This gates the EU multilingual models rather than committing in advance.

## Analysis

**Statistical approach:**
- Mixed-effects logistic regression on judgement correctness, with random intercepts for source item and judge
- Intercept offset to test against correct chance level per instrument (1/6, 1/2, 1/3, 1/4)
- Benjamini-Hochberg FDR q=0.05 within three families: dimension tests, condition contrasts, language contrasts
- Effect sizes as marginal probabilities + 95% CI + odds ratios alongside every p-value
- Convergent validity: run A3 and A4 on overlap and report correlation
- Reliability: Krippendorff's α across judges per instrument/dimension; Cohen's κ between model majority and human
- Imperfect-judge correction (Rogan-Gladen) using human subset, so ~150 human labels support valid estimates over 1000+ automatic ones

**Non-primary analyses:**
- A2 (drift) as signal-detection: hit rate on manipulated dimension vs. false-alarm on locked dimensions, summarised as d′
- H4b: within-condition correlation between quality and adherence outcomes
- Sub-dimension results from A5 flagged as exploratory

**Sample-size justification:**
- Dimension ID against 1/6 chance: 80 items per dimension (480 total from Tasks C+D) adequately powered for 0.35 accuracy after correction
- Spec-story matching against 1/2 chance: 80 items per condition across 3 conditions powered for 0.70 accuracy
- Pairwise contrasts: pre-register smallest effect size of interest (SESOI) at 15 percentage points, stating study not powered below it
- Design is deliberately better powered for RQ1 than ablation ordering (RQ2)

## Reproducibility

Freeze and publish before confirmatory run: hypotheses with primary/secondary status, SESOI, non-inferiority margins, full analysis plan (including convergence fallback and abstention handling), all source items with provenance, both gold-spec sets, double-annotated subset, scratch corpus, parallel-spec translations, model identifiers with exact revisions and decoding parameters, all prompts versioned with content hashes, item construction scripts with seeds, rater materials, raw per-judge/per-rater responses, full generation traces including abandoned runs, analysis code with environment lockfile.