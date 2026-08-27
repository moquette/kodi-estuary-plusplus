# Estuary 8

A Kodi 22 skin. Stand-alone until it releases, then it merges into the Kodi
project. Nothing from here goes into `~/Code/moquette/kodi` before that.

## The ethos, and it governs every decision below

**A stock-looking Estuary skin, with Estuary 7 and FENtastic widgets and
customizations folded into it. Assets are folded in to reduce installation
dependencies.**

Two consequences, and they are easy to get backwards:

**The stock look is the product for v1, not forever.** E8 ships looking like
Estuary. What the donors contribute up to release is **widgets and
customizations, not style**. Someone who knows Estuary should recognise E8 on
sight and then find it does more. This is why the base is stock Estuary and not
MOD V2 or FENtastic, and why a wholesale restyle is out of scope before release
even where FENtastic's styling is nicer.

**After release, it gets painted.** The owner's sequencing: stock-looking first,
then repaint toward the FENtastic look once the functionality is shipped and
proven. Style is deferred, not abandoned.

That deferral is only cheap if the architecture keeps it cheap, which makes it
an engineering constraint now rather than a design question later:

- **Colours must go through Kodi's own mechanism.** Stock Estuary already does
  this properly, with 14 `colors/*.xml` themes at 392 bytes each that Kodi
  MERGES over `colors/defaults.xml`. A FENtastic-look theme could largely be one
  more such file. What defeats it is the **160 literal hex values across 42
  files** that bypass the mechanism entirely: every one is a place a future
  repaint has to be done by hand. Do not add more, and consolidate the existing
  ones opportunistically while working in a file for other reasons.
- **Textures must stay editable.** A compiled `Textures.xbt` cannot be repainted
  in any practical way. FENtastic's rounded corners are alpha masks, real PNG
  files (`masks/focus.png`, `masks/focus-long.png`, `buttons/button-fo.png`,
  `buttons/dialogbutton-fo.png`, all corner alpha 0 and centre 255). Loose PNGs
  can be swapped; a 759KB binary blob cannot. Kodi reads loose PNGs fine and the
  bundle only wins when both exist.

### Phases, and the end state

**Phase 1, before release: the stock look.** Function folded in, style left
alone.

**Phase 2, after release: two looks.** The default **E8** look, and an **F8**
(FENtastic 8) look. The user picks.

**That is a solved problem in Kodi and does not need inventing.** Estuary already
ships two texture themes beside its default: `media/curial.xbt` (672KB) and
`media/flat.xbt` (1.1KB), selected through `lookandfeel.skintheme`. So "E8 look
or F8 look" is exactly what that mechanism exists for, and F8 becomes a theme
rather than a fork or a rewrite.

Two facts to know before phase 2 starts, both measured:

- **Theme sources are stripped at packaging.** `themes/curial/` and
  `themes/flat/` ship as EMPTY directories; only the compiled `.xbt` bundles are
  distributed. So authoring a theme means keeping loose source PNGs in the repo
  and compiling them at build time, which is a build-tooling requirement, not a
  skin one.
- **Nothing in the shipped base is loose.** `media/` is 1.4MB across three
  `.xbt` files and ZERO loose image files (magic `58425446`, XBTF confirmed).
  Compiling needs Kodi's `TexturePacker`, which is not on this machine, and
  reading an existing bundle needs LZO, which is also not installed. For
  contrast, the FENtastic donor ships **790 loose files and no bundle at all**,
  so its artwork is directly usable as theme source.

**Not today's problem.** Recorded so phase 2 starts from facts instead of a
survey, and so nobody "solves" it early by exploding a bundle we may never need
to explode.

**Assets ship inside the skin.** No `resource://` image add-ons, no bundled
helper the user has to install, nothing that turns "install the skin" into
"install four things". There is a working precedent for exactly this in the
FENtastic donor: 49 weather icons were pulled out of
`resource.images.weathericons.outline-hd` and integrated at
`media/weather/small/`, then PROVEN independent by deleting that add-on from
the bench before re-testing. Note the licensing obligation that came with it,
recorded in `../reference/README.md`: integrating someone else's artwork moves
the attribution duty onto us.

### The one place the ethos and an earlier decision pull against each other

**Skin Shortcuts 3 is an installation dependency**, and the ethos says to
minimise those. It was chosen for a real structural reason (stock Estuary's Home
is 13 hard-coded items with show/hide gates and no dynamic content source, so
custom items and per-item widgets are unreachable without it). Both things are
true at once, so this is a genuine trade-off and not an oversight:

- **Depend on it.** One extra install, but it is a maintained Kodi-repo add-on
  that already solves menu and widget customisation properly on Kodi 22.
- **Fold it in.** Implement menu and widget customisation in skin-side Python
  under `scripts/`, the way the skin already will for everything else. Zero
  dependencies, fully consistent with the ethos, and materially more work: it
  means owning a menu editor, its storage format and its migrations.

Not decided. It should be, before the menu is designed, because the two produce
different architectures rather than different amounts of the same one.

**This directory is named `fentastic` and must not be renamed.** The AI session
history is keyed to the path. The name is now historical; the project is E8.

## The method: subtract until it breaks

Owner's direction, and it is the organising principle rather than a slogan.

E8 does not start by adding. It starts from stock Estuary, removes everything
that is not earning its place, and finds the floor by going past it. What breaks
tells us what was load-bearing. What does not break was never needed.

This is why the base is **stock Estuary 4.1.0** and not Estuary 7 / MOD V2.
Measured, not asserted:

| | stock Estuary 4.1.0 | Estuary 7 (MOD V2 derived) | MOD V2 Piers |
| --- | --- | --- | --- |
| files | **245** | 615 | 847 |
| dependencies | **1** | 5 | 4 |
| literal hex colours | **160** across 42 files | 427 across 61 | - |
| colour refs already named | **82 percent** | 51 percent | - |
| fonts | **3** ttf, 952KB | 9 files, 1.0MB | 21 files, **24MB** |
| `extras/` | **none** | 14MB | 65MB |

Starting from the smallest tree means most of the subtraction is already done,
and the rest is ours to do deliberately rather than inherited by accident.

**New and fresh without baggage.** Nothing carries forward because it was there
before. Every file in E8 has to justify itself on its own terms, and "upstream
shipped it" is not a justification.

Subtraction targets already identified in the base, before a line is written:

- `fonts/heebo_licence.txt` and `fonts/mardoto_license.txt` are licences for
  fonts stock Estuary does not ship. Dead weight in the vendor tree.
- `xml/Font.xml` references `arial.ttf`, which the skin does not contain. Kodi
  supplies that one, so this is correct, but it is worth knowing before someone
  "fixes" it by adding a font.

**Fonts: three, and they are Estuary's.** `NotoMono-Regular.ttf`,
`NotoSans-Regular.ttf`, `Roboto-Thin.ttf`. That is the whole font payload.
Nothing is taken from the other donors, which between them carry 38 font files
and over 26MB. The two orphan licence files above go with them.

## What E8 is built from

Three donors, all frozen in `../reference/`, all read only. Read
`../reference/README.md` before touching any of them.

1. **Base: stock Estuary 4.1.0**, from the Kodi 22.0-BETA1 bundle. E8 is a
   derivative of Team Kodi's Estuary and must say so.
2. **Functionality donor: Estuary 7 1.0.78.** Chiefly the tvOS and Fire TV
   remote parity work, which exists as a real file ONLY in that built tree.
   See `../reference/estuary7-1.0.78-MANIFEST.md`.
3. **Ideas donor: FENtastic Plus**, at `../build/skin.fentastic/`. Last in the
   sequence, by the owner's ordering: base first, E7 functionality second,
   FENtastic ideas third.

`../reference/` also holds two things that are not donors but are needed to
build correctly: **Skin Shortcuts 3.0.1**, and **MOD V2 on both Omega and
Piers** so that b-jesch's own Kodi 22 port can be read rather than guessed at.

## The build loop: rapid, pushed often, in this order

Owner's direction. Two rungs, and the order is not negotiable because the first
one is free and the second one is not.

1. **The macOS bench.** Wipeable, no hardware, drivable over JSON-RPC, and it
   can be relaunched in seconds. Everything gets proved here first.
2. **ts1 or the office Fire TV.** Real hardware, real remote, real 4K output,
   and the only place tvOS/FireTV remote behaviour and actual render scale can
   be judged. Slower to iterate, so it confirms rather than explores.

This is why "build rapidly and push frequently" needs the deploy path to already
work rather than being invented per release, and it is the concrete reason
`push-ts1.sh` is kept rather than subtracted. Two of its behaviours matter more
than the pushing: it pushes NAMED FILES ONLY, never `xml/` as a directory, and
it force-stops Kodi before writing. Both exist because the alternatives
destroyed the owner's Home menu twice.

E8 will need its own equivalent. Adapt that script; do not write a new one and
rediscover the traps.

## What subtraction does NOT apply to: the test apparatus

Owner decision. `build/skin.fentastic/`, `build/script.fentastic.helper/`,
`theloop/` and `push-ts1.sh` stay. "We should keep them for testing."

They read like leftovers from the previous project and they are not:

- **FENtastic Plus is the only skin currently running on real hardware**, on ts1
  and the office Fire TV. That makes those boxes usable test targets with a
  known-good skin to fall back to when E8 breaks them.
- **`push-ts1.sh` is a working deploy path to a Fire TV.** E8 needs exactly that
  mechanism. Adapting a script that already handles the traps (named-file pushes
  only, the generated-menu-file hazard, force-stop before push) beats writing a
  new one and rediscovering them.
- **`theloop/` patches are live on ts1**, so any E8 test on that box runs against
  a patched add-on. The patches are part of the test environment's definition,
  not a loose end.

Subtract everywhere else. Not here.

## Decisions already taken, with the reason

**Base is stock Estuary 4.1.0.** See the table above.

**Target is Kodi 22, and Kodi 21 is a hard fail.** `xbmc.gui` moves from
Estuary 7's `5.17.0` floor to `5.18.0`, which drops Kodi 21. That is intended,
not accidental, and it was verified against a real Kodi 21.3 rather than
assumed. Kodi 21 refuses in three independent places: install from zip is
rejected before anything is written to disk, enabling a hand-copied build is
rejected, and a profile that already had Estuary 8 active gets it disabled at
startup behind an "Incompatible add-ons" dialog that names the skin. Measured
numbers, log lines and screenshots are in `notes/kodi22-hardfail.md`.

The guard is two `<import>` lines and nothing else. No startup check was added,
because there is no state in which one could run: on Kodi 21 the skin is never
loaded, so skin-side code never executes.

**Do not add a `minversion` attribute to those imports.** With no `minversion`,
Kodi's `DependencyInfo` constructor copies `version` into it
(`versionMin(versionMin.empty() ? version : versionMin)`), so the bare `version`
IS the hard minimum. Supplying a `minversion` turns `version` into an upper
bound that Kodi 21 satisfies. A probe declaring
`minversion="5.17.0" version="5.18.0"` enables cleanly on Kodi 21.3, measured.
`estuary8/tools/check_kodi_floor.py` enforces the floor and its self-test mode
proves it catches that edit and four others:

```sh
python3 estuary8/tools/check_kodi_floor.py              # assert the floor
python3 estuary8/tools/check_kodi_floor.py --self-test  # assert the assertion
```

**The menu needs Skin Shortcuts 3, and the reason is structural.** Stock
Estuary's Home is `fixedlist id="9000"` with 13 hard-coded `<item>` blocks, each
gated by a `Skin.HasSetting(HomeMenuNo<X>Button)`. Show and hide is the only
user control. The container has no dynamic content source at all, and its 10
widget includes are bound to built-in item types rather than assignable per
item. A custom item pointing at POV or The Loop, a Tools menu, a Power menu, or
an arbitrary widget row are all unreachable by toggling 13 booleans.

Note what this reason is NOT. "v2 is being phased out" turned out to be shaky:
b-jesch still ships v2-shaped code on Piers, and 2.0.3 still runs on Kodi 22.
The durable reason is the structural one above. What IS true is that the Kodi 22
repo index offers `script.skinshortcuts` at **3.0.1 only**, and since Kodi treats
`<import version>` as a minimum, any skin declaring `1.1.3` on Kodi 22 resolves
to 3.0.1. There is no v2 to fall back to on this platform.

Skin Shortcuts 3.0.1 requires `xbmc.python 3.0.2`, which only Kodi 22 provides.

**b-jesch has commented the skinshortcuts import out entirely** at MOD V2 Piers
head `551f77b0`, `addon.xml:6`. Worth watching, but it does not change the above:
his skin does not need the customisation ours does.

## Naming, DECIDED

| what | value |
| --- | --- |
| skin add-on id | **`skin.estuary8`** |
| display name | **Estuary 8** |
| starting version | **`0.1.0`** |
| helper add-on id, IF one is ever created | **`script.estuary8.helper`** |

The id is effectively permanent: changing it after release loses every user's
settings. All four candidate ids were checked against the Kodi 22 Piers index
(1,068 add-on ids) and every one is free.

`estuary8` over `e8` because it carries the lineage E8 actually has, matches the
owner's existing `skin.estuary7`, and is discoverable by anyone looking for
Estuary forks. The helper id follows the ecosystem convention that a helper
mirrors its skin: `skin.aeon.tajo` pairs with `script.aeon.tajo.helper`,
`skin.copacetic` with `script.copacetic.helper`. This supersedes an earlier
`script.e8.helper`, which would have broken that pairing.

### A separate helper add-on is NOT required, and probably should not exist

This was researched rather than assumed, because it is the kind of thing that is
inherited by imitation.

**A skin can run a persistent background service itself.** Estuary 7's
`addon.xml` declares `xbmc.service` pointing at `scripts/services.py` alongside
`xbmc.gui.skin`, and that script runs a genuine `xbmc.Monitor` loop with
`waitForAbort` (`services.py:137,141`). It also declares `kodi.context.item`.
One add-on, full capability, zero dependencies. FENtastic's separate helper
declares `xbmc.python.library` plus `xbmc.service`, which is the same capability
housed separately rather than extra capability.

So the real reasons other projects split a helper out are:

- **Reuse across skins.** `script.embuary.helper` is depended on by many skins.
  Estuary 7 itself calls `script.embuary.info` and `script.artistslideshow`,
  which are other people's shared helpers. This does not apply to code only
  Estuary 8 will ever run.
- **Independent update cadence.** Patch logic without republishing the skin.

Neither is a capability limit, and the cost is concrete and already paid once:
FENtastic's pinned `script.fentastic.helper` 100.6.26 refused to let the skin
enable on the macOS bench, which had Ivar Brandt's 0.6.20a from a different
repo. Both had to be swapped together.

**Default: Python lives inside the skin at `scripts/`, following Estuary 7.**
Note that stock Estuary 4.1.0 declares only `xbmc.gui.skin` and
`xbmc.addon.metadata` and ships no Python at all, so E8 starts with none and
adds a service extension point only when something actually needs one.

## Open questions, not yet decided

- **`Textures.xbt`.** The base ships a 759KB compiled texture bundle. Kodi reads
  loose PNGs fine, but the bundle wins when both exist. Leaving it compiled
  keeps the skin's textures opaque and uneditable in git, which blocks the
  rounded-corners work directly. Explode it or keep it.
- **Whether the E8 repo gets its own git remote**, and if so whether it is
  public. It carries GPL-2.0 third-party skin code from three projects, so
  publishing has licensing consequences that need a deliberate decision.
