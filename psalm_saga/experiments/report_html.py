"""Self-contained HTML report of the corpus-level comparison (no external assets).

For every property: the distribution across books on the originals and on the synthetic
texts, as two strip plots with each book's pair joined by a line, plus the rank agreement
(R1) and dispersion ratio (R2) that summarise the picture. Colours follow the web app.
"""

from __future__ import annotations

import html
import math

GRADE = {"r1": (0.8, 0.6), "r2": (0.8, 0.6)}  # green >= first, orange >= second (R2: distance of ratio from 1)


def _cls(kind: str, v: float | None) -> str:
    if v is None:
        return ""
    g, o = GRADE[kind]
    if kind == "r2":
        v = 1 - abs(1 - v)
    return "good" if v >= g else "warn" if v >= o else "bad"


def _strip(vals: dict) -> str:
    a, b, items = vals["source"], vals["synthetic"], vals["items"]
    lo, hi = min(a + b), max(a + b)
    if hi == lo:
        hi = lo + 1
    W, H, L = 520, 74, 70
    x = lambda v: L + (W - L - 10) * (v - lo) / (hi - lo)  # noqa: E731
    out = [f'<svg viewBox="0 0 {W} {H}" class="strip">',
           '<text x="4" y="22" class="lab">originals</text><text x="4" y="56" class="lab">synthetic</text>']
    for v1, v2, it in zip(a, b, items, strict=True):
        t = html.escape(f"{it}: {v1:g} → {v2:g}")
        out.append(f'<line x1="{x(v1):.1f}" y1="22" x2="{x(v2):.1f}" y2="52" class="pair"><title>{t}</title></line>')
        out.append(f'<circle cx="{x(v1):.1f}" cy="18" r="4" class="src"><title>{t}</title></circle>')
        out.append(f'<circle cx="{x(v2):.1f}" cy="56" r="4" class="syn"><title>{t}</title></circle>')
    out.append(f'<text x="{L}" y="{H - 2}" class="tick">{lo:.3g}</text><text x="{W - 10}" y="{H - 2}" class="tick" text-anchor="end">{hi:.3g}</text></svg>')
    return "".join(out)


def _sd(v: list[float]) -> float:
    m = sum(v) / len(v)
    return math.sqrt(sum((x - m) ** 2 for x in v) / len(v))


def render(name: str, corpus: dict) -> str:
    parts = [f"""<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>{html.escape(name)} — corpus comparison</title><style>
:root{{--bg:#f6f4ef;--panel:#fffdf8;--ink:#1d2329;--muted:#6b7177;--line:#ddd8cc;--accent:#1f4e79;--ok:#2f7d4f;--warn:#b7791f;--bad:#b42318}}
@media (prefers-color-scheme:dark){{:root{{--bg:#12161c;--panel:#1a2029;--ink:#e6e9ee;--muted:#9aa3ad;--line:#2c3440;--accent:#7fb0e0;--ok:#5fbf86;--warn:#e2b04a;--bad:#f07a6f}}}}
body{{background:var(--bg);color:var(--ink);font:14px/1.5 Inter,system-ui,sans-serif;margin:0;padding:24px 16px;max-width:1100px;margin:auto}}
h1{{font:600 22px Georgia,serif}} h2{{font:600 17px Georgia,serif;margin:28px 0 6px}}
.card{{background:var(--panel);border:1px solid var(--line);border-radius:10px;padding:12px 16px;margin-bottom:10px}}
.grid{{display:grid;grid-template-columns:repeat(auto-fill,minmax(480px,1fr));gap:10px}}
.strip{{width:100%;height:auto}} .lab,.tick{{font-size:10px;fill:var(--muted)}}
.src{{fill:var(--muted);opacity:.75}} .syn{{fill:var(--accent)}} .pair{{stroke:var(--line);stroke-width:1}}
.good{{color:var(--ok)}} .warn{{color:var(--warn)}} .bad{{color:var(--bad)}} .muted{{color:var(--muted)}}
.stats{{font-size:12.5px}} i.k{{display:inline-block;width:9px;height:9px;border-radius:50%;margin:0 4px 0 10px}}
</style></head><body><h1>{html.escape(name)}: do the synthetic texts have the same distributions as the originals?</h1>
<div class="card">Each panel shows one property across all books: grey dots are the originals, blue dots the synthetic
texts, and a line joins each book to its synthetic counterpart. If the synthetic corpus can stand in for the originals,
the two rows have the same spread and the lines do not cross much.
<br><b>R1 rank agreement</b> (Spearman ρ): are the books ordered the same way? <span class="good">≥ 0.8</span> ·
<span class="warn">≥ 0.6</span> · <span class="bad">below</span>.
<b>R2 dispersion ratio</b>: spread of the synthetic values ÷ spread of the originals; 1 = same spread, below 1 = the
synthetic texts are more alike than the books they replace. <span class="good">within 0.2 of 1</span> ·
<span class="warn">within 0.4</span> · <span class="bad">further</span>. Thresholds are provisional. “–” means not computable: all books have the same value, so there is no order or
spread to compare. Hover a dot for the book and both values.</div>"""]
    for group, c in corpus.items():
        parts.append(f"<h2>{html.escape(group)} <span class='muted'>· {c.get('items', 0)} books</span></h2>")
        vals = c.get("values") or {}
        if not vals:
            parts.append("<p class='muted'>No finished runs with a source text.</p>")
            continue
        r1s, r2s = c.get("R1_rank_agreement") or {}, c.get("R2_dispersion") or {}
        parts.append("<div class='grid'>")
        for f, v in vals.items():
            if len(v["source"]) < 2:
                continue
            r1, r2 = (r1s.get(f) or {}).get("spearman"), (r2s.get(f) or {}).get("ratio")
            ci = (r1s.get(f) or {}).get("ci95")
            parts.append(
                f"<div class='card'><b>{html.escape(f.replace('_', ' '))}</b>{_strip(v)}<div class='stats'>"
                f"R1 ρ <span class='{_cls('r1', r1)}'>{'–' if r1 is None else f'{r1:.2f}'}</span>"
                f"{'' if not ci else f' <span class=muted>[{ci[0]:.2f}, {ci[1]:.2f}]</span>'} · "
                f"R2 <span class='{_cls('r2', r2)}'>{'–' if r2 is None else f'{r2:.2f}'}</span> · "
                f"sd {_sd(v['source']):.3g} → {_sd(v['synthetic']):.3g}</div></div>")
        parts.append("</div>")
        d, r4 = c.get("F1b_cosine_delta") or {}, c.get("R4_distinguishability") or {}
        if d.get("top1_accuracy") is not None or r4.get("cv_accuracy") is not None:
            parts.append(
                "<div class='card stats'>"
                f"<b>Own-source attribution (F1b)</b>: {d.get('top1_accuracy', '–')} of synthetic texts are stylistically "
                f"closest to their own original (chance {d.get('chance', '–')}). "
                f"<b>Distinguishability (R4)</b>: a classifier tells originals from synthetic texts with accuracy "
                f"{r4.get('cv_accuracy', '–')} (0.5 = cannot tell them apart); pMSE ratio {r4.get('pmse_ratio', '–')} "
                "(about 1 = indistinguishable).</div>")
    parts.append("</body></html>")
    return "\n".join(parts)
