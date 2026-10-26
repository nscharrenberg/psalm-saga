Write a complete story of about {{ target_words }} words{% if chapters > 1 %} in {{ chapters }} chapters{% endif %}.
{% if source %}
It must be a synthetic counterpart of the source story below: keep its structure, events and their order, character functions and relationships, narrative voice and style (including its language variety: dialect, historical spelling, archaic forms), but use entirely new names, new concrete particulars, and your own wording throughout — no sentence or distinctive phrase may be taken from the source.
{% endif %}{% if spec %}
Follow this specification:
{{ spec }}
{% endif %}{% if premise %}
Premise:
{{ premise }}
{% endif %}
{% if chapters > 1 %}Separate chapters with a line containing only "[[CHAPTER: <title>]]". {% endif %}Output only the story text, no other headings or commentary.
{% if source %}
<source>
{{ source }}
</source>
{% endif %}
