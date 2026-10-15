# Spirit Binding: a Mastermind primary for City of Heroes: Rebirth

A proposed Mastermind primary whose henchmen are the spirits of Croatoa, plus the tooling to tune it and
turn it into a data patch the Rebirth team can review and compile.

The set is a clone of **Necromancy**, so balance, pet upgrades, Supremacy and Bodyguard all start from a
set that already ships. Nothing here needs server code changes: it's power, villain, powerset, category
and costume definitions.

| Slot | Necromancy power | Spirit Binding power | Henchmen |
|---|---|---|---|
| 1 | Dark Blast | Spectral Bolt | |
| 1 | Zombie Horde | Call the Restless | 3 Restless Spirits (Croatoa ghost minions) |
| 2 | Gloom | Grave Chill | |
| 6 | Enchant Undead | Binding Rite | upgrade 1 |
| 8 | Life Drain | Siphon Essence | |
| 12 | Grave Knights | Wailing Shades | 2 Wailing Shades (Croatoa ghost lieutenants) |
| 18 | Soul Extraction | Will-o'-the-Wisp | a fallen spirit returns as a Croatoa wisp |
| 26 | Lich | Lord of the Hollow | 1 Lord of the Hollow (Croatoa ghost boss) |
| 32 | Dark Empowerment | Ectoplasmic Ascension | upgrade 2 |

**Models:** the Croatoa ghosts share one male and one female model across all ranks. The plan is new
models per tier. Until they exist, the spec uses the shipped ghost costumes with per-tier tint and
scale. Custom models drop into each costume's *part overrides* (Geometry/Texture) once they're exported
with Rebirth's model pipeline (Rebirth already ships custom .geo in `z_rebirth_player.pigg`).

## Layout

```
spec/spirit_binding.json   the whole set: names, numbers, pets, costumes, colors (single source of truth)
editor/                    local editor (http://localhost:8765) + catalog.json of names from the client
tools/generate.py          spec + maintainers' source tree -> patch files + REPORT.md
tools/build_catalog.py     reads your installed client's .pigg archives to build editor/catalog.json
tools/cryptic_text.py      format-preserving editor for Cryptic textparser files
tests/                     unit tests over a SYNTHETIC fixture (stand-in for the real defs)
```

## For Corbin: tuning the set

```bash
python editor/serve.py
```

Open http://localhost:8765. Edit names, numbers, pet counts, base costumes, tints, scale, part overrides
and FX. Name fields autocomplete from your installed client and flag anything not in it. **Save**
writes `spec/spirit_binding.json` and keeps the previous copy in `spec/history/`. **Export JSON** and
**Import JSON** move a spec in and out (for example, a version the maintainers hand back).

Rebuild the name catalog after a Rebirth patch:

```bash
python tools/build_catalog.py
```

## For the Rebirth team: generating the patch

Point the generator at your text data tree (the folder whose `defs/powers/*.powers` and
`Defs/Villains/*.villain` the bins are built from). It only reads that tree.

```bash
python tools/generate.py --data <data root> --probe
```

`--probe` prints the first blocks of each template file and the field names they use. Check them
against `field_names` in the spec (`FullName`, `DisplayName`, `CostumePart`, ...). The spec's names were
inferred from compiled bins, not from your source, so this is the step that keeps the patch honest.

```bash
python tools/generate.py --data <data root> --out out
```

Output in `out/`, with `REPORT.md` listing every file, the template-to-new identifier map, and:

- **Errors** – anything still wired to Necromancy (a summon still creating zombies, an upgrade
  targeting a template pet, a template costume left on a cloned villain). Exit code is 1 if any exist.
- **Warnings** – fields that weren't in the template block and were added (likely a field-name
  mismatch), and an "art pass" list of icons/FX/power names still using Necromancy art.

New files: `Mastermind_Summon_Spirit_Binding.powers`, `Mastermind_Pets_<kit>[_2|_3].powers`,
`V_Mastermind_Spirit_Binding.nd`. Shared files (`Mastermind_Summon.powersets`, `Mastermind_Pets.powersets`,
both `Player_Mastermind_*.categories`, `MastermindPets.villain`) are written as full copies with the
original content untouched and new blocks or lines added, so a plain diff shows exactly what changed.

Known gaps to review by hand:

- Display strings are written as literals. If your tree uses message-store keys (`P12345...`), move
  them into your `.ms` files.
- Wisps use the wisp costumes on the ghost villain defs; confirm skeleton/ent type compatibility.
- Power numbers are left at Necromancy's values unless set in the spec.

## Tests

```bash
python -m unittest discover -s tests
```
