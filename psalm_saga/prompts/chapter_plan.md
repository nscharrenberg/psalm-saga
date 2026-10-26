Expand chapter {{ chapter.index }} of the story plan into scenes. For each scene give: a summary, setting (name the place as the story bible names it), characters present (by their names in the bible), 3-7 concrete beats in order, its purpose, and a word budget (scene budgets add up to ~{{ chapter.target_words }}). Then list the spec commitments this chapter must visibly realise (cite sub-dimension keys with a few words each) and state where things stand at the chapter's end.

Be specific: beats are things that happen on the page ("Mara burns the letter unread, then lies about it at supper"), not intentions ("tension rises").
{% if skeleton %}Follow this skeleton for the chapter: same scenes, same order, same events.
{{ skeleton }}
{% endif %}
Whole-story arc: {{ arc }}
Chapter outline: {{ outline_line }}
Previous chapter ends: {{ prev_end or "(this is the first chapter)" }}
Next chapter: {{ next_line or "(this is the last chapter)" }}
{% if extra %}
Revision note for this plan: {{ extra }}
{% endif %}
{% if form %}
{{ form }}
{% endif %}
