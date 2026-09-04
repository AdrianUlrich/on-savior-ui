"""Indexing the save library: fast metadata, continuities, and lineage.

Listing saves must never touch the zips — they run to tens of megabytes — so
the index is built from each folder's ``saveInfo.json`` plus file sizes.

Two structures sit on top of the flat list:

- a **continuity**: one playthrough. Its saves share a ``seedId``; a run that
  was continued under a fresh seed (older builds re-seed on save-as) is
  stitched back on by matching character and play time.
- a **lineage**: the parent/child forest inside a continuity. Play time only
  ever grows while you play, so a save's parent is the most recently written
  save whose play time it continues from. Loading an older save and playing
  on therefore shows up as a branch.
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from .gamedata import load_lenient
from .saves import find_saves_dir

_AUTOSAVE_RE = re.compile(r"^autosave_(\d+)_(.*)$")

#: Play-time slack (hours) when deciding whether one save continues another.
PLAYTIME_EPS = 1.0 / 3600

#: How far past a run's end (hours of play time) a differently-seeded save may
#: start and still be treated as the same continuity.
SEED_LINK_WINDOW = 2.0


def _parse_time(info: dict) -> datetime | None:
    epoch = info.get("epochCreationTime")
    if isinstance(epoch, (int, float)) and epoch > 0:
        return datetime.fromtimestamp(epoch / 1000, tz=timezone.utc)
    raw = info.get("realWorldTime")
    if isinstance(raw, str):
        for fmt in ("%Y-%m-%d %H:%M:%S", "%m/%d/%Y %H:%M:%S"):
            try:
                return datetime.strptime(raw, fmt).replace(tzinfo=timezone.utc)
            except ValueError:
                continue
    return None


@dataclass
class SaveRef:
    """One save folder, described from its metadata file alone."""

    folder: Path
    info: dict = field(repr=False)

    # -- identity ---------------------------------------------------------
    @property
    def name(self) -> str:
        return self.folder.name

    @property
    def seed_id(self) -> str:
        return self.info.get("seedId") or ""

    @property
    def created_epoch(self) -> int:
        return int(self.info.get("epochCreationTime") or 0)

    @property
    def key(self) -> str:
        """Stable identifier, unchanged by renaming the folder."""
        if self.seed_id and self.created_epoch:
            return f"{self.seed_id}:{self.created_epoch}"
        return f"name:{self.name}"

    # -- headline metadata ------------------------------------------------
    @property
    def player(self) -> str:
        return self.info.get("playerName") or ""

    @property
    def ship(self) -> str:
        return self.info.get("shipName") or ""

    @property
    def ship_reg(self) -> str:
        return self.info.get("shipRegID") or ""

    @property
    def occupation(self) -> str:
        return self.info.get("formerOccupation") or ""

    @property
    def version(self) -> str:
        return self.info.get("versionLastSave") or self.info.get("version") or ""

    @property
    def money(self) -> float:
        return float(self.info.get("money") or 0.0)

    @property
    def age(self) -> float:
        return float(self.info.get("age") or 0.0)

    @property
    def play_time(self) -> float:
        """Wall-clock hours spent playing, cumulative along the lineage."""
        return float(self.info.get("playTimeElapsed") or 0.0) / 3600

    @property
    def sim_time(self) -> float:
        """In-game hours elapsed since the run started."""
        return float(self.info.get("simTimeElapsed") or 0.0) / 3600

    @property
    def saved_at(self) -> datetime | None:
        return _parse_time(self.info)

    # -- autosaves --------------------------------------------------------
    @property
    def autosave_counter(self) -> int:
        return int(self.info.get("autoSaveCounter") or 0)

    @property
    def is_autosave(self) -> bool:
        return self.autosave_counter > 0 or bool(_AUTOSAVE_RE.match(self.name))

    @property
    def base_name(self) -> str:
        """For ``autosave_31_nuklear``, the manual save it followed: ``nuklear``."""
        m = _AUTOSAVE_RE.match(self.name)
        return m.group(2) if m else self.name

    # -- files ------------------------------------------------------------
    @property
    def zip_path(self) -> Path:
        return self.folder / f"{self.name}.zip"

    def asset(self, kind: str) -> Path | None:
        p = self.folder / f"{kind}.png"
        return p if p.is_file() else None

    @property
    def size_bytes(self) -> int:
        total = 0
        for entry in os.scandir(self.folder):
            if entry.is_file():
                total += entry.stat().st_size
        return total

    def as_dict(self) -> dict:
        saved = self.saved_at
        return {
            "key": self.key,
            "name": self.name,
            "folder": str(self.folder),
            "seed_id": self.seed_id,
            "player": self.player,
            "ship": self.ship,
            "ship_reg": self.ship_reg,
            "occupation": self.occupation,
            "version": self.version,
            "money": self.money,
            "age": self.age,
            "play_time": self.play_time,
            "sim_time": self.sim_time,
            "saved_at": saved.isoformat() if saved else None,
            "created_epoch": self.created_epoch,
            "autosave_counter": self.autosave_counter,
            "is_autosave": self.is_autosave,
            "base_name": self.base_name,
            "size_bytes": self.size_bytes,
            "has_screenshot": self.asset("screenshot") is not None,
            "has_portrait": self.asset("portrait") is not None,
        }


def read_ref(folder: str | os.PathLike) -> SaveRef | None:
    """Build a :class:`SaveRef` from a save folder, or ``None`` if unreadable."""
    folder = Path(folder)
    meta = folder / "saveInfo.json"
    if not meta.is_file():
        return None
    try:
        raw = load_lenient(meta)
    except Exception:
        return None
    info = raw[0] if isinstance(raw, list) and raw else raw
    if not isinstance(info, dict):
        return None
    return SaveRef(folder=folder, info=info)


def scan(saves_dir: str | os.PathLike | None = None) -> list[SaveRef]:
    """Every readable save under the saves folder, newest first."""
    root = find_saves_dir(saves_dir)
    refs = [r for child in sorted(root.iterdir()) if child.is_dir()
            if (r := read_ref(child)) is not None]
    refs.sort(key=lambda r: r.created_epoch, reverse=True)
    return refs


# --------------------------------------------------------------------------
# Continuities and lineage
# --------------------------------------------------------------------------


@dataclass
class Continuity:
    """One playthrough: its saves, in play-time order, and their lineage."""

    id: str
    saves: list[SaveRef]
    seed_ids: list[str]
    parents: dict[str, str | None]

    @property
    def player(self) -> str:
        return self.saves[-1].player if self.saves else ""

    @property
    def ship(self) -> str:
        for ref in reversed(self.saves):
            if ref.ship:
                return ref.ship
        return ""

    @property
    def label(self) -> str:
        parts = [p for p in (self.player, self.ship) if p]
        return " · ".join(parts) or self.id[:8]

    @property
    def latest(self) -> SaveRef | None:
        return max(self.saves, key=lambda r: r.created_epoch, default=None)

    @property
    def size_bytes(self) -> int:
        return sum(r.size_bytes for r in self.saves)

    def children(self) -> dict[str, list[str]]:
        out: dict[str, list[str]] = {r.key: [] for r in self.saves}
        for key, parent in self.parents.items():
            if parent is not None:
                out.setdefault(parent, []).append(key)
        return out

    def as_dict(self) -> dict:
        latest = self.latest
        by_time = sorted(self.saves, key=lambda r: r.play_time)
        return {
            "id": self.id,
            "label": self.label,
            "player": self.player,
            "ship": self.ship,
            "seed_ids": self.seed_ids,
            "save_count": len(self.saves),
            "autosave_count": sum(1 for r in self.saves if r.is_autosave),
            "size_bytes": self.size_bytes,
            "play_time_max": by_time[-1].play_time if by_time else 0.0,
            "money_latest": latest.money if latest else 0.0,
            "version": latest.version if latest else "",
            "latest_key": latest.key if latest else None,
            "latest_saved_at": (
                latest.saved_at.isoformat() if latest and latest.saved_at else None
            ),
            "branch_points": [k for k, kids in self.children().items() if len(kids) > 1],
        }


def _link_parents(refs: list[SaveRef]) -> dict[str, str | None]:
    """Parent of each save: the newest earlier save it could have continued from.

    Saves are considered in write order. A save's parent is the one with the
    greatest play time not exceeding its own — which is the save the player had
    loaded, whether that was the previous save or an older one they went back to.
    """
    ordered = sorted(refs, key=lambda r: (r.created_epoch, r.play_time))
    parents: dict[str, str | None] = {}
    seen: list[SaveRef] = []
    for ref in ordered:
        best: SaveRef | None = None
        for cand in seen:
            if cand.play_time > ref.play_time + PLAYTIME_EPS:
                continue
            if best is None or (cand.play_time, cand.created_epoch) > (
                best.play_time,
                best.created_epoch,
            ):
                best = cand
        parents[ref.key] = best.key if best else None
        seen.append(ref)
    return parents


def _seed_groups(refs: list[SaveRef]) -> list[list[SaveRef]]:
    groups: dict[str, list[SaveRef]] = {}
    for ref in refs:
        groups.setdefault(ref.seed_id or f"name:{ref.name}", []).append(ref)
    return list(groups.values())


def _merge_reseeded(groups: list[list[SaveRef]]) -> list[list[SaveRef]]:
    """Stitch together seed groups that are one run split by a re-seed.

    A later group continues an earlier one when it is the same character in the
    same job, it starts where the earlier one stopped (in play time), and it was
    written after the earlier one finished.
    """
    spans = []
    for g in groups:
        by_play = sorted(g, key=lambda r: r.play_time)
        spans.append(
            {
                "group": g,
                "player": (by_play[0].player, by_play[0].occupation),
                "play_lo": by_play[0].play_time,
                "play_hi": by_play[-1].play_time,
                "written_lo": min(r.created_epoch for r in g),
                "written_hi": max(r.created_epoch for r in g),
            }
        )
    spans.sort(key=lambda s: s["written_lo"])

    parent = list(range(len(spans)))

    def find(i: int) -> int:
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    for i, later in enumerate(spans):
        for j in range(i):
            earlier = spans[j]
            if later["player"] != earlier["player"] or not later["player"][0]:
                continue
            if later["written_lo"] < earlier["written_hi"]:
                continue  # interleaved in time: separate runs, not a re-seed
            if not (
                earlier["play_hi"] - PLAYTIME_EPS
                <= later["play_lo"]
                <= earlier["play_hi"] + SEED_LINK_WINDOW
            ):
                continue
            parent[find(i)] = find(j)

    merged: dict[int, list[SaveRef]] = {}
    for i, span in enumerate(spans):
        merged.setdefault(find(i), []).extend(span["group"])
    return list(merged.values())


def continuities(
    refs: list[SaveRef], *, link_reseeded: bool = True
) -> list[Continuity]:
    """Group saves into playthroughs and compute each one's lineage."""
    groups = _seed_groups(refs)
    if link_reseeded:
        groups = _merge_reseeded(groups)

    out: list[Continuity] = []
    for group in groups:
        oldest = min(group, key=lambda r: r.created_epoch)
        seeds = sorted({r.seed_id for r in group if r.seed_id})
        out.append(
            Continuity(
                id=oldest.seed_id or f"name:{oldest.name}",
                saves=group,
                seed_ids=seeds,
                parents=_link_parents(group),
            )
        )
    out.sort(
        key=lambda c: max((r.created_epoch for r in c.saves), default=0), reverse=True
    )
    return out


@dataclass
class Library:
    """The whole save folder: saves, their continuities, and the lineage links."""

    root: Path
    refs: list[SaveRef]
    groups: list[Continuity]

    @classmethod
    def load(
        cls, saves_dir: str | os.PathLike | None = None, *, link_reseeded: bool = True
    ) -> "Library":
        root = find_saves_dir(saves_dir)
        refs = scan(root)
        return cls(root=root, refs=refs, groups=continuities(refs, link_reseeded=link_reseeded))

    def by_key(self, key: str) -> SaveRef | None:
        return next((r for r in self.refs if r.key == key), None)

    def group_of(self, key: str) -> Continuity | None:
        return next((g for g in self.groups if any(r.key == key for r in g.saves)), None)

    def group_by_id(self, group_id: str) -> Continuity | None:
        return next((g for g in self.groups if g.id == group_id), None)

    def as_dict(self) -> dict:
        membership = {r.key: g.id for g in self.groups for r in g.saves}
        parents = {k: p for g in self.groups for k, p in g.parents.items()}
        saves = []
        for ref in self.refs:
            row = ref.as_dict()
            row["continuity"] = membership.get(ref.key)
            row["parent"] = parents.get(ref.key)
            saves.append(row)
        return {
            "root": str(self.root),
            "saves": saves,
            "continuities": [g.as_dict() for g in self.groups],
        }
