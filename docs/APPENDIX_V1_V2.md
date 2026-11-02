# Appendix: from the v1 to the v2 experimental design

The main setup ([EXPERIMENTS.md](EXPERIMENTS.md)) stands on its own. This appendix records how
it relates to the earlier PSALM-SAGA study (`EXPERIMENTAL_SETUP.md`, tasks A–D, 14
instruments, mixed-effects models), for readers who know that design.

## A.1 A different claim

The v1 design tested whether *specification-driven story generation is controllable*: that
a story realises the specification it was written from (v1 RQ1), that regenerating one
dimension changes only that dimension (RQ2), and that the specification stage does work the
rest of the pipeline does not (RQ3). Its instruments compare a story with **its own
specification**, mostly through model judges choosing between distractors (A1–A6), and anchor
specification quality to **gold specifications written by the authors** (S2).

The library use case needs another claim: a synthetic text can stand in for **its source** as
data. That changes what has to be measured.

1. **Fidelity to the source, not to a specification.** A story can match a poorly extracted
   specification perfectly and still misrepresent the book. v2 measures the source and the
   synthetic text with the same procedure (F1–F8). In v1 only S2 involved the human source,
   and it compared specifications.
2. **Absence of protected expression.** v1 measured verbatim overlap (M2) as a side check. For
   a release of in-copyright material it is a primary outcome, so v2 adds the longest copied
   span, name leakage, non-literal reuse, distributional divergence and a reconstruction
   attack (D1–D5).
3. **Corpus-level validity.** Researchers analyse corpora. v1 had no corpus-level instrument;
   v2 borrows the utility measures of synthetic-data research (R1–R5), because per-text
   fidelity does not guarantee that comparisons between books survive.
4. **Evidence that does not depend on model judges.** v1's main instruments (A1–A6, S1, Q1)
   were judge-based. v2 puts deterministic instruments first and uses judges where no
   deterministic measure exists, validated against human raters.
5. **Cost.** v1 needed author-written gold specifications for all 36 sub-dimensions of every
   item, double annotation for a ceiling, and several judge trials per item. v2's
   deterministic instruments cost nothing to run; F4 needs one extraction pass per synthetic
   text.

## A.2 Instrument mapping

| v1 instrument | v2 | Note |
|---|---|---|
| M2 verbatim overlap | D1 (extended) | adds longest copied span and spans ≥ 12 words |
| M3 language and length | G1 | language now includes the language variety (F6) |
| Q1 pairwise quality, non-inferiority | G2 | same design |
| S2 specification recovery against gold | F4 against the source | no gold needed: σ(T) vs σ(S); the human subset replaces the double-annotation ceiling |
| A3 / A4 / A5 adherence via attribution | F1–F4 | fidelity measured directly against the source instead of by picking the right specification among distractors |
| A1 / A1b / A2 controllability, M1 lock verification | not in the main design | available as a condition that regenerates one dimension |
| S1 specificity screening, A6 premise attribution | dropped | diagnostic only in v1 |
| — | F1b, F3, F6, F7, F8, KG, D2–D5, R1–R5, human validation | new |

## A.3 Getting v1 analyses back

The controllability study (v1 tasks C/D, A1/A2 with d′) can be run by adding conditions that
regenerate a single dimension (`transform.policy.<dimension>: regenerate`). Gold
specifications, the attribution tasks (A3–A6) and the mixed-effects analysis can be
reinstated if a paper needs them, at the cost listed in A.1 (5).

## A.4 Pipeline changes that affect the experiments

The system changes themselves (workflow instead of an agent, long-context handling, rate
limiting, calibrated review, language and variety handling) are described in
[DESIGN.md](DESIGN.md). Two matter for comparing results across versions: v2's review
reports only violations of explicit commitments and is bounded in rounds, so v1 and v2
"with review" conditions are not the same treatment; and v2 writes from a transformed
specification behind a clean-room boundary, which v1 did not have, so v1 leakage numbers are
not a baseline for v2.
