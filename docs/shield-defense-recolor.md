# Why Shield Defense can't be recolored (Brute and every other AT)

Read-only investigation of the Rebirth client's compiled data (2026-10-15).

**Finding:** this isn't Brute-specific. No Shield Defense power, for any archetype, has customizable FX.

- Brute, Tanker and Scrapper `*_Defense.Shield_Defense.*` power records reference only plain
  `POWERS/SHIELDS/*.FX`. None has a `CUSTOMIZEABLEPOWERS/...` FX block or a `Color Tintable` palette,
  which is what Power Customization tints.
- `CUSTOMIZEABLEPOWERS/SHIELD*` doesn't exist anywhere in `powers.bin` or `fxinfo.bin`: no tintable
  shield FX were ever built.
- The three ATs' powerset records are identical in their customization fields (`CustomShields` costume
  key, `Shield_Default` part). Brute and Tanker differ only in AT attrib tables and melee exclusions.
- Same in the base game: Rebirth's override only adds an Unrelenting interaction to One with the Shield.
- The shield itself is a costume part (`CustomShields`, bone `WepL`). Some shield models have a color
  mask (e.g. Round), others don't (e.g. Riot1), so shield color also depends on the model chosen.

**Fix (maintainer side):** author tintable copies of the shield FX under `CUSTOMIZEABLEPOWERS/SHIELDS/`,
then add customfx entries (`Color Tintable` plus optional themes) to each power in
`defs/powers/Brute_Defense_Shield_Defense.powers`, `Tanker_Defense_Shield_Defense.powers`,
`Scrapper_Defense_Shield_Defense.powers` (and Stalker if present). Shield models without masks need new
masked textures to take costume color.

**Check in game to confirm:** a Tanker or Scrapper with Shield Defense should be missing the same color
options, and shield color behavior should change with the shield model selected.
