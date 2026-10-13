# Experimental Setup (Summary)

A short overview of the design in [`EXPERIMENTAL_SETUP.md`](EXPERIMENTAL_SETUP.md), which is the authoritative
version. This summary deliberately states no parameter values or counts: those live only in that document's
Appendix A (values) and Appendix B (derived counts), so they change in one place. Symbols such as $N_{\text{src}}$,
$D$ and $G$ are defined in its §0.2.

## Corpus

- **Source stories** ($N_{\text{src}}$): English from Project Gutenberg, Dutch from DBNL, all public domain. Short
  stories, single chapters or coherent excerpts, each read in full to confirm it is a complete scene or arc. Stratified
  across $B$ genre buckets per language. Item list, lengths and the translated-items disclosure: CORPUS.md.
- **Length policy**: defined once, in §2.2. Generated stories match their source item's length within $\pm\delta$.
- **Gold specifications**: model draft plus author rewrite for all $S$ sub-dimensions of every source item, with the
  rewritten share logged. $N_{\text{dbl}}$ items are specified independently by two authors to set the human ceiling.
- **Scratch sub-corpus** ($N_{\text{scr}}$): no source text. The system authors the specification and generation
  proceeds from it unreviewed; an author reviews it afterwards for descriptive data only.
- **Language design**: two independent corpora, never translated from each other. Dutch is generated in Dutch, with an
  explicit language directive and an automatic check. $N_{\text{par}}$ gold specifications are translated to give a
  content-matched cross-language comparison.

## Conditions and tasks

**Conditions**: C1 Full (spec → plan → draft → review → repair), C2 No Review, C3 Flat+Spec (single call), C4 No Spec
(premise → plan → draft → generic review), C5 Flat (single call from premise), C6 Agents' Room (if feasible), C7 Human.

**Tasks**:

- **A, premise → story.** All generating conditions. C1/C2 write their own specification first.
- **B, specification → story.** C1, C2, C3 from the gold specification: following a spec, separated from writing one.
- **C, source → base and variants.** C1 extracts a specification from the human story, then generates a base story, a
  null replicate (a second story from the same specification), and $D$ variants that each regenerate one dimension and
  lock the rest. Judges compare base with variant, never the human source with a variant.
- **D, scratch → base and variants.** Task C's procedure from an authored specification: no extraction, no source.

Every task runs once per generator family ($G$).

## Research questions

| RQ  | Question                                                                                        | Status     |
|-----|-------------------------------------------------------------------------------------------------|------------|
| RQ1 | Adherence: does a story instantiate the values its specification names? (A1b, A3, A4, A5)        | Primary    |
| RQ2 | Controllability: does regenerating one dimension change that dimension and only that one? (A1, A2) | Primary    |
| RQ3 | Contribution: does the specification stage do work the rest of the pipeline does not? (A3, A4)  | Primary    |
| RQ4 | Specification production: does an extracted specification recover the gold one? (S2)            | Diagnostic |
| RQ5 | Quality guardrail: is specification-driven output non-inferior in quality? (Q1)                 | Guardrail  |
| RQ6 | Provenance: do adherence and lock fidelity depend on where the specification came from? (C vs. D) | Diagnostic |

Hypotheses H1a–H6b and the map from each to its task and instrument are in §1.

## Instruments

- **Mechanical**: M1 lock verification (locked-value changes classified as declared-expected, declared-unexpected or
  silent), M2 verbatim overlap, M3 output language and length.
- **Specification level**: S1 specificity screening, S2 recovery against gold.
- **Adherence and controllability**: A1 dimension identification on base-variant and null pairs; A2 drift on locked
  dimensions, analysed with and without the pre-specified entangled dimension pairs and against the null-pair baseline;
  A1b value check (does the variant realise the new value); A3 specification-story matching; A4 story-specification
  attribution; A5 sub-dimension recovery; A6 premise attribution (calibration only).
- **Quality**: Q1 pairwise preference, tested for non-inferiority.

All ground-truth instruments run identically for model judges and humans.

## Models and judges

Generator, judge and gold-spec drafter roles, with their disjointness constraints, are in §6.1. Model choices and the
cost estimate are in `docs/experimental_cost_estimation.xlsx` and are fixed after the pilot. Human raters judge a
stratified subset of the same instruments, allocated first to A1, then A4, then Q1.

## Pilot, analysis and reproducibility

- **Pilot** (§7): checks generators, judges, A1 abstention, human time per item, measured tokens and runtime, C6
  feasibility; freezes thresholds and the entanglement matrix.
- **Analysis** (§8): mixed-effects logistic regression with random intercepts for item and judge, offset to each
  instrument's chance level; Benjamini-Hochberg within three families; Rogan-Gladen correction from the human subset;
  A2 as signal detection.
- **Sample size** (§9, Appendix B.2) and **reproducibility** (§11) as in the full document.
