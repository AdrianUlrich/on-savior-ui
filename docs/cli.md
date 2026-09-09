# CLI

All commands run through the `on-savior-ui` entry point:

```console
$ uv run on-savior-ui <command> [args]
```

## Commands

### `saves`

Lists every save folder with headline metrics from `saveInfo.json` (no zip
extraction — fast):

```console
$ uv run on-savior-ui saves
detectivation                       Haaña De Rings       $         325     2.0h  2025-11-14 12:11:04
skipped gott tools                  Haaña De Rings       $       3,080    10.8h  2025-11-14 21:04:06
...
```

Columns: save name, player, money, real playtime, save timestamp.

### `save <name>`

Full metrics for one save (parses the save zip):

```console
$ uv run on-savior-ui save "skipped gott tools"
```

Prints a JSON metrics block — money, age, play/sim time, ledger totals
(income/expense), objectives done, open jobs, plot beats — followed by the
player character's ship, skills, and condition count.

The name is the save folder name (quote it; they contain spaces).

### `social-graph [--out DIR]`

Exports the social-move graph for analysis (default `analysis/social_graph/`):

- `nodes.csv` — one row per `SOC*` move: title, source file, opener flag,
  gate tests, loot tables, required/forbidden traits.
- `edges.csv` — response links from each move's `aInverse` reply list.

For the fully resolved dataset (need deltas, families, marginals) use the
[analysis pipeline](analysis.md) instead — this command is the quick raw export.

### `library [--json] [--saves-dir DIR] [--no-link-reseeded]`

Lists saves grouped into playthroughs, each in play-time order with its lineage:

```console
$ uv run on-savior-ui library
■ Ashi · K-Leg: Azikiwe Commercial  [2289f9df]  18 saves · 0.8 GB · 40h played
   ●    7.56h  $    11,542      44 MB  nuklear
   ·    8.93h  $    11,542      46 MB  autosave_27_nuklear
   ◆    9.16h  $    11,542      46 MB  autosave_29_nuklear
   ●    9.20h  $    11,542      47 MB  no scam this time
   ·    9.39h  $    38,969      47 MB  autosave_30_nuklear  ← branched from autosave_29_nuklear
```

`●` manual save, `·` autosave, `◆` a save two timelines descend from. `--json`
dumps the raw index instead. See [saves-ui.md](saves-ui.md) for how continuities
and lineage are derived.

### `serve [--host H] [--port P] …`

Runs the save library web app. Read-only by default; each write is unlocked by
its own flag.

| Flag | Effect |
|---|---|
| `--host`, `--port` | Bind address (default `127.0.0.1:8765`); use `0.0.0.0` to reach it from another device |
| `--saves-dir`, `--store` | Override the saves folder and the tags/notes/policies file |
| `--allow-delete` | Permit deleting saves and applying auto-rotate |
| `--trash-dir DIR` | Move deleted saves there instead of erasing them |
| `--archive-dir DIR` | Destination for "archive copy" |
| `--auto-rotate`, `--rotate-interval S` | Apply enabled retention policies in the background |
| `--no-link-reseeded` | Keep re-seeded runs as separate continuities |

Needs the web extra: `uv run --extra web on-savior-ui serve`.

### `rotate [CONTINUITY] [--apply] [--trash-dir DIR]`

Previews retention for continuities with a budget set (match by id or a
substring of the label; omit for all), listing every save with keep/drop and the
reason. `--apply` carries it out.

### `bangbang [--host H] [--port P]`

Launches the bang-bang burn planner (a Streamlit app) at
`http://localhost:8501` by default. See [bangbang.md](bangbang.md) for the
data/intent split and the underlying physics.

## Environment variables

| Variable | Meaning |
|---|---|
| `ON_SAVIOR_GAME_DIR` | Path to the Ostranauts install folder (the one containing `Ostranauts_Data/`) |
| `ON_SAVIOR_SAVES_DIR` | Path to the `Saves` folder |
| `ON_SAVIOR_STORE` | Path to the tags/notes/policies file (default `~/.local/share/on-savior-ui/library.json`) |

Without them, common Steam locations are probed: `/mnt/*/Program Files (x86)/Steam/...`,
`/mnt/*/SteamLibrary/...`, `~/.steam`, `~/.local/share/Steam` for the game, and
`/mnt/*/Users/*/AppData/LocalLow/Blue Bottle Games/Ostranauts/Saves` or
`~/.config/unity3d/...` for saves.
