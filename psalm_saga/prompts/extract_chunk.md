Analyse the passage below: chunk {{ chunk.index + 1 }} of {{ total }}, from chapter {{ chunk.chapter }}{% if chunk.chapter_title %} ("{{ chunk.chapter_title }}"){% endif %}{% if chunk.part %}, part {{ chunk.part + 1 }}{% endif %}.

Record what a literary scholar would need to reconstruct the story's structure without the text:
- summary: what happens, in order, in 3-8 sentences.
- scenes: every scene boundary (change of time, place or participants). Keep them in order. Give the named place where each happens in `location`, using the place's entity name.
- entities: every named character, place, object or organisation that matters, with aliases used in this passage (nicknames, titles, surnames). Describe characters by concrete traits and behaviour shown here, and give each character's `gender` as the passage presents it (pronouns, forms of address), or `unknown`.
- relations: relationships between entities that this passage shows or implies — between characters (kinship, love, rivalry, employment) and of the story world: a place located in another, a character living or working somewhere, an object owned by or tied to someone, membership of an organisation. Use a short lowercase verb phrase as `type` ("mother of", "lives in", "owns", "member of").
- events: plot-relevant events in causal order, with what caused each. When the cause is an earlier event in your own list, give its 0-based position in `cause_index`; give the place in `location` when it is named.
- style: how the text and narration work here (prose or verse: sentence shape, line and stanza form, metre and rhyme if verse, register, point of view, tense, dialogue habits, irony, imagery). Describe; do not quote more than a few words.

Write all descriptions in your own words and in the language of the passage. Do not invent anything the passage does not support.
{% if known %}
Entities already known from earlier chunks (reuse these exact names when they reappear): {{ known }}
{% endif %}
<passage>
{{ chunk.text }}
</passage>
