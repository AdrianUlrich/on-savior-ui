"""Social-move graph extraction for analysis.

Two relations are captured:

- **response edges** — ``aInverse`` lists the moves an NPC may answer with
  (``bRandomInverse`` means one is drawn at random).
- **condition chain** — a move plants loot condition tables
  (``LootCTsUs``/``LootCTsThem``, plus ``aLootItms`` entries); those tables
  spawn ``TIs*`` triggers whose ``aReqs``/``aForbids`` reference conditions,
  including personality traits like ``IsHumorless``. ``CTTestUs``/``CTTestThem``
  gate whether the move is available at all. Trait-perception modifiers hang
  off the trait condition's ``aPer`` list.

Nodes and edges export to CSV for clustering / min-cut work elsewhere.
"""

from __future__ import annotations

import csv
from pathlib import Path

from .gamedata import GameData


def response_edges(gd: GameData) -> list[tuple[str, str, str]]:
    """(source move, target move, kind) for every aInverse link."""
    edges = []
    moves = gd.social_moves
    for name, move in moves.items():
        kind = "random_response" if move.get("bRandomInverse") else "response"
        for target in move.get("aInverse", []):
            edges.append((name, target, kind))
    return edges


def trait_requirements(gd: GameData, move: dict) -> dict[str, list[str]]:
    """Conditions required/forbidden for a move via its CT test chains."""
    reqs: list[str] = []
    forbids: list[str] = []
    for key in ("CTTestUs", "CTTestThem"):
        trig = gd.condtrigs.get(move.get(key) or "")
        if trig:
            reqs.extend(trig.get("aReqs", []))
            forbids.extend(trig.get("aForbids", []))
    return {"requires": reqs, "forbids": forbids}


def export_graph(gd: GameData, out_dir: str | Path) -> dict[str, int]:
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    moves = gd.social_moves
    edges = response_edges(gd)

    with open(out / "nodes.csv", "w", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(
            [
                "name", "title", "src", "opener", "random_inverse",
                "ct_test_us", "ct_test_them", "loot_us", "loot_them",
                "requires", "forbids",
            ]
        )
        for name, m in sorted(moves.items()):
            tr = trait_requirements(gd, m)
            w.writerow(
                [
                    name,
                    m.get("strTitle", ""),
                    m.get("_src", ""),
                    int(bool(m.get("bOpener"))),
                    int(bool(m.get("bRandomInverse"))),
                    m.get("CTTestUs") or "",
                    m.get("CTTestThem") or "",
                    m.get("LootCTsUs") or "",
                    m.get("LootCTsThem") or "",
                    ";".join(tr["requires"]),
                    ";".join(tr["forbids"]),
                ]
            )

    with open(out / "edges.csv", "w", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["source", "target", "kind"])
        w.writerows(edges)

    dangling = {t for _, t, _ in edges if t not in moves}
    return {"nodes": len(moves), "edges": len(edges), "dangling_targets": len(dangling)}
