# The social-move analysis pipeline

The pipeline turns the game data into two pages: the analysis **report**
("Ostranauts Social Physics") and the standalone build-planner **applet**
("Airlock Diplomat"). Rerun after a game update:

```console
$ uv run python analysis/build_dataset.py    # game data -> analysis/out/*.csv + dataset.json
$ cd analysis
$ uv run python build_report.py              # -> out/report.html
$ uv run python build_planner.py             # -> out/planner.html
```

Both pages embed the same compact payload, built by `analysis/payload.py`
from `dataset.json` and injected at each template's `/*__DATA__*/null`
placeholder. The planner's logic lives separately in `analysis/planner.js`
and is inlined at its template's `/*__SCRIPT__*/` marker at build time
(published artifacts must be single-file — the artifact CSP blocks external
scripts — so the separation exists only in the source tree).

## `build_dataset.py`

Resolves every non-debug `SOC*` move through `on_savior_ui.resolve` and writes
to `analysis/out/`:

| File | Contents |
|---|---|
| `moves.csv` | One row per move: gating traits, gate chance, need deltas, valence, outcome family |
| `traits.csv` | One row per chargen trait: year cost, enables/forbids/net counts, sole-gate count, share-weighted enables, mean tone of enabled moves, per-family breakdown |
| `synergy.csv` | Trait pairs: co-enable counts (shared any-of gates) and conflicts (one enables what the other forbids) |
| `dataset.json` | Everything above plus the precomputed graph layout, consumed by the report |

Analysis choices:

- **Families** — moves with any need-axis effect are clustered on their
  concatenated us/them delta vectors (L2-normalized, agglomerative, cosine,
  k=10). Human-readable names and colors are assigned in `build_report.py`
  (`FAMILY_DISPLAY`); the five biggest clusters get named, the rest fold into
  "Minor Families", and moves without effects are "Flavor & Plumbing".
- **Valence** — the sum of a move's need deltas on the target; negative =
  prosocial (satisfies needs), positive = hostile.
- **Graph layout** — ForceAtlas2 over the `aInverse` reply links for connected
  moves; isolated moves are placed in a grid strip below.
- Debug-only moves (`interactions_debug.json`) are excluded everywhere.

## The report — `report_template.html`

A self-contained single-theme page (no external assets except Google Fonts):

1. a mechanics explainer,
2. the trait-economy scatter (year cost vs. net moves, colored by tone),
3. the sortable full trait table,
4. outcome-family cards with need signatures,
5. the browse-only conversation graph (family isolation, hover ledgers),
6. synergy, collision, subset, and mirrored-axis lists.

Published at
<https://claude.ai/code/artifact/d1b4d339-32c6-487a-a933-560856a1693e>.

## The planner applet — `planner_template.html`

A three-rail app for assembling a build against the marginal-value math:

- **Trait roster** (left): searchable checklist with year costs; selected
  traits become chips showing their *unique* contribution ("0 unique!" =
  fully redundant within the build).
- **Graph** (center): the conversation graph with amber (unlocked) / red
  (lost to forbids) rings. View filters: hide always-available ("anyone")
  moves, hide no-effect moves (both default on — also the performance fix),
  family isolation, and a fuzzy move filter with `-term` exclusion.
- **Objectives** (right): a mean↔nice tone slider (weights moves by their
  effect on the target), a "value of a refunded year" slider (in
  move-equivalents, so refund traits with mild downsides rise when years
  matter), a need-coverage bonus (+6 per axis you gain a first **unlocked**
  move for, in a chosen direction: replenish own / attack theirs / soothe
  theirs — basic always-available moves don't count), and a "score only
  moves matching the filter" toggle that turns the fuzzy filter into a
  target moveset. The **ranking** recomputes each unselected trait's
  composite marginal score with a per-term breakdown.
- **Coverage table** (under the graph): one row per need axis, four columns
  (us ↑ worsen / us ↓ replenish / them ↑ attack / them ↓ soothe), each cell
  showing the strongest *unlocked* modifier and the move providing it,
  falling back to the best Basic (always-available) move, dimmed with a BAS
  tag, when the build has none.

Published at
<https://claude.ai/code/artifact/c21e9f97-3c60-47c8-a160-8ec4c73bfeea>.

Republishing the same file path updates the same URL for either page.

## Checking the output

The repo's dev environment includes Playwright (`chromium-headless-shell`) for
render checks:

```console
$ uv run python -c "
from playwright.sync_api import sync_playwright; import pathlib
with sync_playwright() as p:
    b = p.chromium.launch(); pg = b.new_page()
    pg.goto(pathlib.Path('analysis/out/report.html').resolve().as_uri())
    pg.wait_for_timeout(1000); pg.screenshot(path='/tmp/report.png', full_page=True)"
```

Validation anchors: `SOCAskHowDoing` should read us Altruism −6 / Achievement +6,
them Altruism +6 / SelfRespect −6, and `SOCComplainAboutLAs` Autonomy −6 /
Security +6 on both sides (matches the wiki's hand-collected table).
