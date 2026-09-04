# Save library UI

A local web app for browsing, annotating, and pruning your Ostranauts saves.
It reads the saves folder directly, so it can run on the machine that holds the
saves and be opened from another device on the same network.

```console
$ uv run --extra web on-savior-ui serve
saves:   /mnt/c/Users/.../Blue Bottle Games/Ostranauts/Saves
store:   ~/.local/share/on-savior-ui/library.json
serving: http://127.0.0.1:8765
```

## Continuities and lineage

Saves are grouped into **continuities** — one per playthrough — and each
continuity's saves are linked into a **lineage**.

`saveInfo.json` carries a `seedId` that is stable across a run, so it forms the
groups. Older builds re-seed when you save under a new name, which splits one
run in two; those halves are stitched back together when the character, job,
and play time line up (disable with `--no-link-reseeded`).

Within a continuity, `playTimeElapsed` only grows while you play, so a save's
parent is the most recently *written* save whose play time it continues from.
That makes reloads visible: a save written after a longer-played sibling but
with less play time on it branched off an earlier point.

```
◆ autosave_29_nuklear      9.2h    ← two children, so a fork
  └╴ no scam this time     9.2h       the branch that was abandoned
· autosave_30_nuklear      9.4h    ← the line that continued
```

The **Lineage** view draws that graph; **Cards** and **Table** show the same
saves flat. Grouping can also be switched to character, ship, or build.

## Tags, notes, and stars

Anything you add is written to a sidecar store, never to the game's files. Its
key is `<seedId>:<epochCreationTime>`, which does not change when a save is
renamed, so annotations survive renames. Starred saves are exempt from rotation.

Store location, in order: `--store`, `$ON_SAVIOR_STORE`,
`$XDG_DATA_HOME/on-savior-ui/library.json`, `~/.local/share/on-savior-ui/library.json`.

## Managing saves

| Action | Needs | Notes |
|---|---|---|
| Rename | — | Rewrites the folder, the `<name>.zip`, and `strName` in both copies of `saveInfo.json`. The archive is rebuilt to a temporary file and CRC-checked before it replaces the original. Expect a few seconds on a large save. |
| Download | — | Streams the save's zip to the browser. |
| Archive copy | `--archive-dir DIR` | Copies the whole save folder to `DIR`, timestamping the name if it is taken. |
| Delete | `--allow-delete` | With `--trash-dir DIR` the folder is moved there instead of erased. |

Both permissions are server-side: the browser is told which actions exist and
hides the rest, so a session started without `--allow-delete` cannot delete
anything even if someone calls the API by hand.

## Auto-rotate

Per-continuity retention, configured from the **Auto-rotate…** button on a
group header. Set a size budget (GB) and/or a maximum number of saves, and
rotation thins the continuity until it fits.

**What it protects.** Manual saves (`keep_manual`), starred saves, the first
save of the run, forks and the tip of every timeline (`keep_branch_points`),
and the newest N (`keep_recent`, default 5). If the budget cannot be met
without breaking one of those, rotation stops and reports `over_budget` rather
than taking a protected save.

**How it chooses.** Everything else is ranked by what its removal would cost:

    gap(i)  = (earliest child's play time, or i's own if it is a tip) − parent's play time
    cost(i) = gap(i) / (1 + newest play time − i's play time)

and the cheapest is dropped, repeatedly. Because the cost is divided by age,
spacing settles proportional to age — recent history stays dense, old history
gets progressively coarser — with no tier table to tune.

**When it runs.** *Preview rotation* and *Apply now* in the UI act on demand.
Starting the server with `--auto-rotate` (plus `--allow-delete`) also sweeps
every enabled policy every `--rotate-interval` seconds. From the shell:

```console
$ uv run on-savior-ui rotate "Ashi"            # preview
$ uv run on-savior-ui rotate "Ashi" --apply --trash-dir ~/ostranauts-trash
```

## Serving to another device

```console
$ uv run --extra web on-savior-ui serve --host 0.0.0.0 --port 8765
```

There is no authentication, so only do this on a network you trust — anyone who
can reach the port gets whatever the server's flags allow.

## HTTP API

| Method | Path | Purpose |
|---|---|---|
| `GET` | `/api/library` | Full index: saves, continuities, tags, capabilities. Never opens a zip. |
| `GET` | `/api/saves/{key}/detail` | Metrics, crew, and recent ledger from inside the archive (cached per save). |
| `GET` | `/api/saves/{key}/screenshot.png`, `/portrait.png` | The save's images. |
| `GET` | `/api/saves/{key}/download` | The save's zip. |
| `PATCH` | `/api/saves/{key}` | `{tags, note, starred}` |
| `POST` | `/api/saves/{key}/rename` | `{name}` |
| `POST` | `/api/saves/{key}/archive` | Copy to the archive folder. |
| `DELETE` | `/api/saves/{key}` | Delete or move to trash. |
| `PUT` | `/api/continuities/{id}/policy` | Store a `RetentionPolicy`. |
| `POST` | `/api/continuities/{id}/rotate[?apply=true]` | Plan, or plan and execute. |

Interactive docs at `/api/docs`.

## Moving the store to a database

`store.MetadataStore` is a `Protocol` with nine methods, all taking and
returning `SaveMeta` / `RetentionPolicy` dataclasses keyed by a string. Nothing
else in the package touches storage, so a Postgres implementation only has to
satisfy that protocol and be passed to `ServerConfig(store=...)`:

```sql
create table save_meta (
    save_key text primary key,       -- "<seedId>:<epochCreationTime>"
    tags     text[] not null default '{}',
    note     text   not null default '',
    starred  boolean not null default false
);
create table retention_policy (
    continuity_id      text primary key,   -- the run's earliest seedId
    enabled            boolean not null default false,
    max_bytes          bigint,
    max_count          integer,
    keep_recent        integer not null default 5,
    keep_manual        boolean not null default true,
    keep_branch_points boolean not null default true,
    label              text    not null default ''
);
```

`known_tags()` becomes a `select distinct unnest(tags)`. Both keys are content
identifiers rather than paths, so one database can hold the annotations for
several machines' save folders side by side.
