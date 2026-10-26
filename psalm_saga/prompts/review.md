Check this chapter against its plan and the specification it was written from. Report only clear, checkable violations of explicit commitments — a beat that does not happen, a wrong point of view or tense, a character acting against their specified behaviour, a style target plainly missed, a continuity error, or prose in the wrong language or language variety (for example modern spelling where the specification requires a historical spelling or a dialect). Do not report matters of taste, things the plan leaves open, or things a different writer might have done differently.

Severities:
- blocker: the chapter contradicts the plan or spec in a way a reader would notice (missing key event, wrong POV, wrong language or variety, broken continuity).
- major: a commitment is clearly under-realised (a specified behaviour never shows, a style target is far off).
- minor: everything else worth mentioning. Minor issues never trigger a revision.

For each issue, say where it comes from (`origin`):
- prose: the plan and specification are sound and the chapter fails them. Fixed by editing the chapter.
- plan: the chapter does what its plan says, but the plan is the problem — it contradicts the specification, the cast notes or the story so far, leaves out something the specification requires, or asks for something impossible. Fixed by revising the plan.
- spec or bible: the plan and chapter follow the specification (spec) or the cast and world notes (bible), but those are themselves contradictory or wrong, so no chapter could satisfy them. Use this only when changing the chapter or its plan cannot resolve the problem.
Most issues are prose issues.

A competent draft usually has no blocker or major issues; an empty list is a normal result. Report at most {{ max_issues }} issues, most severe first, each with short evidence and a concrete local fix.

# Plan
{{ plan }}
{% if cast %}
# Cast and world notes (story bible)
{{ cast }}
{% endif %}

# Chapter
{{ text }}
{% if checklist %}

# Design checklist
The story bible this story is written from fixes these facts for this chapter (names as in the story). In `coverage`, give EVERY item its status: realised (the chapter shows it, in any wording), missing (not in the chapter), or contradicted (the chapter says otherwise); say whether the chapter plan includes it (`in_plan`); give short evidence for missing or contradicted items. Do not repeat these items as issues: they become issues automatically.
{{ checklist }}
{% endif %}
