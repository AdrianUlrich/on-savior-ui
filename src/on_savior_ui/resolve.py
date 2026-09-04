"""Resolve social-move mechanics: trait gating and need-axis effects.

Chain: a move's ``CTTestUs`` names a condtrig whose ``aReqs`` (usually
``bAND: false`` = ANY-of) and ``aForbids`` reference personality traits;
its ``LootCTsUs``/``LootCTsThem`` name loot tables (``strType: trigger``)
whose entries ``TUpX=<dur>x<mag>`` / ``TDnX=...`` are condtrigs with
``strCondName: Stat<Axis>`` and ``fCount`` ±1 — i.e. a need-axis delta of
``fCount * mag * fChance``. Temporary trait variants (``IsBraveTemp``)
are folded into their base trait.

Chargen point costs come from ``traitscores.json`` rows ``name,cost,flag``;
``flag == 1`` marks real chargen traits (homeworld markers are 0).
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field
from functools import cached_property

from .gamedata import GameData


def base_trait(name: str) -> str:
    return name.removesuffix("Temp")


@dataclass
class MoveMechanics:
    name: str
    title: str
    src: str
    opener: bool
    enabled_by: list[str]      # chargen traits, ANY-of unless gate_and
    forbidden_by: list[str]    # chargen traits, any blocks
    gate_and: bool
    gate_chance: float | None
    needs_us: dict[str, float] = field(default_factory=dict)
    needs_them: dict[str, float] = field(default_factory=dict)
    markers: list[str] = field(default_factory=list)
    rel_them_sees_us: str | None = None
    rel_us_sees_them: str | None = None


class Resolver:
    def __init__(self, gd: GameData | None = None):
        self.gd = gd or GameData()

    @cached_property
    def trait_costs(self) -> dict[str, int]:
        rows = self.gd.table("traitscores")[0]["aValues"]
        out = {}
        for row in rows:
            name, cost, flag = row.split(",")
            if flag.strip() == "1":
                out[name.strip()] = int(cost)
        return out

    @cached_property
    def trait_meta(self) -> dict[str, dict]:
        conds = self.gd.conditions
        meta = {}
        for trait, cost in self.trait_costs.items():
            c = conds.get(trait, {})
            meta[trait] = {
                "cost": cost,
                "friendly": c.get("strNameFriendly", trait),
                "desc": c.get("strDesc", ""),
                "color": c.get("strColor", ""),
                "anti": c.get("strAnti", ""),
            }
        return meta

    def _gate(self, test_name: str | None):
        trig = self.gd.condtrigs.get(test_name or "")
        if not trig:
            return [], [], True, None
        traits = self.trait_costs
        reqs = sorted({base_trait(r) for r in trig.get("aReqs", [])} & traits.keys())
        forb = sorted({base_trait(r) for r in trig.get("aForbids", [])} & traits.keys())
        return reqs, forb, bool(trig.get("bAND", True)), trig.get("fChance")

    def _needs(self, ct_name: str | None, mult: float = 1.0, depth: int = 0):
        """Recursively resolve a loot table into need deltas + markers."""
        vec: Counter[str] = Counter()
        markers: list[str] = []
        table = self.gd.loot.get(ct_name or "")
        if not table or depth > 4:
            return vec, markers
        for entry in table.get("aCOs", []):
            name, _, rest = str(entry).partition("=")
            _, _, mag_s = rest.partition("x")
            try:
                mag = float(mag_s or 1.0)
            except ValueError:
                mag = 1.0
            trig = self.gd.condtrigs.get(name)
            cond_target = (trig or {}).get("strCondName") or ""
            if trig and cond_target.startswith("Stat") and name.startswith(("TUp", "TDn")):
                delta = trig.get("fCount", 1.0) * mag * trig.get("fChance", 1.0) * mult
                vec[cond_target.removeprefix("Stat")] += delta
            else:
                markers.append(name)
        for sub in table.get("aLoots", []):
            sub_name, _, rest = str(sub).partition("=")
            chance_s, _, count_s = rest.partition("x")
            try:
                m = float(chance_s or 1.0) * float(count_s or 1.0)
            except ValueError:
                m = 1.0
            v, mk = self._needs(sub_name, mult * m, depth + 1)
            vec.update(v)
            markers.extend(mk)
        return vec, markers

    def move(self, m: dict) -> MoveMechanics:
        reqs, forb, b_and, chance = self._gate(m.get("CTTestUs"))
        needs_us, mk_us = self._needs(m.get("LootCTsUs"))
        needs_them, mk_them = self._needs(m.get("LootCTsThem"))
        return MoveMechanics(
            name=m["strName"],
            title=m.get("strTitle") or m["strName"],
            src=m.get("_src", ""),
            opener=bool(m.get("bOpener")),
            enabled_by=reqs,
            forbidden_by=forb,
            gate_and=b_and,
            gate_chance=chance,
            needs_us={k: round(v, 3) for k, v in needs_us.items() if v},
            needs_them={k: round(v, 3) for k, v in needs_them.items() if v},
            markers=sorted(set(mk_us + mk_them)),
            rel_them_sees_us=m.get("strLootRELChangeThemSeesUs"),
            rel_us_sees_them=m.get("strLootRELChangeUsSeesThem"),
        )

    @cached_property
    def social_moves(self) -> dict[str, MoveMechanics]:
        return {
            name: self.move(m) for name, m in self.gd.social_moves.items()
        }
