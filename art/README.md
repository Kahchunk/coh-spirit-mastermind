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

Textures come out as PNG. Models come out as OBJ (LOD0 only). The model export is **experimental**:
triangles, UVs and normals decode correctly, but skinned parts aren't placed on the skeleton yet,
so arms can look folded or offset. A legacy `.geo` + `.wrl` pair from SilverAgeFan will let us
check positions against known values and fix that.

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
