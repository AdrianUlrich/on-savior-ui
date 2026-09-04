# Ostranauts data model (decoded)

What we've established about the game's files and mechanics. Verified against
Early Access Build 0.14.5.17; spot-checked against the community wiki.

## Locations

- **Game data**: `<install>/Ostranauts_Data/StreamingAssets/data/` — ~70
  subdirectories of plain JSON (interactions, conditions, condtrigs, loot,
  traitscores, careers, ships, …). Some files need lenient parsing
  (control characters in strings, `//` comments, trailing commas).
- **Saves**: `.../AppData/LocalLow/Blue Bottle Games/Ostranauts/Saves/<name>/`
  containing `saveInfo.json` (headline metadata, readable without unzipping),
  `portrait.png`, `screenshot.png`, and `<name>.zip`.

## Save zip layout

- `<player name>.json` — world state: financial ledger (`aLIs`), objectives,
  jobs, plots, market snapshot, AI ship manager, and the player ship's loose
  objects (`aCOs`).
- `ships/*.json` — one file per ship/station. **People live here**: entries in
  a ship's `aCOs` whose `aConds` include `IsHuman`. The player is the person
  matching the world file's `strPlayerCO`.
- Conditions on any object are strings `Name=<duration>x<magnitude>`
  (e.g. `SkillHacking=1.0x1`, `StatContact=1.0x87.3`).

## The social system

**Needs** are the currency: each character tracks axes (Contact, Esteem,
Intimacy, Privacy, Self-Respect, Meaning, Altruism, Autonomy, Security,
Family, Achievement, …) as `Stat<Axis>` conditions scored 0–210 where
**lower is better**.

**Moves** (`SOC*` interactions, bulk in `interactions2.json`) resolve through
two chains:

- *Gate*: `CTTestUs` names a condtrig. Its `aReqs` is an **any-of** trait list
  (`bAND` is false on every multi-trait social gate in the current build),
  `aForbids` blocks, `fChance` is a flat pre-roll (see below).
- *Effect*: `LootCTsUs` / `LootCTsThem` name loot tables (`strType: trigger`)
  whose entries `TUpX=<dur>x<mag>` / `TDnX=...` are condtrigs with
  `strCondName: Stat<Axis>` and `fCount` ±1 — a need delta of
  `fCount × mag × fChance`. `TUp` frustrates the need, `TDn` satisfies it.
  (An insult is `TUpEsteem` on the target; a dark joke `TDnContact`.)

**Replies**: a move's `aInverse` lists the moves that can answer it
(`bRandomInverse` = the NPC draws randomly). **Traits** come in mirrored
pairs (`strAnti`); their passive stat effects hang off the condition's `aPer`
loot table. **Chargen**: `traitscores.json` rows are `name,cost,flag` — cost
in *years* (negative = the trait refunds years), `flag=1` marks real chargen
traits (homeworld markers are 0).

## Selection mechanics (decompiled)

From `Assembly-CSharp.dll` (`CondTrigger.Triggered`,
`GUISocialCombat2.SetData`), decompiled with ILSpy:

1. The conversation UI creates one button for **every** reply in the current
   move's `aInverse` that passes its gate — no sampling or hand size.
2. A gate first rolls its flat `fChance`; failing hides the move for this
   refresh (this is what a free reroll re-rolls).
3. The any-of trait walk **short-circuits on the first match** — match count
   is never used. Even the "(Trait)" tag on a button is just the first match.

Consequences: overdetermined moves are *not* more likely to appear; a trait
whose enable set is a subset of a build-mate's adds nothing but its passive
effects, refund years, and forbids. Trait value is purely **marginal unlocks**
(the report's build planner computes exactly this). Notable strict subsets:
Cruel ⊂ Arrogant (18/18), Lustful ⊂ Gregarious, Treacherous ⊂ Arrogant,
Strong ⊂ Tough.

Not yet analyzed: NPC-side choice among valid replies, relationship-formation
rolls (`strLootRELChange*`), plot/stakes conversations.

## Decompilation setup

Mono assembly, trivially decompilable:

```console
$ bash dotnet-install.sh --channel 8.0 --install-dir ~/.dotnet
$ ~/.dotnet/dotnet tool install --global ilspycmd --version 8.2.0.7535
$ export DOTNET_ROOT=~/.dotnet PATH=~/.dotnet:~/.dotnet/tools:$PATH DOTNET_ROLL_FORWARD=LatestMajor
$ ilspycmd -t CondTrigger "<install>/Ostranauts_Data/Managed/Assembly-CSharp.dll" > CondTrigger.cs
```

## References

- [Social Moves — Ostranauts Wiki](https://ostranauts.wiki.gg/wiki/Social_Moves)
  (direction convention, partial move tables)
- [Character creation — Ostranauts Wiki](https://ostranauts.wiki.gg/wiki/Character_creation)
  (trait year costs, aging)
- `data/DebugSocialAudit.csv` — the developers' own gate success-rate audit
  (fed by the same `SocialStats` counters the gate code updates)
