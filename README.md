# on-savior-ui

Read-oriented tooling for **Ostranauts** (Blue Bottle Games): parse the game's
shipped JSON and your save files, track progress metrics, and analyze the social
system — no save editing, no cheating.

Highlights:

- **Save library UI** — a local web app to browse, tag, group by playthrough,
  see where a run branched, and auto-rotate old autosaves away.
- **Save reader** — saves, ships, people, traits, skills, financial ledger, plots.
- **Game-data loader** — lenient JSON parsing of `StreamingAssets/data`, indexed tables.
- **Social-move analysis** — trait gates, need-axis effects, outcome families,
  and marginal trait value, rendered as an interactive report plus a
  standalone build-planner applet.
- **Bang-bang burn planner** — a Streamlit app for accelerate/flip/decelerate
  intercept burns, built from flight-computer-plausible sensor data plus
  your own burn intent.

## Quickstart

```console
$ uv run on-savior-ui saves                 # list your saves with headline metrics
$ uv run on-savior-ui save "<save name>"    # detailed metrics for one save
$ uv run on-savior-ui social-graph          # export the social-move graph as CSV
$ uv run on-savior-ui library               # saves grouped by playthrough, with lineage
$ uv run --extra web on-savior-ui serve     # the save library at http://127.0.0.1:8765
$ uv run on-savior-ui bangbang              # burn planner at http://localhost:8501
```

The game install and save folder are auto-detected (Steam under WSL or Linux);
override with `ON_SAVIOR_GAME_DIR` / `ON_SAVIOR_SAVES_DIR`.

## Documentation

| Doc | Contents |
|---|---|
| [docs/saves-ui.md](docs/saves-ui.md) | The save library: web UI, continuities, auto-rotate |
| [docs/cli.md](docs/cli.md) | CLI commands and environment variables |
| [docs/library.md](docs/library.md) | Python API: `GameData`, `Save`, `Resolver` |
| [docs/analysis.md](docs/analysis.md) | The social-move analysis pipeline and report |
| [docs/data-model.md](docs/data-model.md) | Decoded Ostranauts data formats and mechanics |
| [docs/bangbang.md](docs/bangbang.md) | The bang-bang burn planner: data vs. intent, and the physics |

Game data © Blue Bottle Games, read from your local install at runtime.
