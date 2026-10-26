"""Language variety: dialect, sociolect and historical spelling as a measurable property.

A variety is described in words (for the writer) and by *marker pairs* — a form as the
variety spells or uses it, and its contemporary-standard equivalent ("mensch"/"mens",
"zoo"/"zo", "gij"/"jij", "ain't"/"isn't"). Markers proposed by the model are kept only
if the source actually uses them, so the profile is anchored in the text. The share of
variety forms among all marker occurrences,

    share = variety / (variety + standard)

is computed the same way on source and synthetic text: 1.0 means fully in the variety,
0.0 means fully modernised. Single words and short forms only — never phrases from the
source — so the markers carry no protected expression.
"""

from __future__ import annotations

import re
from collections import Counter

from psalm_saga.artifacts import LanguageVariety, VarietyMarker

_DIALOGUE = re.compile(r"^\s*[\"“„«‘'—–-]")
MIN_OCCURRENCES = 8  # below this many marker hits, a share is too noisy to act on


def _pattern(form: str) -> re.Pattern:
    return re.compile(rf"(?<![\w'’]){re.escape(form.strip())}(?![\w'’])", re.IGNORECASE)


def count_forms(text: str, forms: list[str]) -> Counter:
    c: Counter = Counter()
    for f in {f.strip() for f in forms if f and f.strip()}:
        c[f] = len(_pattern(f).findall(text))
    return c


def scoped_text(text: str, scope: str) -> str:
    """Dialogue-only varieties are measured on dialogue paragraphs."""
    if "dialogue" in (scope or "").lower() and "narration" not in (scope or "").lower():
        paras = [p for p in re.split(r"\n\s*\n", text) if _DIALOGUE.match(p) or "„" in p[:3] or "“" in p[:3]]
        return "\n\n".join(paras)
    return text


def marker_tally(text: str, markers: list[VarietyMarker]) -> tuple[int, int, Counter, Counter]:
    var = count_forms(text, [m.variety_form for m in markers])
    std = count_forms(text, [m.standard_form for m in markers if m.standard_form])
    return sum(var.values()), sum(std.values()), var, std


def variety_share(text: str, variety: LanguageVariety | None, *, min_hits: int = MIN_OCCURRENCES) -> dict | None:
    """Share of variety forms in `text`; None when there is nothing to measure."""
    if not variety or variety.standard or not variety.markers:
        return None
    body = scoped_text(text, variety.scope)
    v, s, var, std = marker_tally(body, variety.markers)
    if v + s < min_hits:
        return {"variety": v, "standard": s, "share": None}
    return {"variety": v, "standard": s, "share": round(v / (v + s), 3),
            "top_standard_forms": [f for f, n in std.most_common(8) if n],
            "top_variety_forms": [f for f, n in var.most_common(8) if n]}


def looks_like_name(source: str, form: str) -> bool:
    """A form written with a capital in mid-sentence most of the time is a name, not a variety marker."""
    hits = [mt for mt in _pattern(form).finditer(source)]
    if not hits:
        return False
    mid = [mt for mt in hits if not re.search(r"(^|[.!?…:]\s*[\"“„«‘']?\s*)$", source[max(0, mt.start() - 4) : mt.start()])]
    caps = [mt for mt in mid if mt.group(0)[:1].isupper()]
    return bool(mid) and len(caps) / len(mid) > 0.5


def verify_markers(source: str, proposed: list[VarietyMarker], *, min_count: int = 2, max_markers: int = 40) -> list[VarietyMarker]:
    """Keep only markers the source actually uses, and uses predominantly; never names."""
    kept, seen = [], set()
    for m in proposed:
        vf, sf = m.variety_form.strip(), m.standard_form.strip()
        if not vf or vf.lower() == sf.lower() or vf.lower() in seen or len(vf) > 40:
            continue
        if looks_like_name(source, vf):
            continue
        nv = len(_pattern(vf).findall(source))
        ns = len(_pattern(sf).findall(source)) if sf else 0
        if nv >= min_count and nv > ns:
            seen.add(vf.lower())
            kept.append(VarietyMarker(variety_form=vf, standard_form=sf, feature=m.feature))
    # Prefer the most frequent markers: they give the most stable measurement.
    kept.sort(key=lambda m: -len(_pattern(m.variety_form).findall(source)))
    return kept[:max_markers]


def mismatch_note(text: str, variety: LanguageVariety, language_name: str) -> str | None:
    """A correction for the writer when a draft drifted toward the standard language."""
    # A chapter is short, so act on fewer hits than the whole-story evaluation does: against a source
    # that is (say) 95% variety forms, 0 variety forms among 4+ hits is already decisive.
    m = variety_share(text, variety, min_hits=4)
    target = variety.source_share
    if not m or m["share"] is None or target is None or target < 0.5:
        return None
    if m["share"] >= max(0.5 * target, target - 0.35):
        return None
    pairs = [mk for mk in variety.markers if mk.standard_form in m.get("top_standard_forms", [])][:8]
    examples = "; ".join(f"{p.variety_form} (not {p.standard_form})" for p in pairs)
    return (f"IMPORTANT: the previous attempt drifted into modern standard {language_name} "
            f"({int(100 * m['share'])}% variety forms; the source has {int(100 * target)}%). "
            f"Write consistently in {variety.name}." + (f" For example: {examples}." if examples else ""))


def resolve(config_value: str, detected: LanguageVariety | None, style_policy: str) -> LanguageVariety | None:
    """Which variety the synthetic text must be written in.

    auto      the detected variety, unless the writing-style policy is `regenerate`
    modern    always the contemporary standard (a modernised corpus)
    <text>    a variety described by the user, e.g. "Brabants dialect in the dialogue"
    """
    v = (config_value or "auto").strip()
    if v.lower() in {"modern", "standard", "none"}:
        return None
    if v.lower() == "auto":
        if style_policy == "regenerate" or not detected or detected.standard:
            return None
        return detected
    return LanguageVariety(standard=False, name=v, description=v)
