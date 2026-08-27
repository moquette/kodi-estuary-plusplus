# Attribution

**Requires Kodi 22 (Piers) or newer.** Estuary 8 declares `xbmc.gui 5.18.0` and
`xbmc.python 3.0.2`, neither of which Kodi 21 provides, so Kodi 21 and earlier
refuse to install it and refuse to run it. That is deliberate. See the project
`README.md` and `notes/kodi22-hardfail.md` for the measurements.

Estuary 8 (`skin.estuary8`) is a source fork of **Estuary MOD V2**
(`skin.estuary.modv2`), taken from a pinned upstream commit on the `Piers`
branch and maintained here as our own tree. It exists because of the work of
others:

- **Estuary** - the original Kodi skin by **phil65 and Team Kodi**
- **Estuary MOD V2** - the MOD by **Guilouz**, Matrix+ continuation by **PvD**
- **Piers maintenance** - **b-jesch** (the pinned upstream source:
  <https://github.com/b-jesch/skin.estuary.modv2>, `Piers` branch; exact commit
  in `UPSTREAM.lock`)
- **Weather icons** (`extras/weather/`, the skin's baked-in default set) -
  **Outline HD Weather Icons** by **braz** (vendored from
  <https://github.com/braz96/resource.images.weathericons.outline-hd>), based on
  the **weather-icons** project by **Erik Flowers**
  (<http://erikflowers.github.io/weather-icons/>). Licensed **Creative Commons
  Attribution 3.0** (the pack's LICENSE.txt ships alongside the icons at
  `extras/weather/LICENSE.txt`).
- **The hi-res Kodi wordmark** (`media/extras/logo-text-hires.png`, 290x89) is
  Team Kodi's mark, vendored from **Estuary 7** 1.0.78, where it ships at the
  same path and has been in use on hardware since 1.0.x. It replaces the 112x36
  `icons/logo-text.png` that Estuary MOD V2 compiled into `media/Textures.xbt`,
  which Kodi had to upscale 1.39x on Home and 2.78x on a 4K output.

## Licenses (inherited, unchanged)

- Code: **GNU General Public License v2.0**
- Artwork: **Creative Commons Attribution-ShareAlike 4.0**

See `LICENSE.txt` (upstream's license file, kept verbatim). Upstream copyright
headers in skin files are never removed.

## What Estuary 8 changes from upstream

Upstream's `Piers` branch **disabled Skin Shortcuts** rather than porting it:
`addon.xml` carries `<!--<import addon="script.skinshortcuts" version="1.1.3"/>-->`
and the `shortcuts/` directory still holds only the v2 format. Estuary 8 is that
port. It adds the v3 configuration (`shortcuts/menus.xml`, `widgets.xml`,
`properties.xml`, `templates.xml`, `backgrounds.xml`) and fixes the skin-side
integration for Skin Shortcuts 3.0.1, including two paths that destroyed user
data. The reasoning, the control map and the verification runs are in the
repository's `notes/`, and the fixes are itemised in `modv2/README.md`.

The weather icons are integrated rather than referenced, so the skin needs no
weather icon resource add-on out of the box. The picker for alternative packs is
kept and remains optional.
