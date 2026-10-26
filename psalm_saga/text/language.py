"""Offline language identification and localised structural labels.

Detection is a stop-word profile classifier: fast, dependency-free and reliable on
literary prose of a few hundred words or more, which is all we need it for (deciding
the output language and checking each generated chapter). If `lingua` is installed
it is used instead for better accuracy on short or mixed text.

Structural labels ("Chapter", "Part") are rendered by code, never by the model, so a
Dutch book can't come back with an English `## Chapter` heading.
"""

from __future__ import annotations

import re
from collections import Counter
from dataclasses import dataclass

STOPWORDS: dict[str, set[str]] = {
    "en": set(["the", "and", "of", "to", "a", "in", "that", "it", "was", "he", "i", "his", "she", "her", "you", "with", "as", "had", "for", "on", "at", "not", "be", "but", "they", "by", "this", "have", "from", "which", "or", "one", "were", "all", "we", "there", "their", "him", "been", "so", "said", "would", "when", "what", "an", "who"]),
    "nl": set(["de", "het", "een", "en", "van", "ik", "te", "dat", "die", "in", "is", "hij", "niet", "zijn", "op", "aan", "met", "als", "voor", "had", "er", "maar", "om", "hem", "dan", "zou", "of", "wat", "mijn", "men", "dit", "zo", "door", "over", "ze", "zich", "bij", "ook", "tot", "je", "mij", "uit", "der", "daar", "haar", "naar", "heb", "hoe", "nog", "was", "werd", "wel"]),
    "de": set(["der", "die", "und", "in", "den", "von", "zu", "das", "mit", "sich", "des", "auf", "für", "ist", "im", "dem", "nicht", "ein", "eine", "als", "auch", "es", "an", "er", "hatte", "so", "dass", "sie", "nach", "wird", "bei", "einer", "um", "am", "sind", "noch", "wie", "einem", "über", "einen", "war", "ich", "aber", "ihr", "ihm", "ihn"]),
    "fr": set(["le", "de", "un", "et", "à", "il", "être", "en", "avoir", "que", "pour", "dans", "ce", "qui", "ne", "sur", "se", "pas", "plus", "par", "je", "avec", "tout", "faire", "son", "mettre", "autre", "on", "mais", "nous", "comme", "ou", "si", "leur", "y", "dire", "elle", "avait", "était", "les", "des", "du", "la", "une", "au", "aux"]),
    "es": set(["el", "la", "de", "que", "y", "a", "en", "un", "ser", "se", "no", "haber", "por", "con", "su", "para", "como", "estar", "tener", "le", "lo", "todo", "pero", "más", "hacer", "o", "poder", "decir", "este", "ir", "otro", "ese", "si", "me", "ya", "ver", "porque", "dar", "cuando", "él", "muy", "sin", "vez", "mucho", "los", "las", "del"]),
    "it": set(["il", "di", "che", "e", "la", "a", "per", "un", "in", "essere", "non", "è", "sono", "con", "una", "mi", "si", "ma", "ha", "lo", "come", "le", "da", "io", "questo", "ci", "lui", "anche", "del", "della", "gli", "era", "aveva", "più", "quando", "nel", "alla"]),
    "pt": set(["o", "de", "a", "que", "e", "do", "da", "em", "um", "para", "é", "com", "não", "uma", "os", "no", "se", "na", "por", "mais", "as", "dos", "como", "mas", "foi", "ao", "ele", "das", "tem", "à", "seu", "sua", "ou", "ser", "quando", "muito", "há", "nos", "já", "está", "eu", "também"]),
    "sv": set(["och", "i", "att", "det", "som", "en", "på", "är", "av", "för", "med", "till", "den", "har", "de", "inte", "om", "ett", "han", "men", "var", "jag", "sig", "från", "vi", "så", "kan", "man", "när", "år", "säger", "hon", "under", "också", "efter"]),
    "da": set(["og", "i", "at", "det", "er", "en", "til", "på", "af", "for", "med", "den", "som", "de", "ikke", "han", "har", "et", "var", "jeg", "sig", "fra", "vi", "så", "kan", "man", "når", "hun", "der", "efter", "havde"]),
    "pl": set(["i", "w", "nie", "na", "się", "z", "do", "że", "to", "jest", "jak", "o", "co", "ale", "po", "tak", "za", "od", "jego", "go", "już", "tylko", "przez", "jej", "był", "była"]),
}

LANGUAGE_NAMES = {
    "en": "English", "nl": "Dutch", "de": "German", "fr": "French", "es": "Spanish", "it": "Italian",
    "pt": "Portuguese", "sv": "Swedish", "da": "Danish", "pl": "Polish", "no": "Norwegian", "fy": "Frisian",
}

# Rendered by the assembler. Keep in the language's own conventions.
LABELS: dict[str, dict[str, str]] = {
    "en": {"chapter": "Chapter", "part": "Part", "the_end": "The End"},
    "nl": {"chapter": "Hoofdstuk", "part": "Deel", "the_end": "Einde"},
    "de": {"chapter": "Kapitel", "part": "Teil", "the_end": "Ende"},
    "fr": {"chapter": "Chapitre", "part": "Partie", "the_end": "Fin"},
    "es": {"chapter": "Capítulo", "part": "Parte", "the_end": "Fin"},
    "it": {"chapter": "Capitolo", "part": "Parte", "the_end": "Fine"},
    "pt": {"chapter": "Capítulo", "part": "Parte", "the_end": "Fim"},
    "sv": {"chapter": "Kapitel", "part": "Del", "the_end": "Slut"},
    "da": {"chapter": "Kapitel", "part": "Del", "the_end": "Slut"},
    "pl": {"chapter": "Rozdział", "part": "Część", "the_end": "Koniec"},
    "no": {"chapter": "Kapittel", "part": "Del", "the_end": "Slutt"},
}

_WORD = re.compile(r"[^\W\d_]+(?:['’][^\W\d_]+)?", re.UNICODE)


@dataclass(frozen=True)
class Detection:
    code: str
    confidence: float  # share of stop-word hits that went to the winning language
    scores: dict[str, float]


def _lingua(text: str) -> Detection | None:
    try:
        from lingua import LanguageDetectorBuilder  # type: ignore[import-not-found]
    except ImportError:
        return None
    det = LanguageDetectorBuilder.from_all_languages().build()
    vals = det.compute_language_confidence_values(text[:20000])
    if not vals:
        return None
    best = vals[0]
    code = best.language.iso_code_639_1.name.lower()
    return Detection(code, float(best.value), {v.language.iso_code_639_1.name.lower(): float(v.value) for v in vals[:5]})


def detect_language(text: str, *, use_lingua: bool = True) -> Detection:
    if use_lingua and (d := _lingua(text)) is not None:
        return d
    words = [w.lower() for w in _WORD.findall(text[:60000])]
    counts = Counter(words)
    scores = {lang: float(sum(counts[w] for w in sw)) for lang, sw in STOPWORDS.items()}
    total = sum(scores.values())
    if total == 0:
        return Detection("und", 0.0, scores)
    best = max(scores, key=lambda k: scores[k])
    return Detection(best, scores[best] / total, {k: v / total for k, v in scores.items()})


def language_name(code: str) -> str:
    return LANGUAGE_NAMES.get(code, code)


def label(code: str, key: str) -> str:
    return LABELS.get(code, LABELS["en"])[key]


def language_directive(code: str, variety=None) -> str:
    """Language constraint for every model call; `variety` is a LanguageVariety or None."""
    name = language_name(code)
    head = (f"OUTPUT LANGUAGE: {name} ({code}). Write every word of story text, titles and any natural-language "
            f"field in {name}. Do not translate into or switch to English or any other language, even though these "
            f"instructions are in English. JSON keys stay exactly as specified.")
    if variety is not None and not getattr(variety, "standard", True):
        return (f"{head}\nLANGUAGE VARIETY: the story prose itself (not plans, descriptions or other fields) must be "
                f"written in {variety.name}, NOT in contemporary standard {name}. Keep its spelling system, word "
                f"forms, grammar and forms of address consistently, as the specification's language-variety section "
                f"describes ({variety.scope}). Do not modernise.")
    return f"{head} Use the conventions, idiom and punctuation of literary {name}."
