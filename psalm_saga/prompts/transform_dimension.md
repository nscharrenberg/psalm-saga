Rewrite this dimension specification for the synthetic story. Policy for **{{ dim.label }}**: **{{ policy }}**.
{% if policy == "preserve" -%}
Keep every value as it is, only replacing original names using the rename table and removing any quoted source wording.
{%- elif policy == "abstract" -%}
Keep the *function* and *structure* of each value (what it does in the story, how it relates to other elements) but re-invent its concrete realisation. Sub-dimensions marked (surface) — {{ surface }} — must get clearly new particulars. Everything must stay consistent with the kept dimensions.
{%- else -%}
Invent new values for every sub-dimension, consistent with the dimensions that are kept and with the overall arc.
{%- endif %}
Use only the new names. Write in the output language. Keep exactly the same sub-dimension keys. Leave `evidence` empty.

Rename table: {{ renames }}
{% if setting_shift %}Setting shift: {{ setting_shift }}{% endif %}

Kept context (other dimensions, already transformed):
{{ context }}

Original specification of {{ dim.label }}:
{{ original }}
