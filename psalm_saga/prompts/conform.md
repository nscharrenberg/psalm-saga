Revise the rhythm and layout of the passage below so that it matches the measured style of the original work. The measurements of the whole chapter and the targets:

{{ table }}

What to change:
{% for g in gaps %}- {{ g }}
{% endfor %}
{% if scaffold %}
{{ scaffold }}

{% endif %}Rules:
- Change sentence and paragraph boundaries, connecting words, punctuation, and direct versus reported speech. Do not add, remove or reorder events, details, names or descriptions.
- Keep the language ({{ language }}){% if variety %} and the language variety ({{ variety.name }}: its spelling, word forms and forms of address){% endif %}, the narrative voice and the tense exactly.
- Keep the length: about {{ words }} words (within 10%).
- Output only the revised passage, with paragraphs separated by blank lines. No comments, no headings.

<passage>
{{ text }}
</passage>
