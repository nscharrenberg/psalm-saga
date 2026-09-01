# Experimental Setup

## 1. Research Questions

**RQ1 (Adherence).** Does a story generated from a specification instantiate the values that specification names?

- **H1a.** Given a source story and one of its dimension variants, a blind judge identifies which of the six dimensions
  was regenerated at a rate above chance ($\frac{1}{6}$).
- **H1b.** Given a specification and two stories, one generated from it and one from a different specification, a blind
  judge identifies the correct story above chance ($\frac{1}{2}$).
- **H1c.** Adherence varies across dimensions, with lower identification accuracy for the six functional sub-dimensions
  than for the concrete ones.
- **H1d.** Manipulation is specific. When a judge identifies the regenerated dimension correctly, that judge reports no
  change in the five locked dimensions at a rate above the false-alarm baseline.

**RQ2 (Contribution of the specification).** Does the specification stage do work the rest of the pipeline does not?

- **H2a.** Stories from the full pipeline instantiate a target specification more often than stories from the
  no-specification ablation given the same premise.
- **H2b.** Stories from the full pipeline instantiate a supplied specification more often than a single-call baseline
  given the same specification in its prompt.
- **H2c.** The review-and-repair loop improves adherence over the no-review ablation.

**RQ3 (Specification production).** When the system writes a specification from a human-written story, does it recover
the properties a human annotator recorded for that story?

- **H3a.** System-to-gold agreement is non-inferior to human-to-human agreement measured on the double-annotated subset.
  The human ceiling, not an absolute threshold, is the comparison.
- **H3b.** Recovery is lower for the six functional sub-dimensions than for the concrete ones, mirroring H1c. Agreement
  between H1c and H3b would locate the difficulty in the taxonomy; divergence would locate it in the pipeline.
- **H3c.** Recovery is lower in Dutch than in English.

**RQ4 (Quality guardrail).** Is specification-driven output non-inferior in quality to the unstructured baselines?

- **H4a.** Full-pipeline stories are not worse than flat-baseline stories by more than a pre-specified margin, tested by
  two one-sided tests following the equivalence approach of Scharrenberg and Sun [2026].
- **H4b.** Adherence and quality do not correlate negatively within condition. CS4 reports quality decaying as
  story-writing constraints accumulate [Atmakuru et al., 2024], so a negative correlation here would be a finding rather
  than a nuisance.
- **H4c.** Human-written source items are preferred over all system conditions. This anchors the quality scale and
  serves as a validity check on the instrument; a null would impugn the instrument.

**RQ5 (Specification provenance).** Does adherence depend on who wrote the specification?

- **H5a.** Adherence is higher for system-authored specifications than for human-authored gold specifications. A
  positive result quantifies constraint self-selection, the tendency of a system to specify what it already writes well.
- **H5b.** Variant chains built from system-authored specifications show higher lock fidelity than those built from
  extracted specifications, isolating the cost of extraction error.

RQ1 and RQ2 are primary. RQ3 and RQ5 are secondary and diagnostic. RQ4 is a guardrail whose failure would qualify the
other results without its success being a contribution.

## 2. Corpus

### 2.1. Source Stories

Fifteen English and fifteen Dutch source items, thirty in total. English sources come from Project Gutenberg, Dutch
sources from the Digital Library of Dutch Literature (DBNL), all public domain within the European Union. Each item is a
self-contained short story, a single chapter, or a coherent excerpt, normalised to $1200-2000$ words.

The short target length is deliberate. It keeps generation costs within reach of a small team, and it keeps items short
enough for a human rater to read one in full instead of judging from an excerpt, which removes an entire class of
confound from the human study.

Sources are stratified across five genre buckets per language, three items each, fixed before selection. Bucket
membership matters downstream, since distractors in the attribution instruments are drawn from within bucket.

### 2.2. Gold Specifications

Each source item receives a gold specification: an explicit answer for all 36 sub-dimensions describing that item. A
model drafts candidate answers from the source text, then an author reviews and rewrites every answer against the
dimension criteria. Authors record which answers they rewrote and how far, producing a
machine-drafted-versus-human-rewritten ratio per sub-dimension that is itself reportable.

Ten items, five per language, are specified independently by two authors. Their agreement establishes whether the 36
questions can be answered consistently from a text at all, and it supplies the ceiling against which H3a is tested.
Without this subset, RQ3 would have no principled benchmark, since a gold specification is one valid description among
many and deviation from it is not straightforwardly error.

### 2.3. Scratch Sub-Corpus

Ten additional items, five per language, are produced in scratch mode: the system elicits answers to the 36 questions,
an author reviews the resulting specification, and generation proceeds from it. No source text is involved.

This sub-corpus is small because its job is comparison rather than primary estimation, and it earns its place three
times over. It removes the extraction step, so variant chains descend from specifications that were authored directly
instead of inferred from a human story, which isolates how much extraction error costs the Task C results. It removes
the memorisation confound entirely, since there is no source text to recall, so a replication of the adherence result
here cannot be dismissed as regurgitation of public-domain literature. And it makes RQ5 answerable: comparing adherence
on system-authored against human-authored specifications measures constraint self-selection, which has not been
quantified for specification-driven story generation.

Author review of scratch specifications additionally yields interactive-mode data at no extra cost. Elicitation time,
question count, and the proportion of drafted answers the reviewer rewrote are logged and reported descriptively. This
does not substitute for a user study of the interactive mode, and we present it as characterisation rather than
evaluation.

### 2.4. Language Design

The two language corpora are constructed independently, not by translation. Translation rewrites precisely the
properties the Writing Style and Narrative Voice dimensions describe, so a translated Dutch corpus would test the system
against a register no Dutch author produces.

Independent corpora leave one question unanswerable: whether an English-Dutch difference reflects the language or the
difficulty of the items. A parallel-specification subset addresses this cheaply. Six gold specifications, three per
language, are translated into the other language, with Writing Style sub-dimensions adapted where they reference
language-specific features and every adaptation logged. Generation then runs from matched specification content in both
languages. A specification is a fraction of a story's length, so this costs six translations rather than six stories.

## 3. Conditions

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
specification into a prompt, which would be the most consequential negative result the study could produce.

C4 is matched to C1 on review iterations and token budget, so the C1–C4 contrast tests the taxonomy and not the compute.

C6 guards against C4 being a strawman. Agents' Room decomposes narrative generation into specialised agents under an
orchestrator without a dimensional specification, placing it in the same architectural family as C4 but with an
independently published design. If C4 and C6 behave alike, the no-specification ablation is a fair representative of
plan-and-write architectures. Availability is a risk. If the framework cannot be run as published it is reimplemented
from the paper description and reported as such, and if that also proves infeasible it is dropped with the omission
stated.

## 4. Generation Tasks

|                                  | C1 | C2 | C3 | C4 | C5 | C6 | C7 |
|----------------------------------|----|----|----|----|----|----|----|
| **A** premise → story            | ✓  | ✓  | —  | ✓  | ✓  | ✓  | ✓  |
| **B** specification → story      | ✓  | ✓  | ✓  | —  | —  | —  | —  |
| **C** source → variant           | ✓  | —  | —  | —  | —  | —  | —  |
| **D** scratch → story + variants | ✓  | —  | —  | —  | —  | —  | —  |

**Task A** derives a premise from each source item, written to describe the situation without prescribing the telling,
and runs all conditions on it. C1 and C2 write their own specification first, which is retained and evaluated.

**Task B** supplies the gold specification directly to the specification-consuming conditions. This separates adherence
from specification-writing ability, which matters because a system that writes vague specifications and follows them
faithfully would be indistinguishable from one that writes sharp specifications and follows them poorly, if only Task A
were measured.

**Task C** has C1 extract a specification from the human text, then produce six variants, one per dimension, each
regenerating that dimension and locking the other five.

**Task D** repeats Task C's variant procedure on the scratch sub-corpus, where the specification was authored rather
than extracted.

Two generator families run every task: a frontier API model and a smaller open-weight model. A third from the
EU-oriented multilingual family is included only if it clears the pilot gate of Section 7.

Story counts: Task A, $30 \times 6 \times 2 = 360$; Task B, $30 \times 3 \times 2 = 180$; Task
C, $30 \times 6 \times 2 = 360$; Task D, $10 \times 7 \times 2 = 140$.
The corpus totals $1040$ generated stories of $1200–2000$ words, alongside $30$ human items.

## 5. Instruments

Instruments are grouped by what they cost and what they can establish. The mechanical checks run first, since failures
there invalidate everything downstream.

### 5.1. Mechanical checks (no judge)

**M1: Lock verification.** For every variant, a diff between source and variant specification confirms that locked
sub-dimensions are byte-identical and unlocked ones changed. Failures are system faults: logged, regenerated, and
reported as a rate. Textual change is necessary but not sufficient, since a paraphrase satisfies it while defeating the
purpose, so unlocked values are additionally screened for semantic non-equivalence against a pre-registered embedding
threshold, with 10% audited by an author.

**M2: Verbatim overlap.** Shared 8-gram rate between each generated story and its source item, against a matched
non-source baseline, with a pre-registered exclusion threshold. Public-domain literature is likely present in
pretraining data, so this distinguishes generation from recall. Task D items require no screening, which is part of
their value.

### 5.2. Specification-level instruments

**S1: Specificity screening.** Three binary checks per specification value, taken from the dimension criteria:
does the value name a realised property, is it testable against text, does it commit where the sub-dimension admits a
spectrum. Applied to every specification the system writes and to the gold specifications.

This closes a weakness conceded in the methodology, where specification quality is applied by judgement with no
independent
instrument. It also feeds RQ3 by separating two failure modes that otherwise look identical: a system that writes a
vague specification and one that writes a sharp specification and then ignores it.

**S2: Recovery against gold.** For each source item, the specification C1 extracted from the human story is compared
against the gold specification, sub-dimension by sub-dimension, on three levels: *matches* the gold answer in substance,
*partially matches*, or *conflicts with or omits* it. Supplies H3a–H3c.

Because gold specifications are drafted with model assistance, the judge pool for S2 excludes any family used in
drafting. Otherwise the instrument would partly measure a model's agreement with its own earlier output.

### 5.3. Adherence instruments (objective, ground truth by construction)

**A1: Dimension identification.** The primary measure. A judge sees the source story and one variant, together with the
six dimension names and one-line definitions, and answers which dimension was regenerated.

> Two versions of the same story appear below. They were written from specifications identical except in one of six
> respects. Which one?
>
> **Version A:** {…}  **Version B:** {…}
>
> Writing Style / Narrative Voice / Character / Plot Structure / Scene Sequence / World-Building / Cannot tell
>
> In one sentence: what led you to that answer?

Chance is $\frac{1}{6} \approx 0.167$ and ground truth is the unlocked set, known by construction. The task needs no
rubric, no anchor
descriptions and no rater calibration, and humans and model judges perform it identically, which makes their agreement
directly interpretable.

The confusion matrix over the six dimensions is the more informative output. Its diagonal tests H1a; its off-diagonal
shows which dimensions bleed into which. Systematic confusion between Writing Style and Narrative Voice, say, would be a
finding about the taxonomy and not about the generator.

"Cannot tell" is offered so raters do not guess. Primary analysis covers decided items with the abstention rate reported
alongside; a secondary analysis scores abstentions as incorrect.

**A2: Non-target drift.** A follow-up question attached to A1: besides the dimension you identified, did anything else
change? Answered per dimension as yes/no.

A1's confusion matrix reaches specificity only indirectly. A2 tests the lock at story level, and because it yields both
a hit rate on the manipulated dimension and a false-alarm rate on the locked ones, it supports d′ in place of raw
accuracy. It supplies H1d. Keeping it as a follow-up rather than converting A1 into a select-all task preserves A1's
clean scoring.

**A3: Specification-story matching.** A judge sees a specification and two stories, one generated from it and one from
a different specification in the same language and genre bucket, and identifies which story was written from it. Chance
is $\frac{1}{2}$, presentation order counterbalanced.

Across C1, C2 and C3 in Task B this yields H2b. Across C1 and C4 in Task A, with the gold specification as target and
neither system having seen it, it yields H2a: how much adherence a premise alone buys.

**A4: Story-specification attribution.** The converse direction. A judge sees one story and three candidate
specifications, the true one and two from the same language and genre bucket, and identifies which the story was written
from. Chance is $\frac{1]{3}$.

A4 measures the same underlying construct as A3 from the opposite side, which makes the pair a convergent-validity check
when run on an overlapping sample. It is also far cheaper in human time: reading one story and three short
specifications takes roughly a third as long as reading three stories. For that reason A4 carries the larger share of
the human subset while A3 carries the larger share of the model-judge volume.

Three alternatives rather than four is a deliberate ceiling. With three items per genre bucket, only two same-bucket
distractors exist, and drawing a fourth from outside the bucket would let judges solve the task on content.

**A5: Sub-dimension recovery.** For a sampled subset of sub-dimensions, a judge sees the story and four candidate
values for one sub-dimension, one correct and three from other items' specifications for the same sub-dimension. Chance
is $\frac{1}{4}$, distractors filtered for semantic distance and $10\%$ audited.

This is the only instrument reaching sub-dimension resolution. Human validation at that resolution is out of reach at
this scale, so results are automatic-only and reported as descriptive.

**A6: Premise attribution.** A judge sees one story and three premises, the true one and two from the same language and
genre bucket, and identifies which the story was written from. Chance is $\frac{1]{3}$.

A6 is not a result. Every condition should approach ceiling, since being about the right premise is basic
prompt-following. Its function is calibration: an accuracy of $0.40$ on a six-way dimension task means nothing to a
reader
who does not know what a judge's ceiling looks like on this corpus. Reporting that judges reach $0.94$ on premise
attribution and 0.40 on dimension identification frames the second number properly, and a condition falling below
ceiling on A6 signals a generation failure that would otherwise be misread as poor adherence.

### 5.4. Quality instrument

**Q1: Pairwise preference.** Thirty items $\times$ 3 contrasts (C1–C5, C1–C4, C1–C7) $\times 2$ generators $= 180$
comparisons, both
orders, condition labels stripped. Judges answer which story they would rather read and, separately, which is more
internally consistent.

Quality is tested for non-inferiority, not superiority. The margin is pre-registered at a win rate of $0.40$ for C1
against C5. H4b is tested by correlating each story's Q1 outcome with its A3 and A4 outcomes within condition.

### 5.6. Instrument budget

| Instrument          | Items         | Model-judge calls | Human share | RQ          |
|---------------------|---------------|-------------------|-------------|-------------|
| M1 lock             | $480$         | $0$               | —           | RQ1         |
| M2 overlap          | $1040$        | $0$               | —           | threat      |
| S1 specificity      | $1440$ values | $\approx 2880$    | small audit | RQ3         |
| S2 gold recovery    | $1080$ cells  | $\approx 2160$    | audit       | RQ3         |
| A1 dimension ID     | $480$         | $1440$            | **largest** | RQ1, RQ5    |
| A2 drift            | (with A1)     | $0$ extra         | with A1     | RQ1         |
| A3 matching         | $240$         | $720$             | small       | RQ1, RQ2    |
| A4 attribution      | $240$         | $720$             | **large**   | RQ1, RQ2    |
| A5 sub-dim recovery | $540$         | $1620$            | none        | RQ1         |
| A6 premise anchor   | $120$         | $360$             | small       | calibration |
| Q1 quality          | $180$         | $1080$            | small       | RQ4         |

Roughly $11000$ model-judge calls, each short. The human subset is $150$ items at floor and $300$ at target, allocated
first
to A1, then A4, then Q1.

## 6. Judges

Three model families judge every instrument, none drawn from the generator set, which designs self-preference out
instead of correcting for it afterwards. Each judge produces a rationale before its verdict, returns structured output,
and sees items in randomised order, with both presentation orders run for pairwise instruments.

Human judgement covers a stratified subset of the same instruments, never a separate rubric. Because the tasks have
ground truth, human raters can be authors, colleagues, crowdworkers or domain experts without changing the analysis:
blinding and randomisation make rater identity inert where the correct answer is fixed by construction. Authors who
contributed gold specifications do not judge items derived from them.

Rater materials include five training items with feedback and catch trials at $10\%$, constructed so the manipulated
dimension is unmistakable. Raters below $80\%$ on catch trials are excluded, with exclusions reported and the analysis
rerun including them.

Pool entry requires clearing two gates: exceeding chance on the catch trials humans receive, and producing parseable
structured output on at least $95\%$ of calls. Smaller multilingual models are plausible generators and unreliable
judges,
and this decides the question empirically.

## 7. Pilot

Three source items per language pass through every task and condition before the confirmatory run. Pilot data are
excluded from analysis.

The pilot settles whether the smaller open-weight models can produce coherent $1500$-word stories and valid $36$-field
specifications at all; whether candidate judges clear the Section 6 gates; the observed abstention rate on A1, which
drives the sample-size check; and the median human time per item, which converts the rater budget into an item count. A
model failing the pilot is dropped and the pilot report states why. This is the mechanism for deciding on the EU
multilingual models, in place of committing to them in advance.

## 8. Analysis

This section states how a pile of judge verdicts becomes a defensible result. The obstacles are these.

**Judgements are not independent.** Twelve of the $480$ dimension-identification items come from the same source item,
and
a third of all items are seen by the same judge. Some items are inherently easier, and some judges are more accurate
than others. Treating every judgement as an independent observation would understate the true uncertainty and produce
confidence intervals narrower than the data support. Random intercepts for source item and judge account for this.

**The null is not $50\%$.** Chance differs by instrument: $\frac{1}{6}$ for A1, $\frac{1}{2}$ for A3, $\frac{1}{3}$ for
A4 and A6, $\frac{1}{4}$ for A5. Each model
is offset so that its intercept tests against the correct chance level.

**Many tests invite false positives.** Six dimension tests, three condition contrasts and two language contrasts
together approach twenty comparisons, at which one spurious result is expected by chance alone.

The primary models are mixed-effects logistic regressions on judgement correctness:

```
correct ~ dimension + language + provenance + (1 | source_item) + (1 | judge)
```

for A1, where `provenance` distinguishes extracted from scratch-authored specifications and supplies H5a, and

```
correct ~ condition + language + (1 | source_item) + (1 | judge)
```

for A3, A4 and A5, from which the H2a–H2c contrasts are drawn. Where a model fails to converge at this sample size, the
pre-registered fallback is a per-cell exact binomial test with Wilson intervals. It is registered as the fallback in
advance, never selected after seeing results.

Effect sizes are reported as marginal probabilities with $95\%$ intervals alongside odds ratios, and every p-value is
accompanied by both. Multiple comparisons are controlled by Benjamini-Hochberg at $q = 0.05$ within three declared
families: per-dimension chance tests, condition contrasts, and language contrasts. Families are not pooled, and
sub-dimension analyses from A5 are exploratory and labelled as such.

A2 is analysed as a signal-detection problem, reporting hit rate on the manipulated dimension against false-alarm rate
on locked dimensions, summarised as $d'$.

Reliability is reported as Krippendorff's $\alpha$ across model judges, per instrument and per dimension, and as
Cohen's $\kappa$
between the model majority and human labels. Convergence between A3 and A4 on their overlapping sample is reported as a
correlation, since the two instruments target the same construct from opposite directions and their agreement bears on
whether either measures it.

A judge that is $80\%$ accurate reports an accuracy that is a biased estimate of the true rate. Where judge and human
labels coexist, accuracy is therefore additionally reported with the Rogan-Gladen correction, using sensitivity and
specificity estimated from the human subset. This is what allows roughly $150$ human labels to support valid statements
about more than a thousand automatic ones.

H4a and H3a are tested by two one-sided tests against their pre-registered margins. H4b is a within-condition
correlation between quality and adherence outcomes.

## 9. Sample Size

The purpose of this section is to prevent one specific outcome: running everything, obtaining a null, and being unable
to say whether there was no effect or whether the study was too small to detect one. Fixing the detectable effect in
advance is what makes a null interpretable.

Dimension identification against a chance level of $0.167$, at $\alpha = 0.05$ and $80\%$ power, requires $28$
independent items to
detect an accuracy of $0.40$ and $43$ to detect $0.35$. Tasks C and D together supply $480$ items, $80$ per dimension,
so
per-dimension tests are adequately powered for effects at or above $0.35$ even after correction. The pooled test is
powered far beyond requirement.

Matching against a chance level of $0.5$ requires $47$ items to detect $0.70$ and $98$ to detect $0.65$. Task B
supplies $240$ items
across three conditions, $80$ per condition, powering the design for adherence at or above $0.70$ per condition.
Attribution
against a chance level of $\frac{1}{3}$ requires $36$ items to detect $0.60$, so A4 is comfortably powered at the same
volume.

Pairwise condition contrasts are less well powered than the against-chance tests. We pre-register a smallest effect size
of interest of $15$ percentage points for those contrasts and state that the study cannot detect effects below it.

The design is deliberately better powered for RQ1 than for RQ2. Establishing that specifications control output is the
prior question, and we would rather report a well-estimated primary result with a wide interval on the ablation ordering
than underpower both.

## 10. Threats and Controls

| Threat                                        | Control                                                                                                       |
|-----------------------------------------------|---------------------------------------------------------------------------------------------------------------|
| Circularity between generator and evaluator   | PSALM is used nowhere in this evaluation; internal verifier verdicts are never reported as results            |
| Self-preference                               | Judge families disjoint from generator families                                                               |
| Shared authorship of gold specs and judges    | The drafting model's family is excluded from the S2 judge pool                                                |
| Constraint self-selection                     | Scratch sub-corpus and RQ5 measure it directly instead of controlling it away                                 |
| Extraction error contaminating variant chains | Task D repeats Task C without an extraction step                                                              |
| Survivorship from the repair loop             | Abandonment rate reported; analyses rerun including last drafts of abandoned runs                             |
| Length confound                               | Target band enforced; realised length reported per condition and entered as a covariate where medians diverge |
| Position bias                                 | Pairwise items run in both orders; inconsistency rate reported                                                |
| Memorisation of public-domain sources         | M2, with Task D as the memorisation-free replication                                                          |
| Compute confound in C4                        | C4 matched to C1 on review iterations and token budget                                                        |
| Distractor artefacts                          | Distractors drawn from real specifications within language and genre bucket, embedding-filtered, 10% audited  |
| Judge ceiling unknown                         | A6 establishes it on this corpus                                                                              |
| Language-difficulty confound                  | Parallel-specification subset (Section 2.4)                                                                   |

## 11. Reproducibility

Frozen and published before the confirmatory run:

- Hypotheses with primary/secondary designation, smallest effect size of interest, non-inferiority margins, and the
  analysis plan including convergence fallback, abstention handling and exclusion rules, timestamped on a public
  registry
- The $30$ source items with provenance and licence, both gold specification sets, the double-annotated subset, the
  scratch sub-corpus, and the parallel-specification translations with their adaptation log
- Model identifiers with exact revisions, decoding parameters per stage, seeds, and the repair bound k_max and
  threshold $\tau$
- All prompt templates, versioned and content-hashed: elicitation, planning, drafting, internal verification, repair,
  and every judge instrument
- Item construction and randomisation scripts, distractor generation with its threshold, rater instructions, training
  items and catch trials
- Raw per-judge and per-rater responses at item level, not aggregates
- Full generation traces, including abandoned runs
- Analysis code with an environment lockfile

## 12. Reduction Path

If capacity contracts, the order of reduction is fixed in advance. Tasks C and D with instruments A1 and A2 are retained
under all circumstances, since they carry RQ1 and RQ5. Task B with A3 and A4 goes next, carrying RQ2. First to be cut is
Q1, then C6, then A5, then the second generator family on Tasks C and D, then the corpus from $15$ to $10$ items per
language. A6 is cheap enough to retain throughout, since without it the primary number cannot be interpreted.

A study consisting of Tasks C and D, dimension identification with drift across three model judges, and a $150$-item human
subset is publishable on its own. It answers whether a specification controls what a generator produces, which is the
question the contribution rests on.

Equivalent strategy can be used when requiring an increase in experiment size and/or corpus size.
