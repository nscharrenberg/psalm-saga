Revise the verse passage below so that its form matches the measured form of the original work. The measurements of the whole piece and the targets:

{{ table }}

What to change:
{% for g in gaps %}- {{ g }}
{% endfor %}
Rules:
- Keep what happens, in the same order, with the same names and details. You may change words at line ends, and the order of words within a line, to make lines rhyme and scan.
- One verse line per line of output; a blank line between stanzas; a poem's title, if the passage has one, on its own line.
- Keep the language ({{ language }}){% if variety %} and the language variety ({{ variety.name }}: its spelling, word forms and forms of address){% endif %}.
- Keep the length: about {{ words }} words (within 10%).
- Output only the revised verse. No comments, no headings.

<passage>
{{ text }}
</passage>
