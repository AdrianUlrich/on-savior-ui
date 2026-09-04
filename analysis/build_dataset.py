"""Build the social-move analysis dataset.

Outputs (analysis/out/):
- moves.csv      one row per SOC move: gating traits, need deltas, family
- traits.csv     one row per chargen trait: cost, enables/forbids counts,
                 per-family breakdown, cost-efficiency
- synergy.csv    trait-pair co-enable / conflict counts
- dataset.json   everything + precomputed graph layout, for the web report
"""

from __future__ import annotations

import json
import sys
from collections import Counter, defaultdict
from pathlib import Path

import networkx as nx
import numpy as np
import pandas as pd
from sklearn.cluster import AgglomerativeClustering
from sklearn.preprocessing import normalize

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from on_savior_ui.gamedata import GameData
from on_savior_ui.resolve import Resolver
from on_savior_ui.social import response_edges

OUT = Path(__file__).resolve().parent / "out"
OUT.mkdir(exist_ok=True)

gd = GameData()
rv = Resolver(gd)
moves = {
    n: m for n, m in rv.social_moves.items() if m.src != "interactions_debug.json"
}
costs = rv.trait_costs
meta = rv.trait_meta

# ---------------------------------------------------------------- families
AXES = sorted({ax for m in moves.values() for ax in (*m.needs_us, *m.needs_them)})
active = {n: m for n, m in moves.items() if m.needs_us or m.needs_them}


def vec(m):
    return np.array(
        [m.needs_us.get(a, 0.0) for a in AXES] + [m.needs_them.get(a, 0.0) for a in AXES]
    )


names = sorted(active)
X = np.vstack([vec(active[n]) for n in names])
Xn = normalize(X)
N_FAMILIES = 10
labels = AgglomerativeClustering(n_clusters=N_FAMILIES, metric="cosine", linkage="average").fit_predict(Xn)

# name each family after its dominant axes (side-aware)
fam_names = {}
cols = [f"us:{a}" for a in AXES] + [f"them:{a}" for a in AXES]
for k in range(N_FAMILIES):
    centroid = Xn[labels == k].mean(axis=0)
    top = np.argsort(-np.abs(centroid))[:2]
    parts = []
    for i in top:
        if abs(centroid[i]) < 0.05:
            continue
        sign = "+" if centroid[i] > 0 else "-"
        parts.append(f"{cols[i]}{sign}")
    fam_names[k] = " ".join(parts) or f"family{k}"

family_of = {n: int(k) for n, k in zip(names, labels)}
fam_names[-1] = "no-effect"


def valence_them(m):
    """Net effect on the target's needs; negative = good for them (prosocial)."""
    return round(sum(m.needs_them.values()), 2)


def valence_us(m):
    return round(sum(m.needs_us.values()), 2)

# ---------------------------------------------------------------- moves.csv
rows = []
for n, m in sorted(moves.items()):
    rows.append(
        {
            "move": n,
            "title": m.title,
            "src": m.src,
            "opener": m.opener,
            "gate_chance": m.gate_chance,
            "gate_and": m.gate_and,
            "enabled_by": ";".join(m.enabled_by),
            "forbidden_by": ";".join(m.forbidden_by),
            "family": family_of.get(n, -1),
            "family_name": fam_names[family_of.get(n, -1)],
            "valence_them": valence_them(m),
            "valence_us": valence_us(m),
            "needs_us": json.dumps(m.needs_us),
            "needs_them": json.dumps(m.needs_them),
            "rel_them_sees_us": m.rel_them_sees_us or "",
        }
    )
moves_df = pd.DataFrame(rows)
moves_df.to_csv(OUT / "moves.csv", index=False)

# ---------------------------------------------------------------- traits.csv
enables = defaultdict(list)
forbids = defaultdict(list)
for n, m in moves.items():
    for t in m.enabled_by:
        enables[t].append(n)
    for t in m.forbidden_by:
        forbids[t].append(n)

exclusive = defaultdict(list)
for n, m in moves.items():
    if len(m.enabled_by) == 1:
        exclusive[m.enabled_by[0]].append(n)

trows = []
for t, cost in sorted(costs.items()):
    fam_counts = Counter(family_of.get(n, -1) for n in enables[t])
    mean_valence = (
        round(np.mean([valence_them(moves[n]) for n in enables[t]]), 2)
        if enables[t]
        else 0.0
    )
    trows.append(
        {
            "trait": t,
            "friendly": meta[t]["friendly"],
            "cost_years": cost,
            "n_enables": len(enables[t]),
            "n_exclusive": len(exclusive[t]),
            "n_forbids": len(forbids[t]),
            "net": len(enables[t]) - len(forbids[t]),
            "share": round(sum(1 / len(moves[n].enabled_by) for n in enables[t]), 1),
            "mean_valence_them": mean_valence,
            "anti": meta[t]["anti"],
            "families_enabled": ";".join(
                f"{fam_names[k]}:{v}" for k, v in fam_counts.most_common()
            ),
        }
    )
traits_df = pd.DataFrame(trows).sort_values("net", ascending=False)
traits_df.to_csv(OUT / "traits.csv", index=False)

# ---------------------------------------------------------------- synergy
pair_co = Counter()
pair_conflict = Counter()
for n, m in moves.items():
    for a in m.enabled_by:
        for b in m.enabled_by:
            if a < b:
                pair_co[(a, b)] += 1
        for b in m.forbidden_by:
            pair_conflict[tuple(sorted((a, b)))] += 1
srows = [
    {"a": a, "b": b, "co_enable": c, "conflict": pair_conflict.get((a, b), 0)}
    for (a, b), c in pair_co.most_common()
]
for (a, b), c in pair_conflict.items():
    if (a, b) not in pair_co:
        srows.append({"a": a, "b": b, "co_enable": 0, "conflict": c})
pd.DataFrame(srows).to_csv(OUT / "synergy.csv", index=False)

# trait communities from co-enable graph
TG = nx.Graph()
for r in srows:
    if r["co_enable"] >= 2:
        TG.add_edge(r["a"], r["b"], weight=r["co_enable"])
communities = list(nx.community.greedy_modularity_communities(TG, weight="weight"))
trait_community = {}
for i, com in enumerate(communities):
    for t in com:
        trait_community[t] = i

# ---------------------------------------------------------------- graph layout
edges = [(s, t) for s, t, _ in response_edges(gd) if t in moves and s in moves]
G = nx.Graph()
G.add_nodes_from(moves)
G.add_edges_from(edges)
connected = [n for n in G if G.degree(n) > 0]
isolated = sorted(n for n in G if G.degree(n) == 0)
sub = G.subgraph(connected)
pos = nx.forceatlas2_layout(
    sub, max_iter=400, scaling_ratio=4.0, strong_gravity=True, gravity=0.6, seed=42
)
xs = [p[0] for p in pos.values()]
ys = [p[1] for p in pos.values()]
sx, sy = max(xs) - min(xs) or 1, max(ys) - min(ys) or 1
pos = {
    n: ((p[0] - min(xs)) / sx * 2 - 1, (p[1] - min(ys)) / sy * 1.7 - 1)
    for n, p in pos.items()
}
# isolated moves: compact grid strip below the layout
per_row = 40
for i, n in enumerate(isolated):
    row, col = divmod(i, per_row)
    pos[n] = (col / (per_row - 1) * 2 - 1, 0.82 + row * 0.055)

dataset = {
    "axes": AXES,
    "families": {str(k): v for k, v in fam_names.items()},
    "traits": {
        t: {
            **meta[t],
            "enables": sorted(enables[t]),
            "forbids": sorted(forbids[t]),
            "community": trait_community.get(t, -1),
        }
        for t in costs
    },
    "moves": {
        n: {
            "title": m.title,
            "opener": m.opener,
            "gate_chance": m.gate_chance,
            "valence_them": valence_them(m),
            "valence_us": valence_us(m),
            "family": family_of.get(n, -1),
            "enabled_by": m.enabled_by,
            "forbidden_by": m.forbidden_by,
            "needs_us": m.needs_us,
            "needs_them": m.needs_them,
            "rel": m.rel_them_sees_us,
            "x": round(float(pos[n][0]), 4),
            "y": round(float(pos[n][1]), 4),
        }
        for n, m in moves.items()
    },
    "edges": edges,
    "trait_communities": [sorted(c) for c in communities],
}
(OUT / "dataset.json").write_text(json.dumps(dataset))

n_and = sum(
    1
    for m in moves.values()
    if m.gate_and and len(m.enabled_by) > 1
)
print(f"moves with AND multi-trait gates: {n_and}")
print(f"moves: {len(moves)} ({len(active)} with effects), axes: {AXES}")
print(f"families: {fam_names}")
print(f"trait communities: {[sorted(c)[:6] for c in communities]}")
print(traits_df.head(15).to_string(index=False))
print("---- bottom ----")
print(traits_df.tail(10).to_string(index=False))
