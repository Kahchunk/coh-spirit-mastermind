# Art: custom spirit models

Working area for the Spirit Binding henchmen models. Reference assets pulled from the game live in
`art/reference/` and are **gitignored**: they're the game's art, so they stay on your machine.

```
art/
  blender/      your .blend working files
  max/          3ds Max 2015 scenes (rig + export happens here)
  export/       .wrl files from the CoH exporter, then .geo from getvrml
  textures/     source textures (PSD/PNG) and exported .tga
  reference/    pulled from the client by tools/extract_refs.py (not committed)
```

## Pulling references

```bash
python tools/extract_refs.py textures "Croatoa/Ghosts"
```

```bash
python tools/extract_refs.py geo "player_library/MALE_SHIRT\.geo"
```

```bash
python tools/extract_refs.py list "Croatoa"
```

Textures come out as PNG. Models come out as OBJ (LOD0 only), in their T-pose bind position,
with UVs. The decoder follows GetVrml's `compressDeltas` (OuroDev source), so geometry matches
the game. Bone weights are read but not exported to OBJ.

## What the Croatoa ghosts actually are

Read from the client's costume data:

- A standard humanoid body (`Ghost_Generic_Male` / female) wearing ordinary costume parts:
  - pants: `Loose`
  - chest: `Tight` with `skin_tshirt_01a/b`
  - head: `Masked_Bald` with the face skin `Skin_Croatoa_Ghost_02`
- Ranks differ only in clothing, such as a tank top versus a t-shirt, or cargo pants.
- The ghostliness comes from the skin texture and the body type, not from unique geometry.
- The wisps are a separate creature: Rularuu wisp textures, with their own `animations/Wisp/` set.

## Conventions confirmed in the game's own files

| Thing | Convention | Source |
|---|---|---|
| Model files | one `.geo` per body region and gender, e.g. `MALE_SHIRT.geo`, `fem_pants.geo`, `HUGE_BOOT.geo` | `player.pigg` / `stage1.pigg` |
| Mesh names | `GEO_<Region>_<Name>`, e.g. `GEO_Chest_Tight` | `.geo` headers |
| LODs | each mesh has `_LOD1` and `_LOD2` copies | `.geo` headers |
| Transparency | mesh names end in `__Alpha` when alpha-blended | `.geo` headers |
| Textures | referenced by `.tga` name inside the `.geo`; shipped as `.texture` (header + DDS) | `.geo` headers, texture piggs |
| Skinning | up to 2 bones per vertex (2 bone indices + 1 weight byte) | decoded `.geo` streams |
| Skeletons | male / fem / huge base poses in `animations/<body>/skel_ready2.anim` | `stage1a.pigg` |
| Scale | the male chest is about 3.4 units wide arm to arm in T-pose, so 1 unit is roughly 1 foot (unconfirmed) | decoded `MALE_SHIRT` |

## Art budget (OuroDev costume guide, adapted from Thunderspy's docs)

- No more than **1500 triangles** per costume piece.
- No texture larger than **1024**.
- Normal maps: flip the **green channel**.
- Assign textures in Max before export; otherwise the piece renders white in game.

## ScrapYarder master files

`SM_Master` (standard male), plus the female and huge versions, hold the player skeleton in T-pose with
hundreds of leftover developer costumes. Keep them in `art/scrapyard/`, which is **gitignored**. They're
original studio files and must never land in this public repo (`*.max` is ignored too). Open them in Max
2015, or better, use a cleaned bones-and-base-body copy.

## Pipeline (per OuroDev docs + Rebirth; to confirm with SilverAgeFan)

1. Model and UV in Blender, then bring the mesh into **3ds Max 2015** as FBX.
2. Rig to the matching **ScrapYarder master file** (male / female / huge) so the existing skeleton and
   animations are reused. Don't make a new skeleton; that's the part SilverAgeFan says breaks.
3. Name meshes `GEO_<Region>_<Name>` and add `_LOD1` / `_LOD2` versions.
4. Assign textures in Max **before** export. Flip the **green channel** of normal maps.
5. Export with `CoH_VRML_EXP.DLE` as "Paragon COH VRML97 (*.WRL)".
6. `getvrml` turns the `.wrl` into `.geo`; `gettex` converts textures.
7. Reference the new geometry from a costume part (`Geometry` / `Texture1` / `Texture2` fields) in the spec
   editor's costume **Part overrides**.

## Where color comes from

Player and henchman costume textures are painted **in grayscale**. The source PSDs measure about
0 saturation. Color is applied at runtime from the costume's Color1/Color2 values:

```
final color = base texture (grayscale detail) x mix(Color1, Color2, by mask)
```

The **Mask** layer group decides which color lands where: black takes Color1, white takes Color2.
One-off NPC pieces (the Croatoa Spirit face, a cadet hat) are painted in full color instead and
aren't tintable. A texture's alpha channel is a blend mask (e.g. where skin color shows), never
transparency.

Each original PSD keeps every map for one part in named layer groups: visible layers (color/detail),
`Bump`, `Spec` and `Mask`. Toggle a group on and export it to get that map.

## Live preview: CoH Art Bridge (Photoshop + 3ds Max)

1. Double-click **CoH Art Bridge** on the desktop (or `tools/CoH Art Bridge.cmd`). Leave its window open.
2. In Photoshop, open a part's `.psd` from `art/work/<part>/`. 3ds Max 2015 opens (first time only, about
   a minute) and loads the part with the game's tint applied, in perspective/top/front/right viewports.
3. Paint and **save** (Ctrl+S). Max reloads the textures and re-renders a preview sheet: both
   isometric corners plus front, back, left, right, top and bottom.
4. The **CoH Preview** panel in Photoshop (Window > Plugins) shows that sheet, so you can work on one
   screen. It also sets the look (Flat / Lit / Ghostly / Croatoa dusk) and Color1/Color2, with a
   "Use foreground" button for each.

Install the panel once: run `python tools/photoshop/package_plugin.py`, then double-click
`tools/photoshop/dist/coh-preview.ccx`. If Creative Cloud refuses an unsigned plugin, load
`tools/photoshop/coh-preview/manifest.json` with Adobe's **UXP Developer Tool** (Add Plugin > Load).

The looks are approximations: the Spirit glow comes from the game effect `Ghost_Ship_Enemies.fx`
attached to their body type, and in-game lighting varies by zone. The test server is the final word.

Blender still works as a fallback (`set COH_BACKEND=blender` before starting the bridge).

Each part folder holds `<part>.psd`, `<part>.obj`, and `part.json` (preview colors). The PSD uses
these layer groups:

| Group | Used for |
|---|---|
| `Color` | grayscale detail (or full color for NPC-only pieces) |
| `Mask` | black = Color1, white = Color2; leave empty for no tint |
| `Bump`, `Spec` | game maps, ignored by the preview |
| `UV guide` layer | your paint guide; never exported |

`part.json` stores the preview settings (`color1`, `color2`, `look`, `ghost_opacity`); the panel edits it.

New part from a game mesh (the starter PSD gets the groups and a UV guide):

```bash
python tools/art_bridge.py new spirit_chest --game "player_library/MALE_SHIRT.geo" --mesh GEO_Chest_Tight
```

New part from your own model: `--obj path/to/model.obj`. Two examples (a tintable rifle and the
Spirit face) are created with `python tools/art_bridge.py examples`.

## Weapon color masks (how shipped weapons do it)

Surveyed from the client (`tricks/WEAPONS/CustomWeapons.txt` and the custom weapon models):

- A tintable weapon's model references a **layered texture** `X_CustomWeapon_...`. That layered texture
  names a **base**, a **mask** (or `None`) and a **bump** map.
- About 70% of player weapon models use layered textures. 39 of the 63 custom-weapon layered textures
  have a real mask. The rest are older enemy weapons ported with plain textures, including the
  existing Assault Rifle "Chaingun" option, which reuses the Council texture and has no mask.
- **Base:** near-white grayscale detail; all hue comes from the player's colors.
- **Mask:** blocky black/white regions over the same UV layout. Black and white select the two color
  slots, and grays blend. Masks are often lower resolution than the base (e.g. 128x64 on a 512x256 base).
- Reusing a mask on a dark, already-colored base tints muddy (see the Vanguard rifle). Repaint the base light.

Preview any base + mask pair with two colorways:

```bash
python tools/mask_preview.py art/reference/mask_check.png <base.png> <mask.png>
```

## Open questions for SilverAgeFan

- Rebirth's Max 2015 setup: the `CoH_VRML_EXP` build, plus any MAXScript or project settings.
- ScrapYarder M/F/H master files: the skeleton to rig against.
- A legacy `.geo` + matching `.wrl` (one skinned part, one rigid part).
- Poly and LOD budgets for henchmen.
- Texture sizes and the mask conventions that let player colors tint correctly.
- Which public tools have issues, so we avoid them.
