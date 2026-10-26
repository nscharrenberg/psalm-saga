# Experimental setup

This document specifies the experiments that test whether PSALM-SAGA produces synthetic
counterparts of literary texts that can stand in for the originals as research data. It is
written as the experimental-setup section of a paper: hypotheses, materials, conditions,
measures, procedure and analysis. How this design differs from the earlier PSALM-SAGA study,
and why, is in [Appendix: from the v1 to the v2 design](APPENDIX_V1_V2.md). References are in
[REFERENCES.md](REFERENCES.md).

## 1. Hypotheses

Let *T* be a source text, *S* = SAGA(*T*, π) its synthetic counterpart under transformation
policy π, and φ a property of a text measured by a fixed procedure (§4). A property is
*declared* when π preserves the dimension it belongs to.

- **H1 Fidelity.** For declared properties, φ(*S*) agrees with φ(*T*) more closely than
  φ(*S'*) does for *S'* the counterpart of a different text, and within a pre-registered
  margin of the run-to-run noise of SAGA itself.
- **H2 Distance.** *S* contains no verbatim span of *T* of 12 words or more, no original
  proper names, and less non-literal reuse of *T*'s concrete particulars, and less
  recoverable wording, than a paraphrase of *T*.
- **H3 Corpus validity.** Across a corpus {*T*ᵢ}, analyses run on {*S*ᵢ} reach the same
  conclusions as on {*T*ᵢ}: books are ranked alike per property, between-book variation is
  kept, pre-registered group differences and correlations replicate, and a classifier
  trained on synthetic texts transfers to originals.
- **H4 Trade-off.** SAGA is not dominated on fidelity × distance by the two obvious
  alternatives (paraphrasing the source; one-step rewriting), and its components (the
  specification, the review loop) each contribute measurably.

The claim is about the text as **data for the declared properties**. It is not a claim that
*S* can replace reading *T*, nor a legal verdict: the distance measures are evidence for a
legal assessment by the library, which decides where on the trade-off curve (§3.3) it sits.

## 2. Materials

**Public-domain development and test corpus.** Dutch (DBNL) and English (Project Gutenberg)
prose fiction, 1840–1930, stratified by period, length (short stories, novellas, novels of
60k–150k words) and author gender; 40 items (20 per language), of which 8 are held out for
development and prompt tuning and never used in the reported results. Public-domain texts
allow the leakage results, the texts and the synthetic counterparts to be published and
re-examined. Because well-known public-domain texts are likely to have been seen by the
generator in training (Chang et al., 2023; Cooper et al., 2025), the distance test on this
corpus is conservative: memorisation can only increase measured leakage.

**In-copyright pilot.** 10–20 in-copyright Dutch novels from the KB collection, run on the
library's infrastructure with a locally hosted open-weight generator. Only aggregate
measurements leave the library. This is the population the claim concerns.

**Metadata.** Per item: year of first publication, period (two bins), author gender, genre
label and language. Metadata drive the corpus-level analyses (H3) and are fixed before any
synthetic text is generated.

## 3. Conditions

### 3.1 Systems

| Condition | Description | Purpose |
|---|---|---|
| SAGA | full pipeline: analysis, specification, transformation, hierarchical planning, drafting, calibrated review, leakage guard | the system under test |
| SAGA − review | review and repair disabled | contribution of the review loop |
| SAGA − spec | drafting from the transformed story skeleton without the dimension specification | contribution of the specification |
| SAGA − conform | no numeric rhythm targets in drafting, no conformance step (`no_conform`) | contribution of measured style steering |
| Paraphrase | the generator rewrites the source passage by passage with new names | high-fidelity, high-leakage reference; the naive way to make a synthetic corpus |
| One-step rewrite | the generator rewrites the whole source in one instruction | the "just ask the model" reference |
| Agents' Room | multi-agent long-form generation from the same specification (Huot et al., 2024); short items only | literature reference for long-form generation |

The two baselines see the source text when writing; SAGA's writer does not (clean-room
boundary). This is the contrast H2 and H4 test.

### 3.2 Generators and judge

Two generator families: one frontier API model and one open-weight model that the library can
host. A third family serves as judge, so that no judge rates text from its own family. All
judge calls run at temperature 0; generators use their defaults.

### 3.3 Transformation policies

The policy fixes, per dimension, whether it is preserved, abstracted (function kept,
particulars replaced) or regenerated. Three policies are run with SAGA on all items:

| Policy | Writing style, narrative voice | Plot structure | Character, scene sequence, world |
|---|---|---|---|
| conservative | preserve | preserve | preserve (names replaced) |
| default | preserve | preserve | abstract |
| aggressive | preserve | abstract | regenerate |

Plotting fidelity against distance per policy gives an operating curve rather than one point.

### 3.4 Replicates

Every item is run once per condition and generator. SAGA (default policy) is run a second
time on a random 20% of items; the difference between the two runs gives the noise floor of
every measure (§6.3).

## 4. Measures

All measures are computed with the same code on *T* and *S*. Deterministic measures come
first; model judges are used only where no deterministic measure exists, and are validated
against human raters (§5.3). Each measure is listed with the property it operationalises and
the work that establishes the property as a research object or the measure as valid.

### 4.1 Property catalogue

The properties are chosen from what computational literary studies measure in fiction, so
that H3 is tested on the analyses researchers actually run:

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

### 4.2 Fidelity (H1)

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
| KG | Realised structure | the story-knowledge graph re-extracted from *S* is aligned with that of *T* (renames, inflection-aware name matching, content-based alignment of scenes and events): recall of characters, places, events, causal links, social relations and relations to places and objects, raw and relative to the ceiling of a second analysis of *T* | deterministic after extraction |
| C1 | Design coverage | share of each chapter's design facts (events, causes, relations, places/objects) the verifier finds realised; diagnostic, not independent of generation | judge (internal) |
| J1 | Same story | judge compares chapter summaries of *T* and *S* (same analysis), rates 1–5 overall and per chapter, at the level the policy declares | judge |
| J2 | Same style | judge compares three name-masked excerpts of each text, rates 1–5 | judge |
| J3 | PSALM dimensions | judge compares the texts (in full up to 6,000 words each, else aligned excerpts plus chapter summaries) on the 6 dimensions × 6 aspects; per aspect: description of both, short evidence from both, reasoning, function and expression similarity (1–5), confidence. Fidelity = mean function similarity over non-regenerated dimensions; appropriation = mean expression similarity on surface aspects of abstracted/regenerated dimensions | judge |

The run-level judges (J1–J3) are optional (`judges.enabled`, `judges.model`, `judges.instruments`); in an
experiment, enable them in `overrides` with a judge model of another family than every generator, so that
`score.psalm_fidelity` etc. appear in `results.csv`.

### 4.3 Distance (H2)

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

### 4.4 Corpus validity (H3)

Computed across items, separately per condition and generator, on the property profiles.

| Id | Measure | Operationalisation |
|---|---|---|
| R1 | Rank agreement | Spearman ρ between φ(*T*ᵢ) and φ(*S*ᵢ) across items, per property, with 95% bootstrap CI |
| R2 | Dispersion ratio | sd φ(*S*) / sd φ(*T*) across items; < 1 means the synthetic corpus is more homogeneous (Padmakumar & He, 2024; Shumailov et al., 2024) |
| R3 | Analysis replication | the pre-registered analyses (group differences, correlations with metadata) are run on both corpora; estimates with bootstrap CIs, sign agreement, whether the synthetic estimate lies inside the original's CI |
| R4 | Distinguishability | propensity-score mean squared error (pMSE; Woo et al., 2009; Snoke et al., 2018) of a logistic classifier separating original from synthetic profiles, as a ratio to its null expectation; grouped cross-validated accuracy |
| R5 | Classifier transfer | train on synthetic, test on real (TSTR; Esteban et al., 2017) against train on real, test on real: a metadata label (period) predicted from chapter profiles, leave one book out |

Pre-registered analyses for the main study (fixed in `experiments/kb_main.yaml` before the
main run): sentence length by period; dialogue share against year; women's share of
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

### 5.3 Human validation

On a stratified subset of 30 items (by language, length and condition), two raters per item
(a) answer the F4 question on the two specifications, (b) rate D3 on the same chapter pairs,
and (c) read *S* for anything recognisably lifted from *T*. Agreement between raters
(Krippendorff's α) and between raters and the judge is reported; a judge instrument whose
agreement with the raters falls below the raters' agreement with each other by more than
0.1 is reported but not used for H1/H2 decisions.

## 6. Analysis

### 6.1 Per-item comparisons (H1, H2, H4)

For every measure, the per-item paired difference between SAGA and each other condition,
with 95% bootstrap CIs over items (percentile method, fixed seed) and medians next to means (leakage is
heavy-tailed). The fidelity × distance scatter per condition is reported with its Pareto
frontier. Families of comparisons are corrected with Holm's method.

### 6.2 Decision rules (pre-registered after the pilot)

| Hypothesis | Supported if |
|---|---|
| H1 | for each declared property, SAGA's agreement is within the equivalence margin of the null replicate (two one-sided tests at α = 0.05), and F1b top-1 accuracy is above chance |
| H2 | longest copied span < 12 words for ≥ 95% of items, no names leaked, D3 below the paraphrase baseline and below a pre-registered rate per 1,000 words, D5 identification and recovered overlap no better than for the paraphrase baseline |
| H3 | R1 lower CI bound > 0.7 for the style properties; R2 CI includes 1 or exceeds 0.8; ≥ 3 of 4 analyses replicate; TSTR/TRTR ≥ 0.9 |
| H4 | SAGA lies on the Pareto frontier for every generator; each ablation is worse on at least one primary measure with a CI excluding zero |

Margins and thresholds are fixed after the pilot on the development items and before the
main run.

### 6.3 Noise floor

The difference between the two SAGA runs on the replicate items sets the noise floor of each
measure. Differences between conditions smaller than the floor are not interpreted.

## 7. Threats to validity

- **Steered features.** The conform step steers sentence and paragraph length, speech share and
  punctuation toward the source's values, so agreement on exactly those features (part of F1) is
  partly by construction. The function-word profile (F1b), character-trigram divergence (D4),
  the full length distributions and the judge instruments are not steered and carry the evidence
  about style; the `no_conform` ablation shows what steering adds.
- **Shared extractor.** F4 and KG use the same model-based analysis on *T* and *S*; a
  systematic extractor error appears on both sides and inflates agreement. The deterministic
  measures (F1–F3, F6, F7) and the human subset do not share this dependency.
- **Generator memorisation.** On famous public-domain texts the generator may reproduce the
  original from memory; this works against SAGA on H2 and is the reason for the in-copyright
  pilot.
- **Judge bias.** Judges may prefer text of a particular style or length; the judge family is
  disjoint from the generators, presentation order is randomised, and judges are validated
  against humans (§5.3).
- **Small corpora for H3.** With 20 items per language, rank correlations have wide
  intervals; CIs are reported rather than point estimates alone, and the corpus measures are
  repeated per language.
- **Property choice.** The catalogue (4.1) covers properties with established measurement.
  Properties outside it (imagery, intertextuality, humour) are not claimed and are listed as
  unmeasured in each release's datasheet.

## 8. Reproduction

```bash
saga experiment experiments/offline_demo.yaml          # the whole loop offline, no cost
saga experiment experiments/kb_main.yaml --dry-run     # list jobs
saga experiment experiments/kb_main.yaml               # resumable; re-run to continue
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

Green ≥ 0.80, orange ≥ 0.60 unless a measure states its own cut-offs; c is chosen so these fall at the
working thresholds. The full list with every formula is `psalm_saga/eval/grading.py` (and the web app's
"how is this computed?").

**Core set** (`grading.CORE`), the measures compared across conditions; everything else is supporting detail:
length ratio, form, stylometric drift, sentence-length distribution, events / causal links / characters realised (KG,
relative to the ceiling), character salience, design coverage, same story (J1), PSALM dimension fidelity (J3),
8-word overlap, longest copied span, leaked names (judge measures only when the judges are enabled). `question.<group>` in `results.csv` is the mean core score per question. The report leads with
these two tables; the primary measures of the decision rules (§6.2) are the core measures' raw values.

## Calibration of grades

Every evaluation also records two baselines (see paper §4.7.4):

- `self_agreement` — the source's first half against its second half (verse: split at a stanza break), on the style measures. Style scores are computed on the excess over this value minus a margin, so green means "within the author's own variation".
- `structure_ceiling` — a second, independent extraction of the source. KG recall is shown raw and relative to this ceiling.

Distribution grades use the KS statistic with a p-value override; measures with too few observations (gender < 10 mentions / 20 pronouns, characters < 3) and narrative measures on non-narrative sources (essays, treatises) are listed as not applicable.

Minimum samples (below them a measure is listed as not applicable, with the reason): 10 gendered mentions / 20 gendered pronouns; 3 recurring characters; 15 source mentions for chapter presence; 3 co-occurring pairs for co-occurrence overlap; 5 chapters for the chapter-length correlation. The pacing profile only follows series that vary beyond chance in the source (permutation test). Graph measures whose source-vs-source ceiling is 0 are not measurable on that text.
