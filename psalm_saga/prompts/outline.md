Plan the story below as {{ chapters }} chapter(s), about {{ target_words }} words in total. Produce the whole-story arc and, for each chapter, its index, a title (in the output language, no "Chapter N" prefix), a summary of what happens, the POV, and a word budget. Budgets must add up to roughly the total{% if skeleton %}, and follow the relative chapter lengths of the skeleton{% endif %}.
{% if skeleton %}
The chapter structure is given by the skeleton below: keep one chapter per skeleton chapter, in order, with the same events.
{% endif %}
{{ spec }}
{% if skeleton %}
# Skeleton
{{ skeleton }}
{% endif %}
{% if extra %}
Revision note for this plan: {{ extra }}
{% endif %}
{% if form %}
{{ form }}
{% endif %}
