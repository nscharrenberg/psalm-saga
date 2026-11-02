Re-invent this chapter skeleton for the synthetic story. Keep its STRUCTURE: the same number of scenes in the same order; the same number of events in the same causal order; each event and scene keeps its FUNCTION in the plot (what it changes, who it affects by role, what it causes); the same characters (under their new names) with the same functions.

Change its PARTICULARS{% if policies %} as the policies require ({{ policies }}){% endif %}: for every scene and every event, first decide its function in one clause, then tell a NEW realisation of it — different concrete actions, contests, tricks, objects, animals, places, weather, images and dialogue occasions that do the same job. A reader who knows the original must not recognise any event from its particulars (if the original has a rigged contest with a weighted animal, the new one rigs something else in another way). Keep each scene's `mode` (how it is told) as it is. Follow the transformed specification and the setting shift.
{% if too_close %}
A previous attempt kept these items too close to the original; tell each of them with clearly different particulars:
{{ too_close }}
{% endif %}
Rename table: {{ renames }}
{% if setting_shift %}Setting shift: {{ setting_shift }}{% endif %}

Transformed specification (excerpt):
{{ spec }}

Original chapter {{ chapter.index }} skeleton (already renamed):
{{ skeleton }}
