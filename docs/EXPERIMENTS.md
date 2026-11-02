# Experimental setup

This document specifies the experiments that test whether PSALM-SAGA produces synthetic
counterparts of literary texts that can stand in for the originals as research data. It is
written as the experimental-setup section of a paper: hypotheses, materials, conditions,
measures, procedure and analysis. How this design differs from the earlier PSALM-SAGA study,
and why, is in [Appendix: from the v1 to the v2 design](APPENDIX_V1_V2.md). References are in
[REFERENCES.md](REFERENCES.md).

## 1. Hypotheses

The paper's Section 4 is the authoritative version of this design; this document maps it onto
the implementation. The experiments ask whether a language model, steered by measurements of
the properties a researcher needs, keeps those properties, and whether the transformation
policy controls what a judge finds.

- **H1 Steering by the data properties.** With the same design, the full procedure keeps the
  properties it measures and corrects (sentence- and paragraph-length distributions; the
  design's events and causal links) better than the same procedure without the
  measure-and-correct loop (`no_feedback`), under every policy setting, with no loss on the
  unsteered frequent-word profile.
- **H2 Knowledge graph.** Writing from the story graph realises more of the design's events,
  causal links, characters and relations, and keeps character salience better, than writing
  without the graph (`no_graph`).
- **H3 Policy control (PSALM).** On the story dimensions: *re-invent* keeps the function and
  lowers the expression compared with *preserve*; *replace* lowers the function as well. The
  style dimensions keep their function under every setting.
- **H4 Against renaming and paraphrase.** Under *preserve*: not worse than paraphrase on the
  retained properties beyond a margin, and less of the source's protected expression (8-gram
  overlap, longest shared span, PSALM expression).
- **H5 Against a single call.** Better retention and closer adherence to the policy (share of
  PSALM ratings in the expected range) than one call given the source and the policy, with
  copying not worse.

The claim is about the text as **data for the declared properties**. It is not a claim that
*S* can replace reading *T*, nor a legal verdict.

## 2. Materials

**Public-domain development and test corpus.** Dutch (DBNL) and English (Project Gutenberg)
prose fiction, 1840–1930, stratified by date of first publication (1840–1884, 1885–1930), length (short stories, novellas, novels of
60k–150k words) and author gender; 40 items (20 per language), of which 8 are held out for
development and prompt tuning and never used in the reported results. Public-domain texts
allow the leakage results, the texts and the synthetic counterparts to be published and
re-examined. Because well-known public-domain texts are likely to have been seen by the
generator in training (Chang et al., 2023; Cooper et al., 2025), the distance test on this
corpus is conservative: memorisation can only increase measured leakage.

**Metadata.** Per item: year of first publication, author gender, genre
label and language; `period` (early / late) is derived by splitting at the median year
(`period_split` in the plan). Metadata drive the corpus-level analyses (secondary) and are fixed before any
synthetic text is generated.

## 3. Conditions

### 3.1 Setups

| Setup (plan name) | Preset | Writer sees | Purpose |
|---|---|---|---|
| `full` | `full` | specification, story graph, plan, measured style; drafts measured and corrected | reference |
| `no_graph` | `no_graph` (`use_graph: false`) | specification, chapter synopses, measured scene shapes; drafts measured and corrected | H2 |
| `no_feedback` | `no_feedback` (conform and review off) | specification, story graph, plan, measured style stated once | H1 |
| `paraphrase` | `paraphrase` | the source, passage by passage, with renamed entities | H4 |
| `single_call` | `flat` (told the policy per dimension) | the source and the policy, one generation | H5 |

### 3.2 Policy settings

Every setup except `paraphrase` runs under each setting (`policies:` in the plan; a condition
`full` becomes `full@preserve`, `full@reinvent`, `full@replace`):

| Setting | Style, voice | Character, plot, scenes, world | PSALM function / expression expected |
|---|---|---|---|
| preserve | preserve | preserve | 4–5 / 3–4 |
| reinvent | preserve | abstract | 4–5 / 1–2 |
| replace | preserve | regenerate | 1–2 / 1–2 |

### 3.3 Models

Writers: Mistral Large 4 (`mistral/mistral-large-4-0`, API) and Gemma 4 E4B
(`ollama_chat/gemma4:e4b`, local, 128k context). Judges: Claude (primary; decides the grades),
an OpenAI model and Qwen3.5-397B-A17B (self-hosted) as the agreement panel on the full
procedure's runs (`judges.panel` on `full`; reused by `judge.check_models`). No judge shares a
family with a writer.

### 3.4 Samples

The full procedure runs k = 3 times per item, writer and setting; the other setups once.
32 test items × 2 writers × 19 samples = 1,216 runs.

## 4. Measures

**Primary and secondary measures.** The hypotheses are decided on a small, pre-specified set of
primary measures (paper, Section 4.2, Table 1); everything else below is secondary: computed for
every run, reported in the appendix, used to explain results and never to decide them. Two of
them are steered on purpose (H1 claims that steering keeps them); the unsteered ones check that
the property, not only its measurement, survives.

| Label (paper) | Primary measure | Steered by | Key (`value.<key>` in results.csv) |
|---|---|---|---|
| R1 | KS distance of sentence- and paragraph-length distributions | conform | `sentence_overlap`, `paragraph_overlap` |
| R2 | recall of the design's events and causal links | review checklist | `kg_events`, `kg_causes` |
| R3 | recall of the design's characters and relations | review checklist | `kg_characters`, `kg_social` |
| R4 | salience: Spearman ρ of mention counts | none | `salience` |
| R5 | frequent-word cosine per text; Cosine Delta attribution (corpus) | none | `fw_cosine`; corpus `F1b_cosine_delta` |
| J1 | PSALM function / expression on story and style dimensions (1–5); share in expected range | none | `psalm.function.story`, `psalm.expression.story`, `psalm.function.style`, `psalm.in_range` |
| L1 | longest shared span; 8-gram overlap | guard (≥ 10 words) | `span`, `ngram8` |
| G1, G2 | language, form, length, invented names; blind pairwise quality vs the single call | — | `length_ratio`, `form_match`, `names`; `judge.quality.win` |

These are `grading.CORE`, marked *core* in the web app. The instrument descriptions below cover
both primary and secondary measures; F4 (specification recovery), F5 and F8, D3–D5, R1, R4 and R5,
C1 and J1–J2 are secondary.

All measures are computed with the same code on *T* and *S*. Deterministic measures come
first; model judges are used only where no deterministic measure exists, and are validated by
agreement among three judges and known-answer anchors (§5.3). Each measure is listed with the property it operationalises and
the work that establishes the property as a research object or the measure as valid.

### 4.1 Property catalogue

The properties are chosen from what computational literary studies measure in fiction, so
that the corpus analyses are the ones researchers actually run:

| Property family | Representative research | Instruments |
|---|---|---|
| Style and stylometry | Burrows (2002); Evert et al. (2017); van Cranenburgh & Bod (2017) | F1, F1b, D4 |
| Narrative structure and pacing | Underwood (2018); Piper, So & Bamman (2021) | F2, F4 |
| Characters and their networks | Elson et al. (2010); Bamman et al. (2014); Labatut & Bost (2019) | F3, F4 |
| Gender representation | Underwood, Bamman & Lee (2018) | F7 |
| Emotional arc | Reagan et al. (2016) | F8 |
| Language variety (historical spelling, dialect) | a requirement of the KB's historical Dutch holdings rather than a CLS measure; see the methodology | F6 |

Every per-text measure contributes one or more numbers to the run's property profile
(`evaluation.json → features`), which is what the corpus-level measures (4.4) operate on.

### 4.2 Fidelity (retention: H1, H2, H4, H5)

| Id | Measure | Operationalisation | Type |
|---|---|---|---|
| F1 | Stylometric agreement | mean symmetric relative difference over 10 features (sentence and paragraph length and spread, word length, MATTR, dialogue share, question share, comma rate, first- and third-person pronoun rates) | deterministic |
| F1b | Stylistic proximity | Cosine Delta over the 300 most frequent words, proper names excluded, z-scored on the originals (Evert et al., 2017): rank of *T* among all originals by distance to *S*; top-1 accuracy against chance 1/n. Per text: cosine of most-frequent-word profiles | deterministic, corpus |
| F2 | Structure | equal chapter count; Pearson r of chapter lengths; share of chapters with the same scene count | deterministic |
| F3 | Character network | Spearman ρ of character salience (mentions); Pearson r of character × chapter presence; Jaccard of co-occurrence edges, names mapped through the rename table | deterministic |
| F4 | Specification recovery | the analysis stage is re-run on *S*; a judge compares σ(*T*) and σ(*S*) per sub-dimension (same / partial / different) at the level the policy declares. The judge reads two specifications, never two books, which keeps it feasible for novels | judge |
| F5 | Direct dimension similarity | 1–5 rating per dimension on paired excerpts; short items and spot checks only | judge |
| F6 | Language variety | share of verified variety marker forms among all marker occurrences in *S* vs *T*; retention = ratio | deterministic |
| F7 | Gender representation | share of character mentions referring to women (gender from extraction), and share of gendered pronouns that are feminine; absolute difference *S* − *T* | deterministic |
| F8 | Emotional arc | valence of 10 evenly spaced passages, rated separately on *T* and *S*; Pearson r between arcs (LLM sentiment rating: Zhang et al., 2024) | judge |
| F2 | (pacing) | per unit, mean sentence length and direct-speech share, z-scored, correlated *T*–*S*; only series that vary beyond chance in *T* (permutation test) | deterministic |
| KG | Realised structure | *S* is analysed once and its graph aligned with the design graph (same ids as *T*'s graph): rules, then a model pairing of remaining entities and of scenes/events per chapter, then a model check of the chapter text for design items still unmatched (with evidence). Recall of characters, places, events, causal links, social relations and relations to places and objects; through the design ids, every item of *T* is marked kept / changed / lost. Optional: relative to the ceiling of a second analysis of *T* (`stages.recover.params.calibrate=true`) | extraction + model alignment |
| C1 | Design coverage | share of each chapter's design facts (events, causes, relations, places/objects) the verifier finds realised; diagnostic, not independent of generation | judge (internal) |
| J1 | Same story | judge compares chapter summaries of *T* and *S* (same analysis), rates 1–5 overall and per chapter, at the level the policy declares | judge |
| J2 | Same style | judge compares three name-masked excerpts of each text, rates 1–5 | judge |
| J3 | PSALM dimensions | judge compares the texts (in full up to 6,000 words each, else aligned excerpts plus chapter summaries) on the 6 dimensions × 6 aspects; per aspect: description of both, short evidence from both, reasoning, function and expression similarity (1–5), confidence. Fidelity = mean function similarity over non-regenerated dimensions; appropriation = mean expression similarity on surface aspects of abstracted/regenerated dimensions | judge |

The run-level judges (J1–J3) are optional (`judges.enabled`, `judges.model`, `judges.instruments`); in an
experiment, enable them in `overrides` with a judge model of another family than every generator, so that
`score.psalm_fidelity` etc. appear in `results.csv`.

### 4.3 Distance (H4, H5)

| Id | Measure | Operationalisation | Type |
|---|---|---|---|
| D1 | Verbatim overlap | share of *S*'s word 5- and 8-grams found in *T*; longest shared span; number of spans ≥ 12 words | deterministic |
| D2 | Name leakage | original proper names (and their aliases) present in *S* | deterministic |
| D3 | Non-literal reuse | on three aligned chapter pairs, a judge lists close paraphrases and concrete particulars of *T* carried into *S* (cf. non-literal copying in Chen et al., 2024); items per 1,000 words | judge |
| D4 | Distributional divergence | Jensen–Shannon divergence of character-trigram distributions, names masked (Chim et al., 2025) | deterministic |
| D5 | Reconstruction attack | an attacker model sees two 400-word excerpts of *S* and tries to name the work and write the original passage; scored by 5-gram overlap with *T* above that of *S* itself, longest recovered span, and whether title or author were identified | judge + deterministic |

D4 is reported in both directions: too low means *S* is distributionally a copy, too high
means the style was lost (F1). It is interpreted against the paraphrase baseline and the
noise floor.

### 4.4 Corpus validity (secondary)

Computed across items, separately per condition and generator, on the property profiles.

| Id | Measure | Operationalisation |
|---|---|---|
| R1 | Rank agreement | Spearman ρ between φ(*T*ᵢ) and φ(*S*ᵢ) across items, per property, with 95% bootstrap CI |
| R2 | Dispersion ratio | sd φ(*S*) / sd φ(*T*) across items; < 1 means the synthetic corpus is more homogeneous (Padmakumar & He, 2024; Shumailov et al., 2024) |
| R3 | Analysis replication | the pre-registered analyses (group differences, correlations with metadata) are run on both corpora; estimates with bootstrap CIs, sign agreement, whether the synthetic estimate lies inside the original's CI |
| R4 | Distinguishability | propensity-score mean squared error (pMSE; Woo et al., 2009; Snoke et al., 2018) of a logistic classifier separating original from synthetic profiles, as a ratio to its null expectation; grouped cross-validated accuracy |
| R5 | Classifier transfer | train on synthetic, test on real (TSTR; Esteban et al., 2017) against train on real, test on real: a metadata label (period) predicted from chapter profiles, leave one book out |

Pre-registered analyses for the main study (fixed in `experiments/kb_main.yaml` before the
main run): sentence length against year; dialogue share against year; women's share of
character mentions against year; women's share by author gender.

### 4.5 Guardrails

| Id | Measure | Operationalisation |
|---|---|---|
| G1 | Language and length | detected language equals the input language; word count ÷ target |
| G2 | Quality | blind pairwise preference against the one-step rewrite, order randomised per item |
| G3 | Cost | tokens, cost and wall-clock time per stage, per run |

## 5. Procedure

### 5.1 Generation

Each job (item × condition × generator × replicate) is a run directory with a deterministic
id; runs are resumable, every intermediate artefact is stored, and token use, cost and time
are recorded per stage. Prices are pinned in the plan so that cost figures are reproducible.

### 5.2 Measurement

The deterministic measures are computed at the end of every run. Judge instruments and the
re-extraction for F4 and KG run after generation with the judge model; the corpus measures
run once all jobs of a condition are finished. Nothing in the measurement reads the
configuration of the condition except the declared policy (F4, D3).

### 5.3 Validity of the model-based measures (no human raters)

The study uses no human raters. The model-based primary measures are validated inside the
experiment (paper, Section 4.5; `psalm_saga/eval/validity.py`; judge instruments `psalm_check`,
`psalm_anchor`, `alignment_anchor`):

- **Agreement.** Two further judges (`judge.check_models`: OpenAI and a self-hosted open-weight
  model, Qwen3.5-397B-A17B), each of a family other than the writers' (Mistral, Gemma) and the primary judge's
  (Claude), repeat the PSALM judgement on every item of the full procedure; Krippendorff's α
  (interval) across all three judges and pairwise against the primary judge, on function and
  expression ratings. α < 0.667: reported, not used for decisions; α ≥ 0.8: reliable. The mean
  rating of the three judges (`validity.panel.*`) is reported as a sensitivity analysis.
- **Lower anchors.** The PSALM judge on two unrelated sources of the corpus (function and
  expression should be low); the alignment of one item's design against another item's synthetic
  text (event recall should be near zero). The paraphrase condition is the upper anchor.
  A measure decides a hypothesis only if its anchors are separated by at least [0.5].

Results are in `summary.json → corpus.validity` and per run in `results.csv` (`validity.*`).

## 6. Analysis

The tests are part of the plan (`hypotheses:` in `experiments/kb_main.yaml`, 64 per writer)
and run by `psalm_saga/experiments/hypotheses.py` after the runs: item means over samples,
paired differences oriented so that positive favours the first condition, 10,000 bootstrap
resamples over items, one-sided p-values, Holm within each family and writer, α = 0.05.
Test types: `superiority`, `non_inferiority` (margin), `equivalence` (TOST), `above` / `below`
(one sample) and `share_below` (a share of samples, e.g. the 12-word span criterion).
`hypotheses: default` generates the paper's five families from the setups' presets and the
policy settings. Results: `summary.json → hypotheses` and the *Hypotheses* table in
`report.md`.

Margins (pre-registered after the pilot): KS distance 0.05, recall 0.05, Spearman 0.1, PSALM
rating 0.5, frequent-word cosine 0.02, longest span 2 words.

Secondary: corpus analyses (R3 replication with TOST, dispersion ratio), Cosine Delta
attribution, run-to-run variation of the full procedure, cost and time per stage.

## 7. Threats to validity

- **Steered features.** The conform step steers the sentence- and paragraph-length
  distributions, and review checks the design's events and causal links; H1 measures exactly
  these, on purpose. The frequent-word profile (F1b), character salience and the judges are not
  steered and show whether the property survives or only its measurement.
- **Small writer.** Gemma 4 E4B cannot read a whole novel (128k context); the single call
  then sees a truncated source (recorded). Results for the small writer are what a library can
  run on its own hardware, not the method's ceiling.
- **Priorities.** Measure priorities (`priorities`) raise the generation's effort on chosen
  measures and weight them when a stage chooses between revisions. All conditions of an
  experiment run with the same priorities (default: none); a condition with priorities is a
  different condition and is reported as such.
- **Shared extractor.** F4 and KG use the same model-based analysis on *T* and *S*; a
  systematic extractor error appears on both sides and inflates agreement. The deterministic
  measures (F1–F3, F6, F7) and the alignment anchors do not share this dependency.
- **Generator memorisation.** On famous public-domain texts the generator may reproduce the
  original from memory; this works against SAGA on H4 and H5, so the distance results on this corpus are conservative.
- **Judge bias.** Judges may prefer text of a particular style or length; the judge family is
  disjoint from the generators, pairwise judgements are made in both orders, and the judges are
  validated by agreement and anchors (§5.3).
- **Small corpora for the corpus analyses.** With 20 items per language, rank correlations
  have wide intervals; CIs are reported rather than point estimates alone.
- **Property choice.** The catalogue (4.1) covers properties with established measurement.
  Properties outside it (imagery, intertextuality, humour) are not claimed and are listed as
  unmeasured in each release's datasheet.

## 8. Reproduction

```bash
saga experiment experiments/offline_demo.yaml          # the whole loop offline, no cost
saga experiment experiments/kb_main.yaml --dry-run     # list jobs
saga experiment experiments/kb_main.yaml               # resumable; re-run to continue
# or in the web app: Experiment plans → kb_main (or + New experiment) → Save and start
# → experiments_out/<name>/{results.csv, summary.json, report.md, judgements.json, runs/}
```

`report.md` contains the per-condition table, per-stage cost and time, and the corpus-level
tables (R1–R5, F1b); `report.html` plots, per property, the distribution across books on the
originals and on the synthetic texts, with each book's pair joined. Per run, the evaluation
tab of the web app shows the within-text distributions (sentence, paragraph and word length,
chapter profiles, character attention, most frequent words) with histogram overlap and the
Kolmogorov–Smirnov statistic. A plan declares conditions, generators, judge instruments, the metadata
file, the pre-registered analyses (`analyses`) and the label for classifier transfer
(`tstr_label`).

## Scores and the core set

Every graded measure is also reported as a score in [0, 1] where 1 is best (`evaluation.json → grades.<key>.score`,
with the formula in `grades.<key>.formula`; `results.csv → score.<key>`):

| Raw value | Score | Example |
|---|---|---|
| share, similarity, recall (0–1, higher better) | s = x | KG recall, coverage, judges: (rating − 1) / 4 |
| correlation r | s = max(0, r) | salience, presence, pacing |
| difference or distance d (0 = identical) | s = max(0, 1 − d / c), **inverted** | KS D (c = 0.5), drift (c = 0.5), 8-gram overlap (c = 0.01), copied span (c = 40 words) |
| ratio x (1 ideal) | s = max(0, 1 − abs(x − 1) / c) | length (c = 0.5), variety retention (c = 1) |

Green ≥ 0.80, orange ≥ 0.60 unless a measure states its own cut-offs (the judges: green from 0.75 —
a rating of 4, "largely the same with minor differences" — and orange from 0.5, a rating of 3); c is chosen so these fall at the
working thresholds. The full list with every formula is `psalm_saga/eval/grading.py` (and the web app's
"how is this computed?").

**Core set** (`grading.CORE`) = the primary measures and guardrails of §4: length ratio, form, invented
names, frequent-word cosine, events and causal links realised, character salience, PSALM dimension fidelity,
8-word overlap, longest copied span, PSALM expression on changed dimensions (judge measures only when the
judges are enabled). Steered measures (stylometric drift, length distributions) and self-reported ones
(design coverage) are deliberately not in it. `question.<group>` in `results.csv` is the mean core score per question. The report leads with
these two tables; the primary measures of the decision rules (§6.2) are the core measures' raw values.

## Calibration of grades

Every evaluation also records two baselines (see paper §4.3, P1, and §4.7):

- `self_agreement` — the source's first half against its second half (verse: split at a stanza break), on the style measures. Style scores are computed on the excess over this value minus a margin, so green means "within the author's own variation".
- `structure_ceiling` — optional (`stages.recover.params.calibrate=true`): a second, independent extraction of the source; KG recall is then also shown relative to it. By default the source is analysed once and the synthetic text is aligned with the design (`recovered/alignment.json`).

Distribution grades use the KS statistic with a p-value override; measures with too few observations (gender < 10 mentions / 20 pronouns, characters < 3) and narrative measures on non-narrative sources (essays, treatises) are listed as not applicable.

Minimum samples (below them a measure is listed as not applicable, with the reason): 10 gendered mentions / 20 gendered pronouns; 3 recurring characters; 15 source mentions for chapter presence; 3 co-occurring pairs for co-occurrence overlap; 5 chapters for the chapter-length correlation. The pacing profile only follows series that vary beyond chance in the source (permutation test). Graph measures whose source-vs-source ceiling is 0 are not measurable on that text.
