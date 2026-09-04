"""Sidecar metadata: tags, notes, stars, and retention policies.

The game's own files are never written to by this module — everything the user
adds lives in a separate store, keyed by a save's stable ``key``
(``<seedId>:<epochCreationTime>``), which survives renaming the folder.

:class:`MetadataStore` is the seam to swap the JSON file for a database. It
deals only in plain dicts and small value objects, so a Postgres-backed
implementation needs two tables and the same nine methods — see
``docs/saves-ui.md``.
"""

from __future__ import annotations

import json
import os
import tempfile
from dataclasses import asdict, dataclass, field, replace
from pathlib import Path
from typing import Protocol


def default_store_path() -> Path:
    if env := os.environ.get("ON_SAVIOR_STORE"):
        return Path(env)
    base = os.environ.get("XDG_DATA_HOME") or Path.home() / ".local/share"
    return Path(base) / "on-savior-ui" / "library.json"


@dataclass
class SaveMeta:
    """What the user has added to one save."""

    tags: list[str] = field(default_factory=list)
    note: str = ""
    starred: bool = False
    """Starred saves are never touched by retention."""

    @classmethod
    def from_dict(cls, raw: dict) -> "SaveMeta":
        return cls(
            tags=[str(t) for t in raw.get("tags", [])],
            note=str(raw.get("note", "")),
            starred=bool(raw.get("starred", False)),
        )

    def is_empty(self) -> bool:
        return not self.tags and not self.note and not self.starred


@dataclass
class RetentionPolicy:
    """An auto-rotate rule for one continuity.

    The budget is whichever of ``max_bytes`` / ``max_count`` is set; saves are
    thinned until both fit. Everything else describes what rotation may not
    take away — see :mod:`on_savior_ui.rotate` for how candidates are ranked.
    """

    enabled: bool = False
    max_bytes: int | None = None
    max_count: int | None = None
    keep_recent: int = 5
    """Always keep this many most recently written saves."""
    keep_manual: bool = True
    """Only autosaves are eligible for rotation."""
    keep_branch_points: bool = True
    """Never drop a save that two different timelines descend from."""
    label: str = ""
    """Optional name for the continuity, shown instead of character · ship."""

    @classmethod
    def from_dict(cls, raw: dict) -> "RetentionPolicy":
        base = cls()
        known = {f: raw[f] for f in asdict(base) if f in raw}
        if known.get("max_bytes") is not None:
            known["max_bytes"] = int(known["max_bytes"])
        if known.get("max_count") is not None:
            known["max_count"] = int(known["max_count"])
        return replace(base, **known)

    def is_empty(self) -> bool:
        return self == RetentionPolicy()


class MetadataStore(Protocol):
    """Storage seam: a JSON file today, a database later."""

    def save_meta(self, key: str) -> SaveMeta: ...
    def all_save_meta(self) -> dict[str, SaveMeta]: ...
    def put_save_meta(self, key: str, meta: SaveMeta) -> SaveMeta: ...
    def drop_save_meta(self, key: str) -> None: ...
    def policy(self, continuity_id: str) -> RetentionPolicy: ...
    def all_policies(self) -> dict[str, RetentionPolicy]: ...
    def put_policy(self, continuity_id: str, policy: RetentionPolicy) -> RetentionPolicy: ...
    def drop_policy(self, continuity_id: str) -> None: ...
    def known_tags(self) -> list[str]: ...


class JsonStore:
    """A :class:`MetadataStore` kept in one JSON file, rewritten atomically."""

    VERSION = 1

    def __init__(self, path: str | os.PathLike | None = None):
        self.path = Path(path) if path else default_store_path()
        self._data: dict | None = None

    # -- file plumbing ----------------------------------------------------
    def _load(self) -> dict:
        if self._data is None:
            try:
                self._data = json.loads(self.path.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                self._data = {"version": self.VERSION, "saves": {}, "policies": {}}
            self._data.setdefault("saves", {})
            self._data.setdefault("policies", {})
        return self._data

    def _flush(self) -> None:
        data = self._load()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=self.path.parent, suffix=".tmp")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as fh:
                json.dump(data, fh, indent=2, sort_keys=True)
            os.replace(tmp, self.path)
        except BaseException:
            Path(tmp).unlink(missing_ok=True)
            raise

    # -- per-save metadata ------------------------------------------------
    def save_meta(self, key: str) -> SaveMeta:
        return SaveMeta.from_dict(self._load()["saves"].get(key, {}))

    def all_save_meta(self) -> dict[str, SaveMeta]:
        return {k: SaveMeta.from_dict(v) for k, v in self._load()["saves"].items()}

    def put_save_meta(self, key: str, meta: SaveMeta) -> SaveMeta:
        saves = self._load()["saves"]
        if meta.is_empty():
            saves.pop(key, None)
        else:
            saves[key] = asdict(meta)
        self._flush()
        return meta

    def drop_save_meta(self, key: str) -> None:
        if self._load()["saves"].pop(key, None) is not None:
            self._flush()

    # -- retention policies -----------------------------------------------
    def policy(self, continuity_id: str) -> RetentionPolicy:
        return RetentionPolicy.from_dict(self._load()["policies"].get(continuity_id, {}))

    def all_policies(self) -> dict[str, RetentionPolicy]:
        return {
            k: RetentionPolicy.from_dict(v)
            for k, v in self._load()["policies"].items()
        }

    def put_policy(self, continuity_id: str, policy: RetentionPolicy) -> RetentionPolicy:
        policies = self._load()["policies"]
        if policy.is_empty():
            policies.pop(continuity_id, None)
        else:
            policies[continuity_id] = asdict(policy)
        self._flush()
        return policy

    def drop_policy(self, continuity_id: str) -> None:
        if self._load()["policies"].pop(continuity_id, None) is not None:
            self._flush()

    def known_tags(self) -> list[str]:
        tags = {t for m in self.all_save_meta().values() for t in m.tags}
        return sorted(tags)
