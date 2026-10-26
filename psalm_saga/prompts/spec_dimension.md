{% if mode == "source" -%}
Describe how the source story realises the dimension **{{ dim.label }}**, for every sub-dimension listed. This description becomes the specification a different writer will follow without ever seeing the source, so it has to be precise enough to reproduce the dimension and specific enough to be checkable:
- Name mechanisms and patterns ("she deflects every question about her father with a chore"), not labels ("guarded").
- Where numbers are available (measured stylometrics below), state them as targets.
- In `evidence`, briefly say what in the source shows this (paraphrase; at most a few quoted words).
- If the source barely exercises a sub-dimension, say so explicitly ("thin: ...") rather than inventing.
{%- else -%}
Decide the dimension **{{ dim.label }}** for a new story, for every sub-dimension listed. Make concrete, specific, mutually consistent choices that a writer can follow and a reviewer can check: name mechanisms and behaviours, not labels. Stay consistent with the premise and with the dimensions already decided. Leave `evidence` empty.
{%- endif %}

Sub-dimensions of {{ dim.label }}:
{% for s in dim.subdimensions %}- {{ s.key }}: {{ s.label }} — {{ s.guidance }}
{% endfor %}
Return one item per sub-dimension, using exactly these keys.
{% if stylometrics %}
Measured stylometrics of the source: {{ stylometrics }}
{% endif %}{% if excerpts %}
Short excerpts for style analysis only (do not reuse their wording):
{{ excerpts }}
{% endif %}
