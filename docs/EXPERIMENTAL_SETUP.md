# Experimental Setup

## 0. How to Read This Document

### 0.1. Structure

The document follows the order of a preregistration: research questions and hypotheses (§1), materials (§2),
conditions (§3), generation tasks (§4), instruments (§5), models and judges (§6), pilot (§7), analysis (§8), sample size
(§9), threats (§10), reproducibility (§11) and the reduction path (§12). Appendix A holds every parameter value,
Appendix B every count derived from them, and Appendix C the decisions that are still open.

Every task (§4) and every instrument (§5) is described with the same five fields:

- **Answers**: the hypotheses it supplies evidence for.
- **Input**: what has to exist before it can run.
- **Procedure**: what is done, in enough detail to reproduce it.
- **Output**: what it produces.
- **Why this answers it**: how the output bears on the hypotheses.

### 0.2. Notation

Numbers that may change are defined once, as a symbol, and referred to by that symbol everywhere else. Their current
values are in Appendix A, and every count that follows from them is in Appendix B. To change a value, edit Appendix A
and recompute Appendix B. No other section repeats the number.

| Symbol                                                 | Meaning                                                                                 |
|--------------------------------------------------------|-----------------------------------------------------------------------------------------|
| $N_{\text{EN}}$, $N_{\text{NL}}$                       | Source items per language                                                               |
| $N_{\text{src}}$                                       | Source items in total, $N_{\text{EN}} + N_{\text{NL}}$                                  |
| $N_{\text{scr}}$                                       | Scratch items (no source text), split evenly over the two languages                     |
| $N_{\text{dbl}}$                                       | Source items whose gold specification is written independently by two authors           |
| $N_{\text{par}}$                                       | Gold specifications translated into the other language (parallel-specification subset)  |
| $B$                                                    | Genre buckets per language                                                              |
| $D$                                                    | Dimensions in the taxonomy                                                              |
| $S$                                                    | Sub-dimensions in the taxonomy (a specification answers all $S$)                        |
| $G$                                                    | Generator families (§6)                                                                 |
| $J$                                                    | Judge families (§6)                                                                     |
| $W_{\min}$, $W_{\max}$, $C_{\max}$                     | Source-item length bounds in words, and character ceiling (§2.2)                        |
| $\delta$                                               | Relative tolerance of the generation length band (§2.2)                                 |
| $\mathcal{C}_A$, $\mathcal{C}_B$                       | Generating conditions in Task A and Task B (§4)                                         |
| $n_{\text{S1}}$                                        | Specifications sampled per spec-writing mechanism for S1                                |
| $T_{\text{A3}}$, $T_{\text{A4}}$                       | A3 and A4 trials per task-condition cell                                                |
| $T_{\text{A5}}$                                        | A5 trials in total                                                                      |
| $n_{\text{A6}}$                                        | Items sampled per generating condition for A6                                           |
| $n_{\text{pilot}}$                                     | Pilot items per language                                                                |
| $H_{\text{floor}}$, $H_{\text{target}}$                | Human-judged items, minimum and target                                                  |
| $R_H$                                                  | Human raters per human-judged item                                                      |
| $\rho_{\text{catch}}$, $\theta_{\text{catch}}$         | Catch-trial rate in human materials, and the accuracy a rater needs on them             |
| $\theta_{\text{parse}}$                                | Share of parseable structured outputs a model judge needs                               |
| $\rho_{\text{audit}}$                                  | Share of automatic decisions audited by an author                                       |
| $m_{\text{Q1}}$                                        | Non-inferiority margin for quality (win rate)                                           |
| $\Delta_{\text{SESOI}}$                                | Smallest effect size of interest for condition contrasts                                |
| $\alpha$, $1-\beta$, $q$                               | Significance level, power, and Benjamini-Hochberg false discovery rate                  |
| $k_{\max}$, $\tau$                                     | Repair-loop bound and repair threshold of the pipeline                                  |
| $a_{\max}$                                             | Fresh-session attempts per generation job                                               |
| $\sigma$                                               | Master random seed                                                                      |

### 0.3. Terms and Conventions

- **Taxonomy.** The $D$ dimensions and $S$ sub-dimensions are those of the methodology section,
  which defines each sub-dimension and its criteria. This document does not restate them.
- **PSALM.** Our earlier evaluation method [[Probing Stylistic Appropriation using Large Language Models: An Evaluation Framework for Copyright Infringement under EU Law](https://arxiv.org/abs/2606.31250v1)]. It is named here only to state where it is *not*
  used (§10).
- **Word.** A whitespace-separated token of the text, as counted by Python's `len(text.split())`. This is the rule
  used for `word_count` in `corpus.csv` and for realised story length. Markdown headings count as words.
- **Job.** One generation run that produces one story (or, for a specification step, one specification) in a fresh
  agent session (§4.1).
- **Randomness.** Every random draw in this document (item sampling, distractors, presentation order,
  counterbalancing, bucket and length assignment) is made by the published construction scripts from the master seed
  $\sigma$, with one derived seed per instrument. Generation uses the providers' sampling and is not seeded unless a
  provider supports it; decoding parameters are recorded (§11).

## 1. Research Questions

Six research questions. RQ1, RQ2 and RQ3 are primary. RQ4 and RQ6 are secondary and diagnostic. RQ5 is a guardrail:
its failure would qualify the other results, but its success is not a contribution. The instruments named here are
defined in §5, and the table at the end of this section maps every hypothesis to its task and instrument.

**RQ1 (Adherence).** Does a story generated from a specification instantiate the values that specification names?

- **H1a.** Given a specification and two stories, one generated from it and one from a different specification, a blind
  judge identifies the correct story above chance (A3). The converse direction, one story and three specifications,
  is also above chance (A4).
- **H1b.** Given a variant story and two descriptions of its regenerated dimension, the value before regeneration and
  the value after, a blind judge identifies the new value above chance (A1b). This is the adherence test for variants:
  it checks that a variant moved *to the specified value*, not just that something changed.
- **H1c.** Adherence varies across sub-dimensions, and is lower for the $D$ functional sub-dimensions (the "Function"
  sub-dimension of each dimension) than for the concrete ones (A5).

**RQ2 (Controllability).** When one dimension of a specification is regenerated and the others are locked, does the
story change in that dimension and only in that dimension?

- **H2a.** Given a base story and one of its variants, a blind judge identifies which of the $D$ dimensions was
  regenerated above chance, $\frac{1}{D}$ (A1).
- **H2b.** Manipulation is specific. Across all variant pairs, judges report the regenerated dimension as changed more
  often than the locked dimensions, summarised as $d' > 0$ (A1 and A2 together, §5.3). Because dimensions are not
  independent, the test is repeated with and without the pre-specified entangled pairs (§5.3), and the locked-dimension
  false-alarm rate is compared against the null-pair baseline (§4, Task C).

**RQ3 (Contribution of the specification).** Does the specification stage do work the rest of the pipeline does not?

- **H3a.** Stories from the full pipeline instantiate a target specification more often than stories from the
  no-specification ablation given the same premise (C1 vs. C4, Task A, A3 and A4).
- **H3b.** Stories from the full pipeline instantiate a supplied specification more often than a single-call baseline
  given the same specification in its prompt (C1 vs. C3, Task B, A3 and A4). C1 uses substantially more inference-time
  compute than C3, and no compute-matched C3 is run. A positive result is therefore reported as "the full pipeline,
  architecture and compute combined, outperforms a single-call baseline", not as evidence that the pipeline's structure
  alone is responsible, and the paper's limitations say so.
- **H3c.** The review-and-repair loop improves adherence over the no-review ablation (C1 vs. C2, Task B, A3 and A4).

**RQ4 (Specification production).** When the system writes a specification from a human-written story, does it recover
the properties a human annotator recorded for that story?

- **H4a.** System-to-gold agreement is non-inferior to human-to-human agreement measured on the $N_{\text{dbl}}$
  double-annotated items (S2). The human ceiling, not an absolute threshold, is the comparison.
- **H4b.** Recovery is lower for the functional sub-dimensions than for the concrete ones, mirroring H1c. Agreement
  between H1c and H4b would locate the difficulty in the taxonomy; divergence would locate it in the pipeline.
- **H4c.** Recovery is lower in Dutch than in English. The expected mechanism, stated before the data rather than after,
  is generator training-data asymmetry (English is overrepresented relative to Dutch), consistent with our prior PSALM
  experiments (§0.3). The corpus also confounds language with item length and form (§2.1), so this contrast is adjusted for
  length (§8).

**RQ5 (Quality guardrail).** Is specification-driven output non-inferior in quality to the unstructured baselines?

- **H5a.** Full-pipeline stories are not worse than flat-baseline stories by more than $m_{\text{Q1}}$, tested by two
  one-sided tests following the equivalence approach of Scharrenberg and Sun [2026] (Q1).
- **H5b.** Adherence and quality do not correlate negatively within condition. The CS4 benchmark, which varies the
  number of constraints in a story-writing prompt, reports quality decaying as constraints accumulate
  [Atmakuru et al., 2024], so a negative correlation here would be a finding, not a
  nuisance (Q1 against A3 and A4).
- **H5c.** Human-written source items are preferred over all system conditions. This anchors the quality scale and
  checks the instrument: a null would impugn it (Q1, C1 vs. C7).

**RQ6 (Specification provenance).** Do adherence and lock fidelity depend on where the specification came from?

Task C variants descend from a specification the system *extracted* from a human story. Task D variants descend from a
specification the system *authored* from scratch. Both are generated without human review (§2.4), so the two tasks
differ only in where the specification came from.

- **H6a.** Variants from authored specifications adhere better than variants from extracted specifications (A1b and
  A1, Task D vs. Task C). A positive result quantifies constraint self-selection, the tendency of a system to specify
  what it already writes well, together with the cost of extraction error.
- **H6b.** Variants from authored specifications show higher lock fidelity than variants from extracted ones: fewer
  silent lock violations (M1) and less locked-dimension drift (A2).

The Task C vs. Task D contrast bundles two effects, extraction error and self-selection, and the design does not
separate them. S2 measures extraction error directly and is reported alongside RQ6 to help interpret it.

**Hypothesis map.**

| Hypothesis | Task(s)       | Instrument(s)   | Chance or test                           |
|------------|---------------|-----------------|------------------------------------------|
| H1a        | B             | A3, A4          | $\frac{1}{2}$, $\frac{1}{3}$             |
| H1b        | C, D          | A1b             | $\frac{1}{2}$                            |
| H1c        | see App. C    | A5              | $\frac{1}{4}$, descriptive               |
| H2a        | C, D          | A1              | $\frac{1}{D}$                            |
| H2b        | C, D          | A1 + A2         | $d'$, null-pair baseline                 |
| H3a        | A             | A3, A4          | condition contrast                       |
| H3b, H3c   | B             | A3, A4          | condition contrast                       |
| H4a–H4c    | C             | S2              | non-inferiority, contrasts               |
| H5a–H5c    | A             | Q1 (with A3/A4) | non-inferiority, correlation, preference |
| H6a, H6b   | C vs. D       | A1b, A1, A2, M1 | provenance contrast                      |

## 2. Corpus / Dataset

### 2.1. Source Stories

**Purpose.** Human-written stories serve three roles: they are the material Task C extracts specifications from, the
basis of Task A's premises and Task B's gold specifications, and the human reference condition C7.

**Composition.** $N_{\text{EN}}$ English and $N_{\text{NL}}$ Dutch items. English sources come from Project Gutenberg,
Dutch sources from the Digital Library of Dutch Literature (DBNL), all public domain within the European Union. Each
item is a self-contained short story, a single chapter, or a coherent excerpt, and every item was read in full to
confirm it stands as a complete scene or arc. Items are stratified across $B$ genre buckets per language, fixed before
selection. The item list, per-item rationale, per-bucket counts and per-language length statistics are in the
Appendix (CORPUS.md), which is the single source for those facts.

Bucket membership matters downstream, since every distractor in the attribution instruments is drawn from the same
language and bucket as the true item where possible. The smallest bucket therefore limits how many distractors an
instrument can use. A4 and A6 use two, which is why they offer three alternatives. Dutch Detective/Mystery has only two
items, so it offers one same-bucket distractor; §5.5 states how the second is drawn.

**Known properties of the corpus.** Lengths differ by language: the Dutch items are shorter on average, and several of
the shortest are verse fables and children's cautionary tales. Language is therefore confounded with item length and
form, and the language contrasts are adjusted for length (§8). Three Dutch items are Dutch translations of German
originals by Heinrich Hoffmann (CORPUS.md lists them). They are kept and disclosed, and the language contrasts are
reported with and without them (§8), since §2.5's argument against translated text applies to them.

### 2.2. Length Policy

This is the only place lengths are defined. Every other section refers here.

- **Source items** are between $W_{\min}$ and $W_{\max}$ words and at most $C_{\max}$ characters. The character ceiling
  keeps a source item, and the judge prompts that contain one or two stories, within the judges' context windows.
- **Generated stories** target the word count of the source item they derive from, within a band of $\pm\delta$. For
  Task C and its base, null and variant stories, that is the item's own source. For Task A and Task B it is the item
  whose premise or gold specification is used.
- **Scratch stories (Task D)** have no source item. Each scratch item is assigned a genre bucket, balanced across
  buckets within each language, and takes the length band of one corpus item from the same language and bucket, drawn
  with a fixed seed. Task D's length distribution then mirrors Task C's.
- **Words** are counted as defined in §0.3, on the final story text.
- **How the band reaches a condition.** Every condition receives the same length directive in its prompt: the pipeline's
  own directive text (`psalm_saga.story_length.format_length_directive`), rendered from the band with the chapter count
  left to the model. Pipeline conditions also check length in their review. Single-call conditions (C3, C5) get one
  call and no length retry.
- **Realised length** is recorded for every generated story and checked by M3 (§5.1).

**Expected consequences.** Short items exercise fewer sub-dimensions. Gold specifications mark such sub-dimensions as
*thin* rather than leaving them blank, and the number of thin sub-dimensions per item is reported. We expect lower S2
and A5 recovery on short items, and possibly lower A1 identification, since a short variant has less text in which to
show a change. Long items cost more to generate and take human raters longer to read (§7 measures rater time).

### 2.3. Gold Specifications

**Purpose.** A gold specification is a human-authored answer to all $S$ sub-dimensions for one source item. It is the
input to Task B, the target in A3 and A4 for Task A, and the reference for S2.

**Procedure.** A model from the gold-spec drafter role (§6) drafts candidate answers from the source text. An author then
reviews and rewrites every answer against the dimension criteria and records, for each answer, whether it was rewritten
and how far. This yields a machine-drafted versus human-rewritten ratio per sub-dimension, which is reported.

$N_{\text{dbl}}$ items, split evenly over the languages, are specified independently by two authors. Their agreement
shows whether the $S$ questions can be answered consistently from a text at all, and it supplies the ceiling for H4a.
Without it RQ4 would have no principled benchmark, because a gold specification is one valid description among many and
deviation from it is not straightforwardly error.

### 2.4. Scratch Sub-Corpus

**Purpose.** $N_{\text{scr}}$ items, split evenly over the languages, with no source text. They are the input to Task D,
which repeats Task C's variant procedure on specifications the system authored itself. This does three things:

- It removes the extraction step, so its variants descend from a specification that was never inferred from a human
  story. Compared with Task C, this measures what extraction costs (RQ6).
- It removes the memorisation confound. With no source text there is nothing to recall, so an adherence result that
  replicates here cannot be explained as regurgitated public-domain literature.
- It makes constraint self-selection measurable (H6a), which has not been quantified for specification-driven story
  generation.

**Procedure.** The system writes the scratch specification autonomously (C1's specification stage in scratch mode), for
an assigned language and genre bucket (§2.2). Generation proceeds from that specification **unreviewed**, so Task C and
Task D both start from specifications no human has edited. An author reviews each scratch specification afterwards and
records review time and the share of answers they would have rewritten. This characterises the interactive mode
descriptively. It is not a user study, and the review does not feed back into generation.

### 2.5. Language Design

**Purpose.** To compare English and Dutch without testing the system against an unnatural register.

The two language corpora are built independently, not by translating one into the other. Translation rewrites exactly
the properties the Writing Style and Narrative Voice dimensions describe, so a translated corpus would test the system
against a register no author of that language produced. Dutch items are generated in Dutch and English items in
English: every generation prompt carries an explicit output-language directive, and M3 (§5.1) checks the language of
every generated story.

Independent corpora leave one question open: whether an English-Dutch difference reflects the language or the
difficulty of the items. The **parallel-specification subset** addresses this cheaply. $N_{\text{par}}$ gold
specifications, split evenly over the languages, are translated into the other language. Writing Style sub-dimensions
that reference language-specific features are adapted, and every adaptation is logged. Stories are then generated from
matched specification content in both languages (conditions: Appendix C). A specification is a fraction of a story's
length, so this costs $N_{\text{par}}$ specification translations, not story translations.

The subset controls item difficulty in the language contrasts on adherence. It does not test H4c, which concerns
specification recovery, and it is not designed to adjudicate H4c's training-data mechanism, which rests on prior
findings, not on evidence internal to this study.

### 2.6. Premises

**Purpose.** Task A needs an input that describes what happens in a story without prescribing how it is told, so that
conditions with and without a specification start from the same content.

**Procedure.** One premise per source item, in the item's language, describing the situation and its course of events
while leaving every dimension value open. How premises are authored is recorded in Appendix C.

## 3. Conditions

A condition is a way of producing a story. The table lists what each condition receives and which stages it runs.

| ID                  | Input         | Pipeline                                                                                                           |
|---------------------|---------------|--------------------------------------------------------------------------------------------------------------------|
| **C1** Full         | specification | spec → plan → draft → review → repair                                                                              |
| **C2** No Review    | specification | spec → plan → draft                                                                                                |
| **C3** Flat+Spec    | specification | single call, specification supplied in the prompt                                                                  |
| **C4** No Spec      | premise       | premise → plan → draft → generic (taxonomy-free) review                                                            |
| **C5** Flat         | premise       | single call from the premise                                                                                       |
| **C6** Agents' Room | premise       | multi-agent planning architecture of [Google's Agents' Room (Huot et al., 2025)](https://arxiv.org/abs/2410.02603) |
| **C7** Human        | —             | the source item itself                                                                                             |

C3 isolates the pipeline's contribution most sharply. It receives the same specification as C1 with no plan stage, no
per-chapter verification and no repair. If C1 does not beat C3 on adherence, the pipeline adds nothing over pasting the
specification into a prompt, which would be the most consequential negative result the study could produce. The reverse
result is not by itself evidence that the architecture is responsible, since C1 also spends more inference-time compute;
H3b states how that result is scoped.

**How each condition is built.** C1 is the psalm-saga pipeline as released (§11). C2 is the same pipeline with the
review and repair stages disabled, so the first complete draft is the output. C3 and C5 are a single model call with
no tools: a fixed system prompt, shared by every generator, that asks for the complete story in one response, followed
by the specification (C3) or the premise (C5), the length directive (§2.2) and the language directive (§2.5). C4 runs
the same plan, draft and review-and-repair loop as C1, with the specification removed from every prompt and the
dimension review replaced by a generic review. The generic review scores each chapter against a fixed checklist that
names no dimension: coherence, internal consistency, fidelity to the premise, and prose quality. Below $\tau$ it
triggers a repair, at most $k_{\max}$ times, as in C1. The prompts of every condition are released with the templates
(§11).

**C4 compute matching.** C4 uses the same $k_{\max}$ and $\tau$ as C1, so review iterations are matched by
construction. Its token budget per story is capped at the median tokens per story that C1 used in the pilot for the same
generator (§6.3), enforced through the pipeline's model-call limit. Realised tokens per story are reported for both
conditions, so the match can be checked rather than assumed.

C6 guards against C4 being a strawman. Agents' Room decomposes narrative generation into specialised agents under an
orchestrator without a dimensional specification, placing it in the same architectural family as C4 but with an
independently published design. If C4 and C6 behave alike, the no-specification ablation is a fair representative of
plan-and-write architectures. If the framework cannot be run as published it is reimplemented from the paper and
reported as such, and if that also proves infeasible it is dropped with the omission stated. The pilot settles which
(§7).

## 4. Generation Tasks

A task fixes what input a condition receives. The same condition runs under several tasks to separate different
questions.

|                                  | C1 | C2 | C3 | C4 | C5 | C6 | C7 |
|----------------------------------|----|----|----|----|----|----|----|
| **A** premise → story            | ✓  | ✓  | —  | ✓  | ✓  | ✓  | ✓  |
| **B** specification → story      | ✓  | ✓  | ✓  | —  | —  | —  | —  |
| **C** source → base and variants | ✓  | —  | —  | —  | —  | —  | —  |
| **D** scratch → base and variants| ✓  | —  | —  | —  | —  | —  | —  |

$\mathcal{C}_A = \{\text{C1}, \text{C2}, \text{C4}, \text{C5}, \text{C6}\}$ are Task A's generating conditions. C7
contributes the source item itself and is counted separately. $\mathcal{C}_B = \{\text{C1}, \text{C2}, \text{C3}\}$.
Every generating job runs once per generator family, so each count below is multiplied by $G$. Story counts are in
Appendix B.

### 4.1. Jobs, Attempts and Abandonment

- **One job, one output, one session.** Every story and every specification step is a separate job in a fresh agent
  session. No story shares a session, a scratchpad or a conversation history with another story. In Tasks C and D this
  means extraction, the base story, the null replicate, each variant specification and each variant story are all
  separate jobs, and later jobs receive earlier outputs only as files passed in their input.
- **Attempts.** A pipeline job makes up to $a_{\max}$ attempts, each in a fresh session. An attempt ends when the
  pipeline finishes or when its review loop abandons the story after $k_{\max}$ repairs. A job is *abandoned* when all
  $a_{\max}$ attempts are abandoned; its last draft is kept. Single-call jobs (C3, C5) have one attempt.
- **Call limits.** Pipeline jobs run with the model-call and tool-call limits in the released settings file (§11). A job
  stopped by a limit counts as an abandoned attempt.
- **Failed specification steps.** A variant specification that fails M1 is regenerated as a new job, up to $a_{\max}$
  times. If it still fails, the variant is missing and is reported as an M1 failure.
- **How abandoned jobs enter the analysis.** The primary analyses exclude every item, pair or trial that contains an
  abandoned story. Each analysis is rerun with the last drafts included, and the abandonment rate is reported per task,
  condition and generator. If a base story is abandoned, all $D+1$ pairs of that item and generator are affected, so the
  rate is also reported per item.

### Task A: Premise to Story

- **Answers.** H3a (C1 vs. C4), RQ5 (quality), and A6 calibration. Its C1 and C2 specifications feed S1.
- **Input.** The premise of each source item (§2.6).
- **Procedure.** Every condition in $\mathcal{C}_A$ generates one story per premise per generator family. C1 and C2
  write their own specification from the premise first. That specification is kept and evaluated.
- **Output.** $N_{\text{src}} \cdot |\mathcal{C}_A| \cdot G$ stories, plus the self-written C1 and C2 specifications.
- **Why this answers it.** All conditions start from the same content with no dimension values given. A3 and A4 then ask
  how well each story matches the *gold* specification, which no condition has seen, so H3a measures how much adherence
  a premise alone buys with and without a specification stage. Q1 compares the same stories on quality.

### Task B: Specification to Story

- **Answers.** H1a, H3b (C1 vs. C3), H3c (C1 vs. C2).
- **Input.** The gold specification of each source item (§2.3), and the parallel-subset translations (§2.5).
- **Procedure.** Every condition in $\mathcal{C}_B$ generates one story per gold specification per generator family.
  The specification is final: conditions do not re-elicit it.
- **Output.** $N_{\text{src}} \cdot |\mathcal{C}_B| \cdot G$ stories, plus the parallel-subset stories (Appendix B).
- **Why this answers it.** Supplying the specification separates *following* a specification from *writing* one. A
  system that writes vague specifications and follows them faithfully would be indistinguishable, in Task A alone, from
  one that writes sharp specifications and follows them poorly.

### Task C: Source to Base and Variants

- **Answers.** RQ2 (A1, A2), H1b (A1b), RQ4 (S2), and RQ6 together with Task D. Its stories also feed M2.
- **Input.** The source story of each item.
- **Procedure.** Per item and generator family:
  1. C1 extracts a specification $\hat{s}$ from the source story. No human reviews it.
  2. C1 generates a **base story** from $\hat{s}$ unchanged.
  3. C1 generates a **null replicate**: a second, independent story from the same unchanged $\hat{s}$.
  4. For each of the $D$ dimensions $d$, C1 writes a variant specification $\hat{s}_d$ that regenerates every
     sub-dimension of $d$ and locks the other $D-1$ dimensions, then generates a **variant story** from it.
  5. Every repair-loop edit made while producing a variant is logged against that variant's lock map. Any edit touching
     a locked dimension is flagged for audit, even where the audit judges it semantically inert.
- **Output.** Per item and generator family: $\hat{s}$, $D$ variant specifications, and $D+2$ stories (base, null
  replicate, $D$ variants), plus the lock-diagnostic log. In total $N_{\text{src}} \cdot (D+2) \cdot G$ stories.
- **Why this answers it.**
  - A1 shows a judge the base and one variant. Both are model-written from specifications that differ in one dimension
    only, so a correct identification reflects the manipulation, not the difference between human and model prose.
  - The null pair (base and null replicate) differs only by sampling. Judged the same way, it gives the rate at which
    judges report a change when none was made, which is the false-alarm baseline for A2.
  - The source story is not shown in A1. It is used only where a human reference is needed: S2 compares $\hat{s}$
    against the gold specification, and M2 checks for verbatim reuse of it.
  - The repair-loop log tests something A1 and A2 cannot: whether repair is silently patching drift on dimensions that
    must stay untouched. H3c tests whether repair helps in aggregate; this log tests whether it breaks the locks.

### Task D: Scratch to Base and Variants

- **Answers.** RQ2 and H1b on specifications with no human source, and RQ6 against Task C.
- **Input.** The scratch specification of each scratch item (§2.4), with its assigned language, bucket and length band.
- **Procedure.** Task C's steps 2–5, starting from the unreviewed scratch specification instead of an extracted one.
  The scratch specification is written once per generator family, by that family's C1 (§2.4).
- **Output.** $N_{\text{scr}} \cdot (D+2) \cdot G$ stories, the $D$ variant specifications per item and generator family,
  and the lock-diagnostic log.
- **Why this answers it.** Task D is Task C without an extraction step and without a source text. Comparing the two
  gives RQ6, and a replication of RQ2 here rules out memorisation as the explanation.

## 5. Instruments

Instruments are grouped by what they cost and what they can establish. The mechanical checks run first, since failures
there invalidate everything downstream. Item and call counts for every instrument are in Appendix B.

### 5.1. Mechanical Checks (no judge)

**M1: Lock verification.**

- **Answers.** H6b, and it gates every variant before A1, A1b and A2.
- **Input.** Each variant specification $\hat{s}_d$ and the specification it was derived from.
- **Procedure.** A diff of every sub-dimension. Unlocked sub-dimensions (those of $d$) must change: textually, and
  beyond a pre-registered threshold on the cosine distance between the old and new value's embeddings, so a paraphrase
  does not count. The embedding model must be multilingual, is fixed with the thresholds (Appendix C), and is also used
  for the distractor filter (§5.5). Locked
  sub-dimensions must stay identical, with one exception. The pipeline's consistency pass may edit a locked value to keep
  the specification coherent with the new value of $d$, and it has to state each such edit in the specification text.
  Every locked-value change is classified as:
  - *declared and expected*: stated in the specification, and the pair ($d$, changed dimension) is in the entanglement
    matrix $E$ (§5.3);
  - *declared and unexpected*: stated, but not in $E$;
  - *silent*: not stated.
  
  An author audits $\rho_{\text{audit}}$ of the decisions.
- **Output.** Per variant: pass, or one or more of {unlocked unchanged, unlocked paraphrased, declared-expected,
  declared-unexpected, silent}.
- **Why this answers it.** Silent changes and unchanged or paraphrased unlocked values are system faults: they are logged
  and the variant is regenerated, and their rate is reported. Declared changes are allowed, logged, and reported by
  class. They are the specification-level record of entanglement that A2 then measures at story level.

**M2: Verbatim overlap.**

- **Answers.** The memorisation threat (§10).
- **Input.** Each generated story from Tasks A, B and C, and its source item.
- **Procedure.** Both texts are lowercased, stripped of punctuation and split into words (§0.3). The overlap rate is the
  share of the story's word 8-grams that also occur in the source. The baseline is the same rate computed between the
  story and every *other* source item of the same language and bucket, which captures incidental phrase reuse for that
  register. The baseline's distribution is reported first, and the exclusion threshold is set a pre-registered number of
  standard deviations above its mean (Appendix C).
- **Output.** Per story: overlap rate and an exclusion flag.
- **Why this answers it.** A flagged story reuses its source beyond the level of incidental phrase reuse the baseline
  already shows. C7 is excluded by construction, since a source cannot be scored against itself, and so is Task D, which
  has no source. Task D's contribution to the memorisation question is the source-free replication, not an M2 count.

**M3: Output conformity.**

- **Answers.** It gates every generated story, and supplies the length covariate for §8.
- **Input.** Each generated story, its target language and its length band (§2.2).
- **Procedure.** Language identification with fastText's `lid.176` model, run per paragraph. A story passes if the
  target language accounts for at least 90% of its words, so a single English heading in a Dutch story is reported but
  does not fail it. The word count (§0.3) is compared with the band.
- **Output.** Per story: detected language, realised word count, and an in-band flag.
- **Why this answers it.** A story in the wrong language is a system fault: it is logged and regenerated. A story outside
  the length band is kept, and the out-of-band rate is reported per condition. Realised length enters the analysis as a
  covariate where condition medians diverge (§10).

### 5.2. Specification-Level Instruments

**S1: Specificity screening.**

- **Answers.** Whether a spec-writing mechanism tends towards vague or sharp specifications. This feeds RQ4 by
  separating two failures that otherwise look alike: a vague specification, and a sharp one the generator ignores.
- **Input.** A sample of specifications: $n_{\text{S1}}$ from each of the four mechanisms that write a specification
  with no human review, pooled across generator families, plus all $N_{\text{src}}$ gold specifications as the
  human-authored reference. The four mechanisms are Task A's C1 and C2 self-written specifications, Task C's extraction
  and Task D's scratch specification.
- **Procedure.** Three binary checks per value, taken from the dimension criteria: does the value name a realised
  property, is it testable against text, and does it commit where the sub-dimension admits a spectrum. One call per
  value per judge.
- **Output.** Three binary labels per value.
- **Why this answers it.** The sample is drawn per mechanism, not per item, because the question is about the mechanism.
  This closes a weakness in the methodology, where specification quality was applied by judgement with no independent
  instrument.

**S2: Recovery against gold.**

- **Answers.** H4a–H4c, and context for RQ6.
- **Input.** Each specification $\hat{s}$ extracted in Task C, per generator family, and the gold specification of the
  same item.
- **Procedure.** Sub-dimension by sub-dimension, a judge rates $\hat{s}$ against gold on three levels: *matches* the gold
  answer in substance, *partially matches*, or *conflicts with or omits* it. The double-annotated items are rated the
  same way author against author, which gives the human ceiling.
- **Scoring.** Each label is scored *matches* = 1, *partially matches* = 0.5, *conflicts or omits* = 0, and a cell's
  score is the mean over the $J$ judges. **Recovery** is the mean cell score over the cells in question. The human ceiling
  is the same score computed author against author on the $N_{\text{dbl}}$ items (each author's specification rated as
  the candidate against the other's as gold, both directions averaged). For H4a, system recovery is computed on the same
  $N_{\text{dbl}}$ items against each author's specification and averaged, so system and ceiling are measured on
  identical items. Sensitivity analyses score *partially matches* as 0 (strict) and as 1 (lenient). Judge agreement on
  the labels is reported as Krippendorff's $\alpha$ (ordinal).
- **Output.** One three-level label per sub-dimension cell and judge.
- **Why this answers it.** Recovery rates per sub-dimension and language, compared with the human ceiling, test H4a–H4c.
  The gold-spec drafter is outside every judge family (§6), so S2 does not measure a model agreeing with its own family's
  earlier output.

### 5.3. Adherence and Controllability Instruments

These instruments have ground truth by construction, so they need no rubric, anchor descriptions or rater calibration,
and humans and model judges perform them identically, which makes their agreement directly interpretable.

**A1: Dimension identification.**

- **Answers.** H2a, and RQ6 through its provenance term.
- **Input.** A base story and one variant from Task C or D (a *variant pair*), or a base story and its null replicate (a
  *null pair*), with the $D$ dimension names and one-line definitions. Pairs are presented in randomised order, with
  version labels randomised.
- **Procedure.** The judge answers:

  > Two versions of a story appear below. They were written from specifications that are either identical or differ in
  > exactly one of six respects. Which one?
  >
  > **Version A:** {…}  **Version B:** {…}
  >
  > Writing Style / Narrative Voice / Character / Plot Structure / Scene Sequence / World-Building / No difference /
  > Cannot tell
  >
  > In one sentence: what led you to that answer?

- **Output.** One choice and one rationale per pair.
- **Why this answers it.** For variant pairs the correct answer is the regenerated dimension, known by construction.
  Chance among the dimensions is $\frac{1}{D}$. The confusion matrix over the $D$ dimensions is the more informative
  output: its diagonal tests H2a, and its off-diagonal shows which dimensions bleed into which, read against the
  entanglement matrix $E$ below. For null pairs the correct answer is "No difference". "Cannot tell" is offered so
  raters do not guess.

  Scoring, for every response:

  | Pair    | Response                       | Scored as             |
  |---------|--------------------------------|-----------------------|
  | variant | the regenerated dimension      | correct               |
  | variant | another dimension              | incorrect             |
  | variant | "No difference"                | incorrect (a miss)    |
  | null    | "No difference"                | correct               |
  | null    | any dimension                  | incorrect (a false alarm) |
  | either  | "Cannot tell"                  | abstention            |

  The primary analysis covers decided responses, with the abstention rate reported alongside, and a secondary analysis
  scores abstentions as incorrect. H2a is tested on variant pairs against $\frac{1}{D}$. A judge guessing uniformly over
  all seven decided options would score $\frac{1}{D+1}$, so testing against $\frac{1}{D}$ is conservative. Null pairs
  are reported separately, as the rate at which judges claim a change that was not made.

**A2: Non-target drift.**

- **Answers.** H2b, H6b.
- **Input.** The same pair, directly after A1.
- **Procedure.** A follow-up question: besides the dimension you identified (or for every dimension, if you chose "No
  difference" or "Cannot tell"), did anything else change? Answered per dimension as yes or no.
- **Output.** A yes/no label per dimension per pair.
- **Scoring.** A1 and A2 together give a *changed* or *unchanged* report for every dimension of every pair: the
  dimension chosen in A1 counts as *changed*, and A2 supplies the rest. On a variant pair, a *changed* report on the
  regenerated dimension is a **hit**, and a *changed* report on a locked dimension is a **false alarm**. On a null pair,
  every dimension is unchanged, so any *changed* report is a false alarm. Then
  $d' = z(H) - z(F)$, where $H$ and $F$ are the hit and false-alarm rates and $z$ is the inverse standard normal
  distribution function. Rates are computed with the log-linear correction (add 0.5 to each count, 1 to each total) so
  that rates of 0 or 1 stay finite. A "Cannot tell" in A1 leaves the dimension report to A2 alone.
- **Why this answers it.** A1's confusion matrix reaches specificity only indirectly. A2 tests the lock at story level.
  Hits and false alarms are computed over *all* variant pairs, whatever A1's outcome, so a correct A1 answer does not
  fix the hit rate at 1 and leave $d'$ undefined. Keeping A2 a follow-up, not turning A1 into a select-all task, keeps
  A1's scoring clean.

  Two analyses keep entanglement from being read as failure. First, the false-alarm rate is compared against the
  null-pair rate, which is what judges report when nothing changed. Second, A2 is analysed with and without the pairs in
  $E$. If false alarms drop to the null baseline once $E$ is excluded, the drift is the entanglement we predicted; if
  they stay above it, the system is leaking edits into locked dimensions.

  A secondary, conditional analysis reports the false-alarm rate on locked dimensions among pairs where A1 was correct:
  the drift a judge sees once it has found the intended change.

**Entanglement matrix $E$.** The dimensions are not independent: regenerating one can legitimately force a change in
another. $E$ lists the directed pairs where such a knock-on change is expected. It is frozen after the pilot and before
the confirmatory run, and it is used by M1, A1 and A2 as described above. The draft below comes from the pipeline's own
consistency checklist (`story-brainstorming` skill, step 5) and from reviewer input.

| Regenerated dimension | Expected knock-on change in                                                          |
|-----------------------|--------------------------------------------------------------------------------------|
| Plot Structure        | Scene Sequence                                                                       |
| Character             | Plot Structure; World-Building                                                       |
| Character             | Narrative Voice and Writing Style, when the character's mode of communication changes |
| World-Building        | Plot Structure; Character                                                            |
| Writing Style         | Narrative Voice                                                                      |
| Narrative Voice       | Writing Style                                                                        |

**A1b: Value check on variants.**

- **Answers.** H1b, H6a.
- **Input.** One variant story, the name of its regenerated dimension $d$, and two descriptions of $d$: its value in the
  base specification and its value in the variant specification, each the concatenated sub-dimension values of $d$.
- **Procedure.** The judge picks which description the story realises. Description order is counterbalanced. Model
  judges see A1b in a fresh call, separately from A1. Human raters never receive A1b for a pair they judged in A1, so the
  dimension name does not leak into their A1 answer.
- **Output.** One choice and one rationale per variant.
- **Why this answers it.** A1 shows that the judge can tell *which* dimension changed. A1b shows that it changed *to the
  specified value*. A variant could change Character in a direction unrelated to the new specification and still be
  identified in A1, but it would fail A1b. Chance is $\frac{1}{2}$ and ground truth is known by construction.

**A3: Specification-story matching.**

- **Answers.** H1a, H3a–H3c.
- **Input.** A specification and two stories: one generated from it, and one generated from a different specification
  of the same language and genre bucket. For Task A, the specification is the gold specification of the premise's item,
  which no condition has seen.
- **Procedure.** The judge identifies which story was written from the specification. Presentation order is
  counterbalanced. $T_{\text{A3}}$ trials are built per task-condition cell: Task B × $\mathcal{C}_B$ and Task A ×
  {C1, C4}. §5.5 states how trials are sampled and distractors drawn.
- **Output.** One choice per trial.
- **Why this answers it.** Accuracy above $\frac{1}{2}$ is adherence (H1a). Differences between conditions give
  H3a–H3c. A3 carries the larger share of the model-judge volume.

**A4: Story-specification attribution.**

- **Answers.** H1a, H3a–H3c, as A3, from the opposite direction.
- **Input.** One story and three candidate specifications: the true one and two from the same language and genre
  bucket. Same task-condition cells as A3, $T_{\text{A4}}$ trials each.
- **Procedure.** The judge identifies which specification the story was written from. Chance is $\frac{1}{3}$.
- **Output.** One choice per trial.
- **Why this answers it.** A4 measures A3's construct from the other side, so the pair is a convergent-validity check on
  their overlapping sample. It is also far cheaper in human time, since reading one story and three short
  specifications takes roughly a third as long as reading three stories, so A4 carries the larger share of the human
  subset. Three alternatives is a deliberate ceiling: the smallest bucket offers only two same-bucket distractors, and an
  out-of-bucket fourth would let judges solve the task on content.

**A5: Sub-dimension recovery.**

- **Answers.** H1c.
- **Input.** A story and four candidate values for one sub-dimension: the correct one and three from other items'
  specifications for the same sub-dimension, filtered for semantic distance, with $\rho_{\text{audit}}$ audited.
  $T_{\text{A5}}$ trials in total; the sampling frame is in Appendix C.
- **Procedure.** The judge picks the value the story realises. Chance is $\frac{1}{4}$.
- **Output.** One choice per trial.
- **Why this answers it.** It is the only instrument that reaches sub-dimension resolution. Human validation at that
  resolution is out of reach at this scale, so results are model-judge only and reported as descriptive.

**A6: Premise attribution.**

- **Answers.** No hypothesis. It calibrates the others.
- **Input.** One Task A story and three premises: the true one and two from the same language and genre bucket.
  $n_{\text{A6}}$ items per generating condition in $\mathcal{C}_A$, across generator families.
- **Procedure.** The judge identifies which premise the story was written from. Chance is $\frac{1}{3}$.
- **Output.** One choice per trial.
- **Why this answers it.** Every condition should approach ceiling, since writing about the right premise is basic
  prompt-following. A6 shows what a judge's ceiling looks like on this corpus, which frames the primary numbers: an
  accuracy of 0.40 on a $D$-way dimension task means little to a reader who does not know judges reach, say, 0.94 on
  premise attribution. Same-bucket distractors keep the ceiling comparable in difficulty to A1 and A4. The per-condition
  sample makes a single underperforming condition visible, which signals a generation failure that would otherwise be
  misread as poor adherence.

### 5.4. Quality Instrument

**Q1: Pairwise preference.**

- **Answers.** H5a–H5c.
- **Input.** Pairs of Task A stories for the same premise, with condition labels stripped, for three contrasts: C1–C5,
  C1–C4 and C1–C7.
- **Procedure.** Every pair is shown in both orders. Judges answer which story they would rather read and, separately,
  which is more internally consistent.
- **Output.** Two preferences per pair and order.
- **Why this answers it.** Quality is tested for non-inferiority, not superiority: C1's win rate against C5 must not fall
  below $m_{\text{Q1}}$ (H5a). H5b correlates each story's Q1 outcome with its A3 and A4 outcomes within condition. C1–C7
  anchors the scale (H5c).

### 5.5. Item Construction for A3–A6

The construction scripts (§11) build every trial from the master seed $\sigma$ (§0.3).

- **Targets.** A task-condition cell holds $N_{\text{src}} \cdot G$ stories. Its $T$ trials ($T_{\text{A3}}$ or
  $T_{\text{A4}}$) use every story once as a target, then fill the remaining trials by drawing targets without
  replacement, stratified by language. If $T$ exceeds twice the cell size, the draw repeats. A6 samples $n_{\text{A6}}$
  stories per condition, stratified by language and generator.
- **Distractor pool.** Distractors come from the same language and genre bucket as the target, from a different item,
  and from the same task, condition and generator as the target, so neither the condition's nor the generator's style
  can identify the true answer. A3 distractors are stories, A4 distractors are gold specifications, A6 distractors are
  premises, and A5 distractors are other items' values for the same sub-dimension.
- **Similarity filter.** A candidate distractor is rejected if its embedding (§5.1, M1) is closer to the target's
  correct answer than the pre-registered distance threshold (Appendix C), so two near-identical options cannot appear in
  one trial. $\rho_{\text{audit}}$ of the accepted distractors are audited by an author.
- **Small buckets.** Where the bucket has too few items (Dutch Detective/Mystery, §2.1), the missing distractor is drawn
  from the same language and the bucket whose items are nearest by embedding. These trials are flagged, and every
  analysis is rerun without them.
- **Repeated targets.** A story used twice as a target gets a fresh distractor draw and a fresh presentation order.
  Trials that share a target are correlated, which the random intercept for source item absorbs (§8).
- **Presentation.** Position of the correct answer is counterbalanced within each cell, so each position holds it equally
  often.

## 6. Models and Judges

### 6.1. Model Roles

A *family* is a set of models from the same provider and lineage. Constraints apply to families, not individual
models.

| Role               | Count       | Constraint                                                                                                                                                              | Model         |
|--------------------|-------------|-------------------------------------------------------------------------------------------------------------------------------------------------------------------------|---------------|
| Generator          | $G$         | At least one frontier API model and one open-weight model, with an EU-developed open-weight model preferred. Every pipeline stage of a job, subagents included, uses that job's generator. | Appendix C    |
| Judge              | $J$         | Disjoint from every generator family and from the gold-spec drafter's family. Must pass the gates in §6.2.                                                              | Appendix C    |
| Gold-spec drafter  | 1           | Disjoint from every generator and judge family.                                                                                                                         | Appendix C    |

Judge families disjoint from generator families design self-preference out instead of correcting for it afterwards. A
drafter disjoint from the judges keeps S2 from measuring a model's agreement with its own family's draft. A drafter
disjoint from the generators keeps the "human-authored" gold specifications in Task B from being partly authored by the
generator's own family.

Candidate models, prices and the cost estimate are kept in `docs/experimental_cost_estimation.xlsx`. Model assignments
are decided after the pilot (§7), using its measured cost and runtime.

### 6.2. Judges

Each model judge produces a rationale before its verdict, returns structured output, and sees items in randomised
order, with both presentation orders run for pairwise instruments.

Human judgement covers a stratified subset of the same instruments, never a separate rubric. Because the tasks have
ground truth, raters can be authors, colleagues, crowdworkers or domain experts without changing the analysis: blinding
and randomisation make rater identity inert where the correct answer is fixed by construction. Authors who contributed a
gold specification do not judge items derived from it. The human subset has between $H_{\text{floor}}$ and
$H_{\text{target}}$ items, allocated first to A1, then A4, then Q1. Each human item is judged by $R_H$ raters, which
gives human-human agreement alongside the human-model comparison. Within each instrument, items are drawn at random
(seed $\sigma$) and stratified: A1 by language × dimension, with null pairs in proportion to their share of A1 items;
A4 by language × task-condition cell; Q1 by language × contrast. No rater sees two items derived from the same source
item within one instrument. Recruitment, payment, the rating interface and ethics approval are recorded in Appendix C.

Rater materials include five training items with feedback and catch trials at rate $\rho_{\text{catch}}$, built so the
manipulated dimension is unmistakable. Raters below $\theta_{\text{catch}}$ on catch trials are excluded, with
exclusions reported and the analysis rerun including them.

A model enters the judge pool only if it clears two gates: it exceeds chance on the catch trials humans receive, and it
returns parseable structured output on at least $\theta_{\text{parse}}$ of calls. Smaller multilingual models are
plausible generators and unreliable judges, and these gates decide the question empirically.

### 6.3. Compute and Cost

Every model call records its token usage and wall-clock time, and every job records its total. The pilot (§7) uses
these to measure cost and runtime per story, per task, condition and generator, which replaces the per-call assumptions
in the cost sheet. The pipeline is agentic and makes many calls per story, so a per-call estimate without measured
totals undercounts.

## 7. Pilot

$n_{\text{pilot}}$ source items per language pass through every task and condition before the confirmatory run. Pilot
data are excluded from analysis.

The pilot settles:

- whether each candidate generator produces coherent stories at the target lengths (§2.2), in the target language, and
  valid $S$-field specifications; a model that fails is dropped and the pilot report states why, which is how the EU
  open-weight candidates are decided instead of being committed to in advance;
- whether candidate judges clear the §6.2 gates;
- the observed A1 abstention rate and accuracy, which drive the §9 sample-size checks;
- the median human time per item, which converts the rater budget into an item count;
- measured tokens and runtime per story (§6.3), which fix $G$ and the model assignments;
- the C6 feasibility outcome (§3), so that condition's status is known before the confirmatory run;
- the thresholds and the entanglement matrix $E$ listed in Appendix C, which are frozen after the pilot.

## 8. Analysis

This section states how judge verdicts become results. Three obstacles shape it.

**Judgements are not independent.** Each source item contributes $(D+1) \cdot G$ A1 pairs, and every pair is seen by
each judge. Some items are inherently easier, and some judges are more accurate than others. Treating every judgement as
an independent observation would understate the uncertainty, so random intercepts for source item and judge are
included.

**The null is not 50%.** Chance differs by instrument: $\frac{1}{D}$ for A1, $\frac{1}{2}$ for A1b and A3,
$\frac{1}{3}$ for A4 and A6, $\frac{1}{4}$ for A5. Each model is offset so its intercept tests against the correct
chance level.

**Many tests invite false positives.** Per-dimension chance tests, condition contrasts and language contrasts together
make a few dozen comparisons, enough that one spurious result is expected by chance alone.

The primary models are mixed-effects logistic regressions on judgement correctness. For A1 (variant pairs) and A1b:

```
correct ~ dimension + language + provenance + (1 | source_item) + (1 | judge)
```

where `provenance` distinguishes Task C (extracted) from Task D (authored) and supplies RQ6. For A3 and A4:

```
correct ~ condition + language + (1 | source_item) + (1 | judge)
```

fitted per task, from which the H3a–H3c contrasts are drawn. Where a model fails to converge, the pre-registered
fallback is a per-cell exact binomial test with Wilson intervals. It is the registered fallback, never chosen after
seeing results.

Language contrasts additionally include realised item length as a covariate (§2.1), and they are reported twice: with
and without the translated Dutch items.

Effect sizes are reported as marginal probabilities with 95% intervals alongside odds ratios, and every p-value is
accompanied by both. Multiple comparisons are controlled by Benjamini-Hochberg at $q$ within three declared families:
per-dimension chance tests (A1, A1b), condition contrasts, and language contrasts. Families are not pooled. Sub-dimension
analyses from A5 are exploratory and labelled as such.

A2 is analysed as a signal-detection problem (§5.3, A2 scoring). The model is a mixed-effects probit regression on the
per-dimension *changed* reports of variant pairs:

```
reported_changed ~ is_regenerated + (1 | source_item) + (1 | judge)
```

whose `is_regenerated` coefficient estimates $d'$. It is fitted three ways: over all locked dimensions, excluding the
locked dimensions that $E$ pairs with the regenerated one, and with null-pair reports added as a third level, so the
locked-dimension false-alarm rate can be compared with the null-pair rate directly. H2b holds if the coefficient is
positive with its interval above zero. Per-judge $d'$ values with the log-linear correction are reported alongside.

Reliability is reported as Krippendorff's $\alpha$ across model judges, per instrument and per dimension, and as Cohen's
$\kappa$ between the model majority and human labels. Convergence between A3 and A4 on their overlapping sample is
reported as a correlation.

A judge that is 80% accurate reports a biased estimate of the true rate. Where judge and human labels coexist, accuracy
is therefore also reported with the Rogan-Gladen correction, using sensitivity and specificity estimated from the human
subset. This lets a small human subset support valid statements about a much larger set of automatic labels. The human
subset is allocated by instrument (§6.2), not drawn at random across instruments. To keep the correction's validity
assumption checkable, the labels used for Rogan-Gladen within each instrument are an explicit random sample of that
instrument's human-rated items, not whichever items were rated first.

H4a and H5a are tested by two one-sided tests against their pre-registered margins. H5b is a within-condition
correlation between quality and adherence outcomes.

## 9. Sample Size

This section prevents one outcome: running everything, getting a null, and being unable to say whether there was no
effect or the study was too small to detect one. Fixing the detectable effect in advance makes a null interpretable. The
sample sizes required for each test are listed in Appendix B.2, computed at $\alpha$ and power $1-\beta$.

**A1 (H2a).** Tasks C and D supply $(N_{\text{src}} + N_{\text{scr}}) \cdot G$ variant pairs per dimension. The design
requires this to exceed the sample needed to detect an accuracy of 0.35 against $\frac{1}{D}$, so per-dimension tests
are adequately powered for effects at or above 0.35 even after correction. The pooled test is powered far beyond
requirement. A1b has the same number of variants per dimension and a higher chance level; its requirement is in
Appendix B.2.

**A3 and A4 (H1a, H3).** $T_{\text{A3}}$ trials per task-condition cell are set to power the design for adherence at or
above 0.70 per cell against $\frac{1}{2}$. A4 at $T_{\text{A4}}$ is powered for 0.60 against $\frac{1}{3}$.

**Condition contrasts.** Pairwise condition contrasts are less well powered than the against-chance tests. The smallest
effect size of interest for them is $\Delta_{\text{SESOI}}$, and the study states that it cannot detect smaller effects.

**A2 (H2b).** $d'$ uses every variant pair, so its sample does not depend on A1 accuracy: $(N_{\text{src}} +
N_{\text{scr}}) \cdot D \cdot G$ variant pairs per judge, each contributing one hit trial and $D-1$ false-alarm trials
(Appendix B). The conditional analysis (§5.3) is secondary and has no minimum sample.

The design is deliberately better powered for RQ1 and RQ2 than for RQ3. Establishing that specifications control output
is the prior question, and we would rather report a well-estimated primary result with a wide interval on the ablation
ordering than underpower both.

## 10. Threats and Controls

| Threat                                                         | Control                                                                                                               |
|----------------------------------------------------------------|-----------------------------------------------------------------------------------------------------------------------|
| Circularity between generator and evaluator                    | PSALM is used nowhere in this evaluation; internal verifier verdicts are never reported as results                    |
| Self-preference                                                | Judge families disjoint from generator families (§6.1)                                                                |
| Shared authorship of gold specifications and judges            | Gold-spec drafter disjoint from judge families (§6.1)                                                                 |
| Shared authorship of gold specifications and generators        | Gold-spec drafter disjoint from generator families (§6.1)                                                             |
| Human vs. model prose as an A1 cue                             | A1 compares a base story with its variant, both model-written; the source story is never shown in A1 (§4, Task C)     |
| Dimension entanglement read as lock failure                    | Pre-specified matrix $E$; A2 analysed with and without $E$ and against the null-pair baseline; M1 classifies edits    |
| Constraint self-selection                                      | Measured directly by RQ6 instead of controlled away                                                                   |
| Extraction error contaminating variant chains                  | Task D repeats Task C without an extraction step; S2 measures extraction error directly                               |
| Human review confounding the Task C vs. Task D contrast        | Neither task's specification is reviewed before generation (§2.4)                                                     |
| Silent repair-loop edits on locked dimensions                  | Repair-loop edits logged against the lock map and audited, separately from H3c                                        |
| Survivorship from the repair loop                              | Abandonment rate reported; analyses rerun including last drafts of abandoned runs                                     |
| Length confound                                                | Length band per item (§2.2); realised length checked by M3, reported per condition, and a covariate where medians diverge |
| Language confounded with item length and form                  | Length covariate in language contrasts; parallel-specification subset (§2.5)                                          |
| Translated items in the Dutch corpus                           | Disclosed (§2.1); language contrasts reported with and without them                                                   |
| Output in the wrong language                                   | Explicit language directive; M3 language check                                                                       |
| Position bias                                                  | Pairwise items run in both orders; inconsistency rate reported                                                        |
| Memorisation of public-domain sources                          | M2, with Task D as the memorisation-free replication                                                                  |
| Compute confound in C4                                         | C4 matched to C1 on review iterations and token budget                                                                |
| Compute confound in C1 vs. C3 (H3b)                            | Not controlled; a C1 advantage is reported as architecture plus compute                                               |
| Distractor artefacts                                           | Distractors drawn from real specifications within language and bucket, embedding-filtered, $\rho_{\text{audit}}$ audited |
| Judge ceiling unknown                                          | A6 establishes it on this corpus with same-bucket distractors                                                         |
| Training-data asymmetry in H4c                                 | Not controlled; expected direction and mechanism stated in advance (§1)                                               |
| Non-representative human subset for Rogan-Gladen               | Correction subset drawn as an explicit random sample within each instrument (§8)                                      |

## 11. Reproducibility

Frozen and published before the confirmatory run:

- Hypotheses with primary and secondary designation, the parameter values in Appendix A, the smallest effect size of
  interest, non-inferiority margins, and the analysis plan including convergence fallback, abstention handling,
  exclusion rules, the A1 and A2 scoring rules, the C6 feasibility outcome, the entanglement matrix $E$, and the
  Rogan-Gladen sampling scheme, timestamped on a public registry
- The $N_{\text{src}}$ source items with provenance and licence (including which items are translations), the gold
  specifications, the double-annotated subset, the scratch sub-corpus with its bucket and length assignments, the
  premises, and the parallel-specification translations with their adaptation log
- Model identifiers with exact revisions, decoding parameters per stage, the master seed $\sigma$, $k_{\max}$, $\tau$
  and $a_{\max}$
- The software: the psalm-saga and harness commit hashes, the `uv.lock` lockfile (which pins deepagents and LangChain),
  and the settings file of every run, including the model-call and tool-call limits
- The embedding model, the language-identification model and the M1, M2 and distractor thresholds
- All prompt templates, versioned and content-hashed: elicitation, extraction, planning, drafting, internal
  verification, repair, and every judge instrument
- Item construction and randomisation scripts, distractor generation with its threshold, rater instructions, training
  items and catch trials
- Raw per-judge and per-rater responses at item level, not aggregates
- Full generation traces, including abandoned runs, the repair-loop lock-diagnostic log, and per-call token usage and
  wall-clock time
- Analysis code with an environment lockfile

**Where each artifact goes.** The registration goes to the public registry (Appendix C). Code, prompt templates,
settings and construction scripts are released from this repository at the tagged commit. The corpus, gold
specifications, premises, scratch sub-corpus, generated stories, traces and judge and rater responses are released from
the `psalm-saga-experiments` repository (CORPUS.md), with an archived snapshot carrying a persistent identifier.

## 12. Reduction Path

If capacity contracts, the order of reduction is fixed in advance. Tasks C and D with A1, A1b and A2 are kept under all
circumstances, since they carry RQ1's variant test, RQ2 and RQ6. Task B with A3 and A4 goes next, carrying H1a and RQ3.
The order of cuts is: Q1, then C6, then A5, then any generator family beyond the second on Tasks C and D, then the
corpus to two items per genre bucket per language. A6 is cheap enough to keep throughout, since without it the primary
numbers cannot be interpreted.

A study consisting of Tasks C and D, dimension identification with drift and the value check across $J$ model judges,
and a human subset of $H_{\text{floor}}$ items is publishable on its own. It answers whether a specification controls
what a generator produces, which is the question the contribution rests on.

The same ordering, reversed, applies when the experiment or the corpus grows.

## Appendix A. Parameter Values

The only place these values are set. Values marked *pilot* are fixed after the pilot (§7) and before the confirmatory
run.

| Symbol                                         | Value                        | Note                                                         |
|------------------------------------------------|------------------------------|--------------------------------------------------------------|
| $N_{\text{EN}}$, $N_{\text{NL}}$               | 15, 14                       | Current extraction; may still change. See CORPUS.md          |
| $N_{\text{src}}$                               | 29                           | $N_{\text{EN}} + N_{\text{NL}}$                              |
| $N_{\text{scr}}$                               | 10                           | 5 per language                                               |
| $N_{\text{dbl}}$                               | 10                           | 5 per language                                               |
| $N_{\text{par}}$                               | 6                            | 3 per language                                               |
| $B$                                            | 5                            | Genre buckets; members per bucket in CORPUS.md               |
| $D$, $S$                                       | 6, 36                        | Taxonomy                                                     |
| $G$                                            | 2                            | Minimum; 3 or more if budget and time allow (Appendix C)     |
| $J$                                            | 3                            |                                                              |
| $W_{\min}$, $W_{\max}$                         | 300, 10,000 words            |                                                              |
| $C_{\max}$                                     | 50,000 characters            |                                                              |
| $\delta$                                       | 0.10                         | Generation band: target word count $\pm 10\%$                |
| $\vert\mathcal{C}_A\vert$, $\vert\mathcal{C}_B\vert$ | 5, 3                   | §4                                                           |
| $n_{\text{S1}}$                                | 12                           | Per mechanism                                                |
| $T_{\text{A3}}$, $T_{\text{A4}}$               | 80, 80                       | Per task-condition cell                                      |
| $T_{\text{A5}}$                                | 540                          |                                                              |
| $n_{\text{A6}}$                                | 12                           | Per generating condition                                     |
| $n_{\text{pilot}}$                             | 3                            | Per language                                                 |
| $H_{\text{floor}}$, $H_{\text{target}}$        | 150, 300                     |                                                              |
| $R_H$                                          | 2                            | Proposed (Appendix C)                                        |
| $\rho_{\text{catch}}$, $\theta_{\text{catch}}$ | 0.10, 0.80                   |                                                              |
| $\theta_{\text{parse}}$                        | 0.95                         |                                                              |
| $\rho_{\text{audit}}$                          | 0.10                         |                                                              |
| $m_{\text{Q1}}$                                | 0.40                         | Win rate of C1 against C5                                    |
| $\Delta_{\text{SESOI}}$                        | 15 percentage points         |                                                              |
| $\alpha$, $1-\beta$, $q$                       | 0.05, 0.80, 0.05             |                                                              |
| $k_{\max}$, $\tau$                             | *pilot*                      | Pipeline repair bound and threshold                          |
| $a_{\max}$                                     | 3                            | `MAX_STORY_ATTEMPTS` in the harness                          |
| $\sigma$                                       | *pilot*                      | Drawn once and registered before item construction           |

## Appendix B. Derived Counts

### B.1. Counts

Computed from Appendix A. Recompute this table whenever a value there changes.

**Generation.**

| Quantity                          | Formula                                                    | Value |
|-----------------------------------|------------------------------------------------------------|-------|
| Task A stories                    | $N_{\text{src}} \cdot \vert\mathcal{C}_A\vert \cdot G$     | 290   |
| Task B stories                    | $N_{\text{src}} \cdot \vert\mathcal{C}_B\vert \cdot G$     | 174   |
| Parallel-subset stories           | $N_{\text{par}} \cdot G$ (C1 only; see Appendix C)         | 12    |
| Task C stories                    | $N_{\text{src}} \cdot (D+2) \cdot G$                       | 464   |
| Task D stories                    | $N_{\text{scr}} \cdot (D+2) \cdot G$                       | 160   |
| **Generated stories, total**      |                                                            | 1,100 |
| Human items (C7)                  | $N_{\text{src}}$                                           | 29    |
| Variant specifications (C and D)  | $(N_{\text{src}} + N_{\text{scr}}) \cdot D \cdot G$        | 468   |

**Instruments.** An *item* is what the instrument scores; *calls* are model-judge calls ($J$ judges per item unless
noted).

| Instrument | Item                     | Items formula                                                       | Items | Calls formula             | Calls  |
|------------|--------------------------|---------------------------------------------------------------------|-------|---------------------------|--------|
| M1         | variant specification    | $(N_{\text{src}} + N_{\text{scr}}) \cdot D \cdot G$                 | 468   | none                      | 0      |
| M2         | story (Tasks A, B, C)    | Task A + Task B + Task C stories                                    | 928   | none                      | 0      |
| M3         | story (all)              | generated stories, total                                            | 1,100 | none                      | 0      |
| S1         | specification value      | $(4 \cdot n_{\text{S1}} + N_{\text{src}}) \cdot S$                  | 2,772 | items $\cdot J$           | 8,316  |
| S2         | sub-dimension cell       | $N_{\text{src}} \cdot S \cdot G$                                    | 2,088 | items $\cdot J$           | 6,264  |
| A1 (+A2)   | story pair               | $(N_{\text{src}} + N_{\text{scr}}) \cdot (D+1) \cdot G$             | 546   | items $\cdot J$           | 1,638  |
| A2 $d'$    | dimension report, variant pairs | hits: $(N_{\text{src}} + N_{\text{scr}}) \cdot D \cdot G$; false alarms: $\cdot (D-1)$ | 468; 2,340 | from A1 calls | 0 |
| A1b        | variant                  | $(N_{\text{src}} + N_{\text{scr}}) \cdot D \cdot G$                 | 468   | items $\cdot J$           | 1,404  |
| A3         | trial                    | $5 \cdot T_{\text{A3}}$ (cells: B × C1, C2, C3; A × C1, C4)         | 400   | items $\cdot J$           | 1,200  |
| A4         | trial                    | $5 \cdot T_{\text{A4}}$                                             | 400   | items $\cdot J$           | 1,200  |
| A5         | trial                    | $T_{\text{A5}}$                                                     | 540   | items $\cdot J$           | 1,620  |
| A6         | trial                    | $n_{\text{A6}} \cdot \vert\mathcal{C}_A\vert \cdot G$               | 120   | items $\cdot J$           | 360    |
| Q1         | story pair               | $N_{\text{src}} \cdot 3 \cdot G$                                    | 174   | items $\cdot 2 \cdot J$ (both orders) | 1,044 |
| **Total**  |                          |                                                                     |       |                           | 23,046 |

### B.2. Required Sample Sizes

Sample sizes needed for a one-sample test against chance at $\alpha$ and power $1-\beta$. To be re-verified with the
analysis code before registration.

| Test               | Chance          | Target accuracy | Required $n$ | Available                                               |
|--------------------|-----------------|-----------------|--------------|---------------------------------------------------------|
| A1, per dimension  | $\frac{1}{6}$   | 0.40            | 28           | $(N_{\text{src}} + N_{\text{scr}}) \cdot G = 78$        |
| A1, per dimension  | $\frac{1}{6}$   | 0.35            | 43           | 78                                                      |
| A3, per cell       | $\frac{1}{2}$   | 0.70            | 47           | $T_{\text{A3}} = 80$                                    |
| A3, per cell       | $\frac{1}{2}$   | 0.65            | 98           | 80                                                      |
| A4, per cell       | $\frac{1}{3}$   | 0.60            | 36           | $T_{\text{A4}} = 80$                                    |
| A1b, per dimension | $\frac{1}{2}$   | 0.70            | 47           | 78                                                      |

A2's $d'$ is not a test against chance and has no row here: with 468 hit trials and 2,340 false-alarm trials per judge
(B.1), its interval is narrow for any $d'$ worth reporting.

## Appendix C. Open Decisions

Each item is settled before the confirmatory run. Items marked *pilot* are settled by the pilot (§7).

1. **Generator families ($G$) and model assignments** for every role in §6.1. At least two generator families; a third
   or more if budget and time allow. *Pilot*, using the cost sheet and measured tokens and runtime.
2. **Premise authorship** (§2.6): who writes the premises, and whether a model drafts them for an author to edit.
3. **Parallel-specification subset** (§2.5): which conditions run on the translated specifications (C1 only is the
   current assumption in Appendix B), and who translates them.
4. **A5 sampling frame**: which tasks, conditions and sub-dimensions A5 trials are drawn from.
5. **Thresholds** (*pilot*): the M1 embedding threshold, the distractor semantic-distance threshold, the number of
   standard deviations for M2's exclusion threshold, and $k_{\max}$ and $\tau$.
6. **H4a non-inferiority margin** for specification recovery against the human ceiling.
7. **Entanglement matrix $E$** (*pilot*): the draft in §5.3 is frozen after the pilot.
8. **Embedding model** for M1 and the distractor filter (multilingual; *pilot*).
9. **C4 token cap** (§3): confirm that C1's pilot median per generator is the right cap, and that the model-call limit
   can enforce it.
10. **Human study**: $R_H$ (2 proposed), recruitment and payment, the rating interface, and ethics approval.
11. **Small-bucket distractors** (§5.5): confirm the nearest-bucket rule for Dutch Detective/Mystery, or add a third item.
12. **Public registry** for the registration (§11).
