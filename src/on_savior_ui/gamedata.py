"""Access to Ostranauts' shipped game data (StreamingAssets/data).

Everything the game ships is plain JSON, but written for a lenient parser:
some files contain raw control characters inside strings, //-comments, or
trailing commas. ``load_lenient`` handles all three.
"""

from __future__ import annotations

import glob
import json
import os
import re
from functools import cached_property
from pathlib import Path

_DECODER = json.JSONDecoder(strict=False)

_STEAM_GLOBS = [
    "/mnt/*/Program Files (x86)/Steam/steamapps/common/Ostranauts",
    "/mnt/*/Program Files/Steam/steamapps/common/Ostranauts",
    "/mnt/*/SteamLibrary/steamapps/common/Ostranauts",
    str(Path.home() / ".steam/steam/steamapps/common/Ostranauts"),
    str(Path.home() / ".local/share/Steam/steamapps/common/Ostranauts"),
]


def find_install(explicit: str | os.PathLike | None = None) -> Path:
    """Locate the Ostranauts install directory.

    Order: explicit argument, $ON_SAVIOR_GAME_DIR, then common Steam paths.
    """
    candidates: list[str] = []
    if explicit:
        candidates.append(str(explicit))
    if env := os.environ.get("ON_SAVIOR_GAME_DIR"):
        candidates.append(env)
    for pattern in _STEAM_GLOBS:
        candidates.extend(sorted(glob.glob(pattern)))
    for cand in candidates:
        p = Path(cand)
        if (p / "Ostranauts_Data" / "StreamingAssets" / "data").is_dir():
            return p
    raise FileNotFoundError(
        "Ostranauts install not found; set ON_SAVIOR_GAME_DIR to the game folder"
    )


def load_lenient(text_or_path: str | Path) -> object:
    """Parse game JSON that the strict stdlib parser may reject."""
    if isinstance(text_or_path, Path):
        text = text_or_path.read_text(encoding="utf-8-sig")
    else:
        text = text_or_path
    try:
        return _DECODER.decode(text)
    except json.JSONDecodeError:
        cleaned = re.sub(r'^\s*//[^\n]*$', "", text, flags=re.MULTILINE)
        cleaned = re.sub(r",\s*([\]}])", r"\1", cleaned)
        return _DECODER.decode(cleaned)


class GameData:
    """Lazy loader over the data/ directory, one table per subdirectory.

    A "table" is the concatenation of every record in every ``*.json`` file
    of that subdirectory, each record annotated with its source file in
    ``_src``. Records are indexed by ``strName`` via :meth:`index`.
    """

    def __init__(self, install: str | os.PathLike | None = None):
        self.install = find_install(install)
        self.data_dir = self.install / "Ostranauts_Data" / "StreamingAssets" / "data"

    def table(self, name: str) -> list[dict]:
        records: list[dict] = []
        sub = self.data_dir / name
        files = sorted(sub.glob("*.json")) if sub.is_dir() else []
        for f in files:
            loaded = load_lenient(f)
            if isinstance(loaded, dict):
                loaded = [loaded]
            for rec in loaded:
                if isinstance(rec, dict):
                    rec["_src"] = f.name
                    records.append(rec)
        return records

    def index(self, name: str) -> dict[str, dict]:
        return {r["strName"]: r for r in self.table(name) if "strName" in r}

    @cached_property
    def interactions(self) -> dict[str, dict]:
        return self.index("interactions")

    @cached_property
    def conditions(self) -> dict[str, dict]:
        merged = self.index("conditions")
        merged.update(self.index("conditions_simple"))
        return merged

    @cached_property
    def loot(self) -> dict[str, dict]:
        return self.index("loot")

    @cached_property
    def condtrigs(self) -> dict[str, dict]:
        return self.index("condtrigs")

    @cached_property
    def condrules(self) -> dict[str, dict]:
        return self.index("condrules")

    @cached_property
    def social_moves(self) -> dict[str, dict]:
        """All social interactions (SOC*)."""
        return {
            k: v for k, v in self.interactions.items() if k.startswith("SOC")
        }
