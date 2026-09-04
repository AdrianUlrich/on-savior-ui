# Python API

Package: `on_savior_ui` (src layout, Python ≥ 3.12). No required dependencies
beyond the stdlib; the web app is an optional extra (`--extra web`: FastAPI and
uvicorn) and the analysis tools (pandas, networkx, scipy, scikit-learn) are dev
dependencies.

## `gamedata` — the game's shipped data

```python
from on_savior_ui.gamedata import GameData, load_lenient, find_install

gd = GameData()                      # auto-detects the install
gd.data_dir                          # .../Ostranauts_Data/StreamingAssets/data
gd.table("interactions")             # every record from interactions/*.json,
                                     #   each annotated with its source file in "_src"
gd.index("conditions")               # same, keyed by strName
gd.interactions, gd.conditions,      # cached indexes for the common tables
gd.loot, gd.condtrigs, gd.condrules
gd.social_moves                      # the SOC* subset of interactions
```

`load_lenient(path_or_text)` parses the game's not-quite-strict JSON: raw
control characters inside strings, `//` line comments, and trailing commas.
Use it for any file under `data/` — several fail strict parsing.

## `saves` — reading save games

```python
from on_savior_ui.saves import list_saves, find_saves_dir, Save

for save in list_saves():
    print(save.name, save.info["money"])

save = Save(find_saves_dir() / "detectivation")
save.info          # saveInfo.json (metadata; available without opening the zip)
save.metrics()     # money, playtime, ledger totals, objectives, jobs, plot beats
save.world         # the player world file: ledger (aLIs), jobs, plots, market
save.ship_ids      # every ship/station in the save
save.ship("OKLG")  # one ship's raw record
save.people()      # Person objects across all ships (or people(ship_id))
save.player        # the Person matching strPlayerCO, or None
```

`Person` wraps a character record: `.name`, `.ship`, `.conditions` (parsed
from `Name=<duration>x<magnitude>` strings), `.skills`, `.stats`, and
`.prefixed(*prefixes)` for arbitrary condition-name filters.

Everything is read-only and lazy: the zip is opened once per `Save`, ships
parse on first access.

## `catalog` — the save library

Fast indexing built from `saveInfo.json` alone, so listing 30 saves never opens
a 45 MB archive.

```python
from on_savior_ui.catalog import Library, SaveRef, scan, continuities

lib = Library.load()               # or Library.load(dir, link_reseeded=False)
lib.refs                           # SaveRef per save, newest first
lib.groups                         # Continuity per playthrough
lib.by_key("<seedId>:<epoch>")     # a save by its stable key
lib.group_of(key), lib.group_by_id(id)
lib.as_dict()                      # the JSON the web UI consumes
```

`SaveRef` exposes the metadata as typed properties — `.name`, `.player`,
`.ship`, `.money`, `.play_time` and `.sim_time` (hours), `.saved_at`,
`.is_autosave`, `.base_name`, `.size_bytes`, `.key` — plus `.zip_path` and
`.asset("screenshot" | "portrait")`.

`Continuity` holds one playthrough's `saves`, the `seed_ids` it spans, and
`parents` (key → parent key). `.children()` inverts that; keys with more than
one child are the forks. See [saves-ui.md](saves-ui.md) for the rules behind
both.

## `store` — tags, notes, and policies

```python
from on_savior_ui.store import JsonStore, SaveMeta, RetentionPolicy

store = JsonStore()                      # ~/.local/share/on-savior-ui/library.json
store.put_save_meta(key, SaveMeta(tags=["gold"], starred=True))
store.put_policy(continuity_id, RetentionPolicy(enabled=True, max_bytes=5 * 10**9))
store.known_tags()
```

`MetadataStore` is the `Protocol` these implement; swapping in a database means
satisfying it and passing the result to `ServerConfig(store=...)`.

## `rotate` — retention planning

```python
from on_savior_ui.rotate import plan

result = plan(continuity, policy, store.all_save_meta())
result.remove          # the Decisions that would be deleted
result.freed_bytes, result.over_budget
```

Planning is pure — it decides, it does not delete. Every save comes back with
`keep` and a `reason`.

## `manage` — writing to the saves folder

```python
from on_savior_ui.manage import rename, delete, archive, ManageError

rename(lib.root, ref, "new name")        # folder + zip + both saveInfo copies
delete(lib.root, ref, trash_dir=None)    # or move aside
archive(lib.root, ref, Path("~/backups").expanduser())
```

The only module that mutates saves. Each call re-validates that the target sits
directly inside the saves root and holds a `saveInfo.json`, and `rename` builds
the new archive in a temporary file that is CRC-checked before it replaces the
original.

## `web` — the app

```python
from on_savior_ui.web import ServerConfig, create_app, serve

serve(host="0.0.0.0", allow_delete=True, trash_dir="~/trash")
app = create_app(ServerConfig(saves_dir=..., store=JsonStore()))   # any ASGI host
```

Needs the `web` extra. Endpoints are listed in [saves-ui.md](saves-ui.md).

## `resolve` — social-move mechanics

```python
from on_savior_ui.resolve import Resolver

rv = Resolver()            # or Resolver(GameData(...))
rv.trait_costs             # {trait: chargen year cost} from traitscores.json
rv.trait_meta              # + friendly name, description, anti-trait
rv.social_moves            # {name: MoveMechanics}
```

`MoveMechanics` per move: `enabled_by` / `forbidden_by` (chargen traits,
`Temp` variants folded into their base), `gate_and`, `gate_chance` (the flat
appearance roll), `needs_us` / `needs_them` (need-axis deltas resolved
through the loot tables; negative = satisfies), `markers`, and relationship
change annotations. See [data-model.md](data-model.md) for what these mean
in game terms.

## `social` — graph extraction

```python
from on_savior_ui.social import response_edges, export_graph

edges = response_edges(gd)      # (source, target, kind) from aInverse lists
export_graph(gd, "out/dir")     # nodes.csv + edges.csv
```
