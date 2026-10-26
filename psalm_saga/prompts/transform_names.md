Create fresh names for every named entity below, so the synthetic story contains none of the original names.

Rename proper names only. Entities known by a description rather than a name ("the widow", "the old house", "the apple tree", "het meisje", "de moeder") keep their description: return them unchanged or leave them out. A description is not protected and may refer to several people. For a descriptive name that contains a proper name ("the wife of Sir Wallenstein"), replace only the proper name ("the wife of Sir Bredeveld").

Each new name must preserve what the original name *does* for a reader: gender, social class, age cues, region and period{% if keep_culture %} (stay within the source's language and culture{% if language %} — {{ language }}{% endif %}){% endif %}, register (formal surname vs. diminutive), and any obvious connotation (a speaking name gets a different speaking name with a similar effect). Places become different but analogous places; invented places get newly invented names. Avoid famous names, names from other well-known works, and names that differ from the original by only a letter or two.
{% if setting_policy != "preserve" %}
Also describe in `setting_shift` how the concrete setting will be re-invented while keeping its function (same kind of place, period and social world, different particulars).
{% endif %}{% if notes %}
Additional instructions: {{ notes }}
{% endif %}
Entities:
{{ entities }}
