"""Corpus-level instruments: does a corpus of synthetic texts support the same conclusions as
the corpus of originals? Per-text fidelity does not guarantee this (a generator can keep
every text's mean while shrinking the differences between texts), so these are measured
across items, one condition / generator at a time.

  R1 rank_agreement     Spearman rho between phi(T_i) and phi(S_i) across items, per property
  R2 dispersion_ratio   sd of phi(S) / sd of phi(T) across items (homogenisation shows as < 1)
  R3 replicate_analyses declared analyses (group differences, correlations with metadata) run
                        on both corpora; estimates, bootstrap CIs, sign agreement, overlap
  R4 distinguishability pMSE of a classifier separating original from synthetic profiles
                        (Snoke et al. 2018), with its null expectation and grouped CV accuracy
  R5 classifier_transfer train on synthetic, test on real (TSTR; Esteban et al. 2017) against
                        train on real, test on real (TRTR), leave-one-item-out, on chapters
  F1b cosine_delta      Cosine Delta (Evert et al. 2017) over the most
                        frequent words: is each S closest to its own T among all originals?

Everything is deterministic (fixed bootstrap seed); numpy only.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

import numpy as np

from psalm_saga.eval.features import function_words, rel_freq_vector
from psalm_saga.text.metrics import spearman

B = 1000  # bootstrap resamples
SEED = 0


@dataclass
class ItemRecord:
    item: str
    features: dict[str, dict]  # name -> {"source": x, "synthetic": y}
    source_text: str = ""
    synthetic_text: str = ""
    source_chapters: list[dict[str, float]] = field(default_factory=list)  # style profile per chapter
    synthetic_chapters: list[dict[str, float]] = field(default_factory=list)
    exclude: set[str] = field(default_factory=set)
    metadata: dict[str, str] = field(default_factory=dict)


def _pairs(records: list[ItemRecord], feat: str) -> tuple[np.ndarray, np.ndarray, list[ItemRecord]]:
    keep = [r for r in records if (v := r.features.get(feat)) and v.get("source") is not None and v.get("synthetic") is not None]
    return (np.array([float(r.features[feat]["source"]) for r in keep]),
            np.array([float(r.features[feat]["synthetic"]) for r in keep]), keep)


def _ci(samples: list[float]) -> list[float] | None:
    s = [x for x in samples if x is not None and not math.isnan(x)]
    if len(s) < 20:
        return None
    return [round(float(np.percentile(s, 2.5)), 4), round(float(np.percentile(s, 97.5)), 4)]


def _r(x) -> float | None:
    return None if x is None or (isinstance(x, float) and math.isnan(x)) else round(float(x), 4)


def feature_names(records: list[ItemRecord]) -> list[str]:
    names: dict[str, None] = {}
    for r in records:
        for k in r.features:
            names.setdefault(k, None)
    return list(names)


# ------------------------------------------------------------------ R1, R2


def rank_agreement(records: list[ItemRecord], min_items: int = 4) -> dict:
    rng = np.random.default_rng(SEED)
    out = {}
    for f in feature_names(records):
        a, b, _ = _pairs(records, f)
        if len(a) < min_items:
            continue
        rho = spearman(list(a), list(b))
        boots = []
        for _ in range(B):
            idx = rng.integers(0, len(a), len(a))
            boots.append(spearman(list(a[idx]), list(b[idx])))
        out[f] = {"spearman": _r(rho), "ci95": _ci(boots), "items": len(a)}
    return out


def dispersion_ratio(records: list[ItemRecord], min_items: int = 4) -> dict:
    rng = np.random.default_rng(SEED)
    out = {}
    for f in feature_names(records):
        a, b, _ = _pairs(records, f)
        if len(a) < min_items or a.std() == 0:
            continue
        boots = []
        for _ in range(B):
            idx = rng.integers(0, len(a), len(a))
            sa = a[idx].std()
            boots.append(b[idx].std() / sa if sa else None)
        out[f] = {"ratio": _r(b.std() / a.std()), "ci95": _ci(boots), "sd_source": _r(a.std()),
                  "sd_synthetic": _r(b.std()), "items": len(a)}
    return out


# ------------------------------------------------------------------ R3


def _estimate(values: np.ndarray, covariate: list, kind: str, groups: tuple[str, str] | None) -> float | None:
    if kind == "difference":
        g1 = values[[c == groups[0] for c in covariate]]
        g2 = values[[c == groups[1] for c in covariate]]
        if len(g1) < 2 or len(g2) < 2:
            return None
        return float(g2.mean() - g1.mean())
    x = [float(c) for c in covariate]
    return spearman(x, list(values))


def replicate_analyses(records: list[ItemRecord], analyses: list[dict]) -> list[dict]:
    """Each analysis: {feature, by: <metadata column>, groups: [a, b]} (difference of means, b - a)
    or {feature, vs: <numeric metadata column>} (Spearman correlation)."""
    rng = np.random.default_rng(SEED)
    results = []
    for an in analyses:
        feat = an["feature"]
        col = an.get("by") or an.get("vs")
        kind = "difference" if an.get("by") else "correlation"
        a, b, keep = _pairs(records, feat)
        cov, sel = [], []
        for i, r in enumerate(keep):
            v = r.metadata.get(col)
            if v in (None, ""):
                continue
            if kind == "correlation":
                try:
                    v = float(v)
                except ValueError:
                    continue
            cov.append(v)
            sel.append(i)
        a, b = a[sel], b[sel]
        groups = None
        if kind == "difference":
            levels = an.get("groups") or sorted(set(cov))[:2]
            if len(levels) < 2:
                results.append({**an, "error": f"need two levels of {col}"})
                continue
            groups = (str(levels[0]), str(levels[1]))
            cov = [str(c) for c in cov]
        est_t, est_s = _estimate(a, cov, kind, groups), _estimate(b, cov, kind, groups)
        bt, bs, bd = [], [], []
        n = len(a)
        for _ in range(B if n >= 4 else 0):
            idx = rng.integers(0, n, n)
            c = [cov[i] for i in idx]
            et, es = _estimate(a[idx], c, kind, groups), _estimate(b[idx], c, kind, groups)
            if et is not None and es is not None:
                bt.append(et)
                bs.append(es)
                bd.append(es - et)
        ci_t, ci_s, ci_d = _ci(bt), _ci(bs), _ci(bd)
        row = {"analysis": an.get("name") or f"{feat} {'by ' + col if kind == 'difference' else 'vs ' + col}",
               "feature": feat, "kind": kind, "items": n, "groups": list(groups) if groups else None,
               "source": {"estimate": _r(est_t), "ci95": ci_t}, "synthetic": {"estimate": _r(est_s), "ci95": ci_s},
               "difference_ci95": ci_d}
        if est_t is not None and est_s is not None:
            row["sign_agrees"] = bool(np.sign(est_t) == np.sign(est_s))
            row["synthetic_within_source_ci"] = bool(ci_t and ci_t[0] <= est_s <= ci_t[1])
            row["ci_overlap"] = bool(ci_t and ci_s and ci_t[0] <= ci_s[1] and ci_s[0] <= ci_t[1])
            row["replicates"] = row["sign_agrees"] and row["synthetic_within_source_ci"]
        results.append(row)
    return results


# ------------------------------------------------------------------ classifiers (numpy)


def _standardise(train: np.ndarray, test: np.ndarray | None = None):
    mu, sd = train.mean(0), train.std(0)
    sd[sd == 0] = 1.0
    return (train - mu) / sd, None if test is None else (test - mu) / sd


def fit_logistic(X: np.ndarray, y: np.ndarray, l2: float = 1.0, iters: int = 500, lr: float = 0.1) -> np.ndarray:
    """Multinomial logistic regression with L2 penalty, by gradient descent. y: int labels."""
    k = int(y.max()) + 1
    Xb = np.hstack([X, np.ones((len(X), 1))])
    W = np.zeros((Xb.shape[1], k))
    Y = np.eye(k)[y]
    for _ in range(iters):
        Z = Xb @ W
        Z -= Z.max(1, keepdims=True)
        P = np.exp(Z)
        P /= P.sum(1, keepdims=True)
        grad = Xb.T @ (P - Y) / len(X)
        grad[:-1] += l2 * W[:-1] / len(X)
        W -= lr * grad
    return W


def predict_proba(W: np.ndarray, X: np.ndarray) -> np.ndarray:
    Z = np.hstack([X, np.ones((len(X), 1))]) @ W
    Z -= Z.max(1, keepdims=True)
    P = np.exp(Z)
    return P / P.sum(1, keepdims=True)


def _profile_matrix(records: list[ItemRecord]) -> tuple[np.ndarray, np.ndarray, list[str], np.ndarray]:
    feats = [f for f in feature_names(records)
             if all((v := r.features.get(f)) and v.get("source") is not None and v.get("synthetic") is not None for r in records)]
    rows, labels, groups = [], [], []
    for gi, r in enumerate(records):
        for side, lab in (("source", 0), ("synthetic", 1)):
            rows.append([float(r.features[f][side]) for f in feats])
            labels.append(lab)
            groups.append(gi)
    return np.array(rows), np.array(labels), feats, np.array(groups)


def distinguishability(records: list[ItemRecord], folds: int = 5) -> dict:
    """R4. pMSE = mean (p_i - c)^2 of the propensity of being synthetic, c = share synthetic (0.5).

    Under the null that the two sets are draws from one distribution, a logistic model with k
    parameters has E[pMSE] = (k - 1)(1 - c)^2 c / N (Snoke et al. 2018); the ratio to it is
    reported (about 1 = indistinguishable). Grouped cross-validated accuracy (T and S of an item
    always in the same fold) is the more intuitive companion: 0.5 = cannot tell them apart."""
    if len(records) < 4:
        return {"items": len(records)}
    X, y, feats, groups = _profile_matrix(records)
    if not feats:
        return {"items": len(records)}
    Xs, _ = _standardise(X)
    W = fit_logistic(Xs, y)
    p = predict_proba(W, Xs)[:, 1]
    c, N, k = 0.5, len(y), len(feats) + 1
    pmse = float(np.mean((p - c) ** 2))
    null = (k - 1) * (1 - c) ** 2 * c / N
    n_items = len(records)
    order = np.random.default_rng(SEED).permutation(n_items)
    correct = 0
    for f in range(min(folds, n_items)):
        test_items = set(order[f::min(folds, n_items)].tolist())
        te = np.array([g in test_items for g in groups])
        Xtr, Xte = _standardise(X[~te], X[te])
        Wf = fit_logistic(Xtr, y[~te])
        correct += int((predict_proba(Wf, Xte).argmax(1) == y[te]).sum())
    return {"items": n_items, "features": feats, "pmse": _r(pmse), "pmse_null": _r(null),
            "pmse_ratio": _r(pmse / null) if null else None, "cv_accuracy": _r(correct / N)}


def classifier_transfer(records: list[ItemRecord], label: str, min_chapter_items: int = 4) -> dict:
    """R5. Predict a metadata label of the book (period, genre, author gender, ...) from chapter
    profiles. For each held-out item, train on the other items' synthetic chapters (TSTR) or
    their original chapters (TRTR) and test on the held-out item's original chapters."""
    recs = [r for r in records if r.metadata.get(label) not in (None, "") and r.source_chapters and r.synthetic_chapters]
    levels = sorted({r.metadata[label] for r in recs})
    if len(recs) < min_chapter_items or len(levels) < 2:
        return {"label": label, "items": len(recs), "error": "need at least 4 labelled items and 2 classes"}
    feats = sorted(set.intersection(*(set(ch) for r in recs for ch in [*r.source_chapters, *r.synthetic_chapters])))
    lab = {v: i for i, v in enumerate(levels)}

    def mat(chs):
        return np.array([[c[f] for f in feats] for c in chs])

    hits = {"tstr": 0, "trtr": 0}
    n_test = 0
    for i, held in enumerate(recs):
        rest = [r for j, r in enumerate(recs) if j != i]
        Xte = mat(held.source_chapters)
        yte = np.full(len(Xte), lab[held.metadata[label]])
        for key, side in (("tstr", "synthetic_chapters"), ("trtr", "source_chapters")):
            Xtr = np.vstack([mat(getattr(r, side)) for r in rest])
            ytr = np.concatenate([np.full(len(getattr(r, side)), lab[r.metadata[label]]) for r in rest])
            if len(set(ytr.tolist())) < 2:
                continue
            A, Bt = _standardise(Xtr, Xte)
            W = fit_logistic(A, ytr)
            hits[key] += int((predict_proba(W, Bt).argmax(1) == yte).sum())
        n_test += len(yte)
    acc = {k: round(v / n_test, 4) for k, v in hits.items()}
    # Reference: always predicting the most common class (chapter-weighted). Leave-one-out
    # majority voting would be biased against the held-out class, so it is not used.
    counts = np.bincount(np.concatenate([np.full(len(r.source_chapters), lab[r.metadata[label]]) for r in recs]))
    acc["majority"] = round(float(counts.max() / counts.sum()), 4)
    return {"label": label, "classes": levels, "items": len(recs), "test_chapters": n_test,
            "tstr_accuracy": acc["tstr"], "trtr_accuracy": acc["trtr"], "majority_accuracy": acc["majority"],
            "tstr_over_trtr": round(acc["tstr"] / acc["trtr"], 4) if acc["trtr"] else None}


# ------------------------------------------------------------------ F1b


def cosine_delta(records: list[ItemRecord], top: int = 300) -> dict:
    """For each S, rank its own T among all originals by Cosine Delta (1 = nearest).

    z-scores use the mean and sd of the originals, as in authorship attribution; proper names
    are excluded from the vocabulary. With n items, chance top-1 accuracy is 1/n."""
    recs = [r for r in records if r.source_text and r.synthetic_text]
    if len(recs) < 3:
        return {"items": len(recs)}
    exclude = set().union(*(r.exclude for r in recs))
    vocab = function_words([r.source_text for r in recs], exclude, top)
    T = np.array([rel_freq_vector(r.source_text, vocab, exclude) for r in recs])
    S = np.array([rel_freq_vector(r.synthetic_text, vocab, exclude) for r in recs])
    mu, sd = T.mean(0), T.std(0)
    sd[sd == 0] = 1.0
    Zt, Zs = (T - mu) / sd, (S - mu) / sd

    def dist(a, b):
        na, nb = np.linalg.norm(a), np.linalg.norm(b)
        return 1.0 - float(a @ b / (na * nb)) if na and nb else 1.0

    ranks, own, other = [], [], []
    per_item = {}
    for i, r in enumerate(recs):
        d = [dist(Zs[i], Zt[j]) for j in range(len(recs))]
        rank = 1 + sum(x < d[i] for j, x in enumerate(d) if j != i)
        ranks.append(rank)
        own.append(d[i])
        other += [x for j, x in enumerate(d) if j != i]
        per_item[r.item] = {"rank": rank, "delta_own": round(d[i], 4)}
    return {"items": len(recs), "mfw": len(vocab), "top1_accuracy": round(sum(r == 1 for r in ranks) / len(ranks), 4),
            "chance": round(1 / len(recs), 4), "mean_rank": round(float(np.mean(ranks)), 3),
            "mean_delta_own": round(float(np.mean(own)), 4), "mean_delta_other": round(float(np.mean(other)), 4),
            "per_item": per_item}


def property_values(records: list[ItemRecord]) -> dict:
    """Per property, the paired values across books (for plotting the two distributions)."""
    out = {}
    for f in feature_names(records):
        a, b, keep = _pairs(records, f)
        if len(a):
            out[f] = {"items": [r.item for r in keep], "source": [round(float(x), 4) for x in a],
                      "synthetic": [round(float(x), 4) for x in b]}
    return out


def corpus_report(records: list[ItemRecord], analyses: list[dict] | None = None, tstr_label: str | None = None) -> dict:
    out = {"items": len(records), "values": property_values(records), "R1_rank_agreement": rank_agreement(records), "R2_dispersion": dispersion_ratio(records),
           "R4_distinguishability": distinguishability(records), "F1b_cosine_delta": cosine_delta(records)}
    if analyses:
        out["R3_replication"] = replicate_analyses(records, analyses)
    if tstr_label:
        out["R5_classifier_transfer"] = classifier_transfer(records, tstr_label)
    return out
