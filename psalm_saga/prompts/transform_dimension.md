Rewrite this dimension specification for the synthetic story. Policy for **{{ dim.label }}**: **{{ policy }}**.
{% if policy == "preserve" -%}
Keep every value as it is, only replacing original names using the rename table and removing any quoted source wording.
{%- elif policy == "abstract" -%}
Keep the *function* of each value — what it does in the story, its role and effect, how it relates to other elements — but re-invent its concrete realisation: new traits, events, objects, animals, places, images, devices and mechanisms that do the same job. A reader who knows the original must not recognise its particulars. Sub-dimensions marked (surface) — {{ surface }} — must get clearly new particulars. For each value, first decide its function in one clause, then describe a new realisation of that function. Everything must stay consistent with the kept dimensions.
{%- else -%}
This dimension is REPLACED. Invent new values for every sub-dimension, as for a different story: do not carry over the source's mechanisms, roles, devices or particulars for this dimension (the source's values are deliberately not shown). Only stay consistent with the dimensions that are kept or re-invented, listed below as context.
{%- endif %}
Use only the new names. Write in the output language. Keep exactly the same sub-dimension keys. Leave `evidence` empty.

Rename table: {{ renames }}
{% if setting_shift %}Setting shift: {{ setting_shift }}{% endif %}

Kept context (other dimensions, already transformed):
{{ context }}

{% if policy == "regenerate" -%}
Sub-dimensions of {{ dim.label }} to fill:
{{ subdims }}
{%- else -%}
Original specification of {{ dim.label }}:
{{ original }}
{%- endif %}
