"""Shared compact payload for the report and planner pages.

Reads out/dataset.json and produces the index-based JSON blob both HTML
templates embed at their `/*__DATA__*/null` placeholder.
"""

from __future__ import annotations

import json
from collections import Counter
from pathlib import Path

HERE = Path(__file__).resolve().parent

# family id -> display slot (by size, colors follow the documented palette order)
FAMILY_DISPLAY = [
    (2, "Opening Up", "Sharing worries, family, memories — satisfies your Intimacy at the price of your Privacy."),
    (0, "Put-Downs & Bragging", "Insults, dismissals, bragging — inflates the target's Esteem and Self-Respect needs."),
    (3, "Kindness & Reassurance", "Comfort, encouragement, favors — feeds your Altruism and makes the target feel safer."),
    (1, "Dark Bonding & Wit", "Dark jokes, commiseration, gossip — feeds your own Esteem and Meaning."),
    (7, "Brush-Offs", "Telling people to get lost — reclaims your Privacy at the target's expense."),
]
COLORS = ["#3987e5", "#d95926", "#199e70", "#c98500", "#d55181"]
OTHER_COLOR = "#8a94a6"
NOEFF_COLOR = "#43505c"


def build_payload() -> dict:
    ds = json.loads((HERE / "out" / "dataset.json").read_text())
    fam_slot = {fid: i for i, (fid, _, _) in enumerate(FAMILY_DISPLAY)}

    def slot_of(fam: int) -> int:
        if fam == -1:
            return len(FAMILY_DISPLAY) + 1  # no-effect
        return fam_slot.get(fam, len(FAMILY_DISPLAY))  # other

    moves_names = sorted(ds["moves"])
    midx = {n: i for i, n in enumerate(moves_names)}
    traits_names = sorted(ds["traits"], key=lambda t: ds["traits"][t]["friendly"])
    tidx = {t: i for i, t in enumerate(traits_names)}

    slot_counts = Counter(slot_of(ds["moves"][n]["family"]) for n in moves_names)
    sig: dict[int, Counter] = {}
    for n in moves_names:
        m = ds["moves"][n]
        c = sig.setdefault(slot_of(m["family"]), Counter())
        for a, v in m["needs_us"].items():
            c["us:" + a] += v
        for a, v in m["needs_them"].items():
            c["them:" + a] += v

    fams_out = []
    for i, (fid, label, blurb) in enumerate(FAMILY_DISPLAY):
        n = slot_counts[i]
        top = [
            {"axis": a, "mean": round(v / n, 1)}
            for a, v in sorted(sig[i].items(), key=lambda kv: -abs(kv[1]))[:4]
            if abs(v / n) >= 1
        ]
        fams_out.append({"label": label, "blurb": blurb, "color": COLORS[i], "n": n, "sig": top})
    fams_out.append(
        {
            "label": "Minor Families",
            "blurb": "Complaints, begging, bribe dances, badmouthing rituals, quiet gestures — five small clusters.",
            "color": OTHER_COLOR,
            "n": slot_counts[len(FAMILY_DISPLAY)],
            "sig": [],
        }
    )
    fams_out.append(
        {
            "label": "Flavor & Plumbing",
            "blurb": "Origin chatter, plot beats, UI steps — moves with no need-axis effects.",
            "color": NOEFF_COLOR,
            "n": slot_counts[len(FAMILY_DISPLAY) + 1],
            "sig": [],
        }
    )

    moves_out = []
    for n in moves_names:
        m = ds["moves"][n]
        moves_out.append(
            {
                "id": n,
                "t": m["title"],
                "ch": m.get("gate_chance"),
                "f": slot_of(m["family"]),
                "vt": m["valence_them"],
                "vu": m["valence_us"],
                "x": m["x"],
                "y": m["y"],
                "op": 1 if m["opener"] else 0,
                "eb": [tidx[t] for t in m["enabled_by"]],
                "fb": [tidx[t] for t in m["forbidden_by"]],
                "nu": m["needs_us"],
                "nt": m["needs_them"],
                "rel": m["rel"] or "",
            }
        )

    traits_out = []
    for t in traits_names:
        d = ds["traits"][t]
        en = [midx[m] for m in d["enables"] if m in midx]
        fb = [midx[m] for m in d["forbids"] if m in midx]
        vals = [moves_out[i]["vt"] for i in en]
        traits_out.append(
            {
                "id": t,
                "n": d["friendly"],
                "c": d["cost"],
                "anti": d["anti"],
                "desc": d["desc"],
                "en": en,
                "fb": fb,
                "mv": round(sum(vals) / len(vals), 1) if vals else 0.0,
            }
        )

    edges_out = [
        [midx[s], midx[t]] for s, t in ds["edges"] if s in midx and t in midx
    ]

    # subset / near-subset relations between traits' enable sets
    subsets = []
    esets = {t["id"]: set(t["en"]) for t in traits_out}
    names = {t["id"]: t["n"] for t in traits_out}
    for a, ea in esets.items():
        if not ea:
            continue
        for b, eb in esets.items():
            if a == b or len(ea) > len(eb) or (len(ea) == len(eb) and a > b):
                continue
            inter = len(ea & eb)
            frac = inter / len(ea)
            if frac >= 0.8:
                subsets.append(
                    {
                        "sub": names[a], "sup": names[b],
                        "n_sub": len(ea), "n_sup": len(eb),
                        "covered": inter, "strict": frac == 1.0,
                    }
                )
    subsets.sort(key=lambda s: (-s["strict"], -s["covered"] / s["n_sub"], -s["n_sub"]))

    return {
        "fams": fams_out,
        "moves": moves_out,
        "traits": traits_out,
        "edges": edges_out,
        "subsets": subsets,
        "build": "Early Access Build 0.14.5.17",
    }


def inject(template_name: str, out_name: str, script_name: str | None = None) -> Path:
    payload = build_payload()
    template = (HERE / template_name).read_text()
    html = template.replace("/*__DATA__*/null", json.dumps(payload, separators=(",", ":")))
    if script_name:
        html = html.replace("/*__SCRIPT__*/", (HERE / script_name).read_text())
    out = HERE / "out" / out_name
    out.write_text(html)
    return out
