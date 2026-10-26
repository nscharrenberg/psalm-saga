Write {{ unit }} of the story{% if total_chapters > 1 %} — chapter {{ chapter.index }} of {{ total_chapters }}{% endif %}{% if chapter.title %}, "{{ chapter.title }}"{% endif %}. Target length: about {{ target_words }} words (stay within ±15%).

Realise the plan below beat by beat, and make the specification visible on the page: the narrative voice, style targets and character behaviours must be recognisable in the text itself, not just in what happens. Write the finished literary text in the source's form (prose, verse or drama, as described below), not a summary of the beats.

Use the names of the places, objects and characters from the cast notes where the plan has them: a scene set in a named place happens there, by that name.

Output only the text itself. No title, no heading, no "Chapter" label, no notes, no markdown.
{% if rhythm %}
{{ rhythm }}
{% endif %}
{% if variety %}
Write the prose in {{ variety.name }}, not in contemporary standard {{ language }} ({{ variety.scope }}): keep its spelling, word forms, grammar and forms of address throughout, as described in the specification's language-variety section. A modernised text fails the specification even if everything else is right.
{% endif %}
{% if extra %}
Revision note for this draft: {{ extra }}
{% endif %}
{% if prev_tail %}
The text immediately before this point (continue seamlessly, do not repeat it):
<previous>
{{ prev_tail }}
</previous>
{% elif prev_end %}
Where the previous chapter left things: {{ prev_end }}
{% endif %}
# Plan for this {{ unit_name }}
{{ plan }}
