"""Reading Ostranauts save games.

A save is a folder under .../Blue Bottle Games/Ostranauts/Saves/<name>/
containing saveInfo.json, portrait.png, screenshot.png and <name>.zip.
The zip holds:

- ``<player name>.json`` — world state: financial ledger (aLIs), objectives,
  jobs, plots, market snapshot, and the player ship's loose objects (aCOs).
- ``ships/*.json``     — one file per ship/station; people are condition
  owners inside a ship's ``aCOs`` (marked by the ``IsHuman`` condition).
- ``saveInfo.json``, ``portrait.png``, ``screenshot.png`` — duplicated
  from the folder.

Conditions on a person are strings ``Name=<duration>x<magnitude>``.
"""

from __future__ import annotations

import glob
import os
import zipfile
from dataclasses import dataclass, field
from functools import cached_property
from pathlib import Path

from .gamedata import load_lenient

_SAVES_GLOBS = [
    "/mnt/*/Users/*/AppData/LocalLow/Blue Bottle Games/Ostranauts/Saves",
    str(
        Path.home()
        / ".config/unity3d/Blue Bottle Games/Ostranauts/Saves"
    ),
]


def find_saves_dir(explicit: str | os.PathLike | None = None) -> Path:
    candidates: list[str] = []
    if explicit:
        candidates.append(str(explicit))
    if env := os.environ.get("ON_SAVIOR_SAVES_DIR"):
        candidates.append(env)
    for pattern in _SAVES_GLOBS:
        candidates.extend(sorted(glob.glob(pattern)))
    for cand in candidates:
        p = Path(cand)
        if p.is_dir():
            return p
    raise FileNotFoundError(
        "Ostranauts saves not found; set ON_SAVIOR_SAVES_DIR to the Saves folder"
    )


@dataclass
class Condition:
    name: str
    duration: float
    magnitude: float

    @classmethod
    def parse(cls, raw: str) -> "Condition":
        name, _, rest = raw.partition("=")
        dur, _, mag = rest.partition("x")
        try:
            return cls(name, float(dur or 1.0), float(mag or 1.0))
        except ValueError:
            return cls(name, 1.0, 1.0)


@dataclass
class Person:
    ship: str
    record: dict = field(repr=False)

    @property
    def id(self) -> str:
        return self.record.get("strID") or self.record.get("strName", "?")

    @property
    def name(self) -> str:
        return self.record.get("strFriendlyName") or self.id

    @cached_property
    def conditions(self) -> dict[str, Condition]:
        out: dict[str, Condition] = {}
        for raw in self.record.get("aConds", []):
            c = Condition.parse(str(raw))
            out[c.name] = c
        return out

    def prefixed(self, *prefixes: str) -> dict[str, float]:
        return {
            n: c.magnitude
            for n, c in self.conditions.items()
            if n.startswith(prefixes)
        }

    @property
    def skills(self) -> dict[str, float]:
        return self.prefixed("Skill")

    @property
    def stats(self) -> dict[str, float]:
        return self.prefixed("Stat")


class Save:
    def __init__(self, folder: str | os.PathLike):
        self.folder = Path(folder)
        self.name = self.folder.name

    @cached_property
    def info(self) -> dict:
        raw = load_lenient(self.folder / "saveInfo.json")
        return raw[0] if isinstance(raw, list) else raw

    @cached_property
    def _zip(self) -> zipfile.ZipFile:
        return zipfile.ZipFile(self.folder / f"{self.name}.zip")

    def _load_member(self, member: str) -> object:
        with self._zip.open(member) as fh:
            return load_lenient(fh.read().decode("utf-8-sig"))

    @cached_property
    def world(self) -> dict:
        """The player world file (<player name>.json)."""
        member = next(
            m for m in self._zip.namelist()
            if "/" not in m and m.endswith(".json") and m != "saveInfo.json"
        )
        raw = self._load_member(member)
        return raw[0] if isinstance(raw, list) else raw

    @property
    def ship_ids(self) -> list[str]:
        return sorted(
            m.removeprefix("ships/").removesuffix(".json")
            for m in self._zip.namelist()
            if m.startswith("ships/") and m.endswith(".json")
        )

    def ship(self, ship_id: str) -> dict:
        raw = self._load_member(f"ships/{ship_id}.json")
        return raw[0] if isinstance(raw, list) else raw

    def people(self, ship_id: str | None = None) -> list[Person]:
        """People (condition owners with IsHuman) across ships."""
        ids = [ship_id] if ship_id else self.ship_ids
        found: list[Person] = []
        for sid in ids:
            for co in self.ship(sid).get("aCOs", []):
                if not isinstance(co, dict):
                    continue
                conds = co.get("aConds", [])
                if any(str(c).startswith(("IsHuman=", "IsIntelligentBeing=")) for c in conds):
                    found.append(Person(ship=sid, record=co))
        return found

    @cached_property
    def player(self) -> Person | None:
        target = self.world.get("strPlayerCO")
        for person in self.people():
            if person.id == target or person.name == target:
                return person
        return None

    @property
    def ledger(self) -> list[dict]:
        return self.world.get("aLIs", [])

    def ledger_totals(self) -> dict:
        """Split the ledger into money in and money out.

        Amounts are always positive; the direction is in ``strPayor`` /
        ``strPayee``, matched against the player's name. ``bPaid`` is left
        alone — it reads false on every entry in observed saves, including
        ones that carry a ``fTimePaid``, so it says nothing about settlement.
        """
        who = self.info.get("playerName")
        income = expense = 0.0
        for entry in self.ledger:
            amount = abs(float(entry.get("fAmount") or 0.0))
            if entry.get("strPayor") == who:
                expense += amount
            elif entry.get("strPayee") == who:
                income += amount
        return {"income": income, "expense": expense}

    def metrics(self) -> dict:
        info = self.info
        ledger = self.ledger
        totals = self.ledger_totals()
        income, expense = totals["income"], totals["expense"]
        objectives = self.world.get("aObjectives", [])
        return {
            "save": self.name,
            "player": info.get("playerName"),
            "ship": info.get("shipName"),
            "version": info.get("version"),
            "money": info.get("money"),
            "age": info.get("age"),
            "play_time_h": (info.get("playTimeElapsed") or 0) / 3600,
            "sim_time_h": (info.get("simTimeElapsed") or 0) / 3600,
            "saved_at": info.get("realWorldTime"),
            "ledger_entries": len(ledger),
            "ledger_income": income,
            "ledger_expense": expense,
            "objectives_done": sum(1 for o in objectives if o.get("bFinished")),
            "objectives_total": len(objectives),
            "jobs": len(self.world.get("aJobs", [])),
            "plots": {
                p.get("strPlotName"): p.get("strCurrentBeat")
                for p in self.world.get("aPlots", [])
            },
        }


def list_saves(explicit: str | os.PathLike | None = None) -> list[Save]:
    root = find_saves_dir(explicit)
    saves = []
    for child in sorted(root.iterdir()):
        if (child / "saveInfo.json").is_file():
            saves.append(Save(child))
    return saves
