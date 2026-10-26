"""Deterministic offline model for tests, CI and dry runs (`models.default.name=fake/any`).

Produces schema-valid JSON for structured calls and language-appropriate filler prose of
roughly the requested length for text calls, so the whole pipeline — chunking, rate
limiting, checkpointing, language checks, assembly, metrics — runs without a provider.
"""

from __future__ import annotations

import hashlib
import json
import random
from typing import Any

from pydantic import BaseModel

from psalm_saga.text.language import STOPWORDS

_CONTENT = {
    "en": ["house", "sea", "night", "letter", "garden", "road", "window", "lamp", "river", "winter", "bread", "morning", "voice", "door", "field", "hand"],
    "nl": ["huis", "zee", "nacht", "brief", "tuin", "weg", "venster", "lamp", "rivier", "winter", "brood", "ochtend", "stem", "deur", "veld", "hand"],
    "de": ["Haus", "Meer", "Nacht", "Brief", "Garten", "Weg", "Fenster", "Lampe", "Fluss", "Winter", "Brot", "Morgen", "Stimme", "Tür", "Feld", "Hand"],
    "fr": ["maison", "mer", "nuit", "lettre", "jardin", "route", "fenêtre", "lampe", "rivière", "hiver", "pain", "matin", "voix", "porte", "champ", "main"],
}
_NAMES = {
    "en": ["Agnes Hale", "Tom Ware", "Mrs. Pell", "Harrow End"],
    "nl": ["Geertje Bos", "Teun Wit", "juffrouw Pel", "Hoogwoude"],
    "de": ["Grete Kühn", "Anton Wehr", "Frau Pell", "Hohenau"],
}


class FakeRateLimit(Exception):
    """Mimics a provider 429 carrying a Retry-After hint."""

    status_code = 429


class FakeBackend:
    """Fault injection via the model's `extra` config (for tests):
      fake_rate_limit_every: N   every Nth call raises a 429 "try again in 0.05s"
      fake_hang_every: N         every Nth call sleeps past the timeout
      fake_wrong_language: code  prose calls answer in this language on their first attempt
      fake_bad_json_every: N     every Nth structured call returns invalid JSON
      fake_length_ratio: f       prose comes back at f x the requested length
      fake_latency_s: s          each call takes about s seconds (to watch a run live)
      fake_reasoning_tokens: n   report n reasoning tokens (and a reasoning text) per call
    """

    def __init__(self, seed: int = 0):
        self.seed = seed
        self.calls = 0

    def _rng(self, key: str) -> random.Random:
        return random.Random(int(hashlib.sha256(f"{self.seed}:{key}".encode()).hexdigest()[:12], 16))

    @staticmethod
    def _verse(text: str) -> str:
        """Lay filler prose out as rhymed verse: 6-word lines, couplets, 4-line stanzas."""
        toks = text.replace("\n", " ").split()
        rhymes = ["maan", "gaan", "staan", "slaan", "hoek", "boek", "zoek", "doek"]
        lines = [" ".join(toks[i : i + 5]) + " " + rhymes[(i // 10) % len(rhymes)] for i in range(0, len(toks), 5)]
        return "\n\n".join("\n".join(lines[i : i + 4]) for i in range(0, len(lines), 4))

    def prose(self, words: int, lang: str, rng: random.Random) -> str:
        stop = sorted(STOPWORDS.get(lang, STOPWORDS["en"]))
        content = _CONTENT.get(lang, _CONTENT["en"])
        out, para, sent = [], [], []
        for i in range(max(words, 5)):
            sent.append(rng.choice(content if i % 3 == 0 else stop))
            if len(sent) >= rng.randint(8, 18):
                s = " ".join(sent)
                para.append(s[0].upper() + s[1:] + ".")
                sent = []
            if len(para) >= rng.randint(3, 6):
                out.append(" ".join(para))
                para = []
        if sent:
            s = " ".join(sent)
            para.append(s[0].upper() + s[1:] + ".")
        if para:
            out.append(" ".join(para))
        return "\n\n".join(out)

    def instance(self, schema: type[BaseModel], hints: dict, lang: str, rng: random.Random) -> dict:
        full = schema.model_json_schema()
        defs = full.get("$defs", {})

        def build(node: dict, field: str, depth: int) -> Any:
            if "$ref" in node:
                return build(defs[node["$ref"].split("/")[-1]], field, depth)
            if "anyOf" in node:
                options = [o for o in node["anyOf"] if o.get("type") != "null"]
                return build(options[0], field, depth) if options else None
            if "enum" in node:
                return node["enum"][0] if field not in hints else hints[field]
            if "const" in node:
                return node["const"]
            t = node.get("type")
            if t == "object":
                props = node.get("properties", {})
                if not props and "additionalProperties" in node:
                    ap = node["additionalProperties"]
                    keys = hints.get(f"{field}.keys", ["a", "b"])
                    return {k: build(ap if isinstance(ap, dict) else {"type": "string"}, k, depth + 1) for k in keys}
                return {k: build(v, k, depth + 1) for k, v in props.items()}
            if t == "array":
                n = hints.get(field, 2 if depth < 4 else 1)
                return [build(node.get("items", {"type": "string"}), f"{field}[]" if field in hints else field, depth + 1)
                        for _ in range(n)]
            if t == "integer":
                return hints.get(field, rng.randint(1, 5))
            if t == "number":
                return hints.get(field, round(rng.uniform(0.5, 1.0), 2))
            if t == "boolean":
                return hints.get(field, False)
            if field in hints and isinstance(hints[field], str):
                return hints[field]
            if field in {"name", "new_name", "title"}:
                return rng.choice(_NAMES.get(lang, _NAMES["en"])) + f" {rng.randint(1, 99)}"
            return self.prose(rng.randint(6, 14), lang, rng).split("\n")[0]

        return build(full, "", 0)

    @staticmethod
    def _follow_variety(content: str, messages: list[dict], rng: random.Random) -> str:
        """Use the variety forms the prompt asks for ('- zoo (not: zo)'), as a compliant writer would."""
        import re

        prompt = json.dumps(messages, ensure_ascii=False).replace("\\n", "\n")
        pairs = re.findall(r"^- (\S+) \(not: ([^)\n]+)\)", prompt, flags=re.MULTILINE)
        if not pairs:
            return content
        for var, std in pairs:
            content = re.sub(rf"(?<!\w){re.escape(std)}(?!\w)", var, content, flags=re.IGNORECASE)
        words = content.split(" ")
        for i in range(0, len(words), 9):
            words[i] = rng.choice(pairs)[0]
        return " ".join(words)

    async def complete(self, *, messages: list[dict], schema: type[BaseModel] | None, hints: dict,
                       extra: dict | None = None) -> dict:
        import asyncio

        extra = extra or {}
        self.calls += 1
        n = self.calls
        if (k := extra.get("fake_rate_limit_every")) and n % int(k) == 0:
            raise FakeRateLimit("Rate limit reached for requests. Please try again in 0.05s.")
        if (k := extra.get("fake_hang_every")) and n % int(k) == 0:
            await asyncio.sleep(3600)
        key = json.dumps(messages, sort_keys=True, ensure_ascii=False)[-4000:] + json.dumps(hints, sort_keys=True)
        rng = self._rng(key)
        if d := extra.get("fake_latency_s"):
            await asyncio.sleep(float(d) * (0.5 + random.random()))
        lang = hints.get("language", "en")
        if schema is None and extra.get("fake_wrong_language") and hints.get("variant", 1) == 1:
            lang = extra["fake_wrong_language"]
        if schema is not None:
            content = json.dumps(self.instance(schema, hints, lang, rng), ensure_ascii=False)
            if (k := extra.get("fake_bad_json_every")) and n % int(k) == 0:
                content = content[: len(content) // 2]
        else:
            ratio = float(extra.get("fake_length_ratio", 1.0))
            content = self.prose(int(int(hints.get("target_words", 300)) * ratio), lang, rng)
            if extra.get("fake_follow_variety"):
                content = self._follow_variety(content, messages, rng)
            if extra.get("fake_follow_form") and "the source is VERSE" in json.dumps(messages, ensure_ascii=False):
                content = self._verse(content)
        prompt_chars = sum(len(json.dumps(m.get("content"), ensure_ascii=False)) for m in messages)
        rt = int(extra.get("fake_reasoning_tokens", 0) or 0)
        return {
            "content": content,
            "finish_reason": "stop",
            **({"reasoning": f"(simulated reasoning, {rt} tokens) Plan the answer, then write it."} if rt else {}),
            "usage": {"prompt_tokens": prompt_chars // 4, "completion_tokens": len(content) // 4 + rt, "cached_tokens": 0,
                      "reasoning_tokens": rt},
        }
