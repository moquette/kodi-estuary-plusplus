# Attribution

`script.estuary8.shortcuts` is a fork of **Skin Shortcuts**
(`script.skinshortcuts`) version **3.0.1**, written by **MikeSiLVO** and, before
him, **anxdpanic** and **Unfledged**.

Upstream: <https://github.com/MikeSiLVO/script.skinshortcuts>

Substantially all of the code in this add-on is theirs. The fork exists for one
reason, recorded below, and it is intended to stay readable against upstream so
their later work can still be compared and carried across by hand.

## Licence

**GPL-2.0-only**, unchanged from upstream. `LICENSE.txt` is upstream's own file,
copied verbatim. The fork adds no licence terms and removes none. Because this
add-on ships as Python source, the distributed zip is itself the corresponding
source required by the GPL.

## Why this is a fork and not a patch

The add-on is a dependency. Patching an installed copy of `script.skinshortcuts`
in place is silently undone by upstream's next release: no error, no failed
build, no symptom until the behaviour reverts. Kodi resolves add-ons by id, so
the only way to hold a change reliably is to hold it under a **different id**.

This is deliberately **not** a version bump made to outrank the official build.
This add-on does not compete with `script.skinshortcuts`, cannot be overwritten
by it, and can be installed alongside it. Upstream is free to release whatever
it likes.

## What was changed

1. **Add-on identity.** `id`, `name`, `version` and `provider-name` in
   `addon.xml`; the settings section id; the log prefix; and the
   `special://profile/addon_data/` directory the add-on reads and writes. Thirteen
   sites in ten files, all of them the literal add-on id.

2. **Control 307 opens the shortcut picker.** Upstream's own
   `docs/skinning/management-dialog.md` documents control `307` as "Change action
   (keyboard input)" and control `401` as "Choose shortcut from groupings". A skin
   whose menu editor exposes 307, as Estuary 8 does and as Estuary 7 did before
   it, therefore offers a button reading "Change action" that opens a raw text
   field prefilled with a string such as
   `ActivateWindow(Videos,videodb://movies/titles/,return)`. That is not editable
   by a normal user.

   The fork points 307 at the picker the add-on already has, and falls back to
   upstream's keyboard when the skin declares no groupings, so any skin that
   relies on 307 being a keyboard is unaffected. See `_choose_action` in
   `resources/lib/skinshortcuts/dialog/pickers.py`.

3. **One-time data adoption.** Because the `addon_data` directory is keyed on the
   add-on id, a box that already has a configured menu would otherwise start
   empty under the new id. On first run the fork copies an existing
   `script.skinshortcuts` profile across, once, without modifying the original.
   See `adopt_legacy_userdata` in `resources/lib/skinshortcuts/userdata.py`.

4. **A declared widget type is honoured when browsing.** Upstream's
   `docs/skinning/widgets.md` documents `browse="true"` using an example that
   declares a type in the same tag:

   ```xml
   <widget name="movies-browser" label="Browse Movies" type="movies" browse="true">
   ```

   In 3.0.1 that declaration is discarded: `_browse_widget_path` called
   `_pick_widget_type` unconditionally and used its answer. Cancelling the prompt
   returned `None`, and both call sites read `None` as "return to the picker", so
   the whole selection was thrown away and the user landed back where they
   started. The documentation and the code disagreed; this follows the
   documentation. Reported upstream as issue #124.

5. **A browsed path's type is inferred rather than asked for.** Kodi's library
   paths name their own content, so `videodb://movies/titles/` is `movies`
   without asking anyone. Content is deliberately not sampled to decide this:
   `Files.GetDirectory` reports type `unknown` for library nodes and returns
   nothing at all for a library that has not been scanned, so sampling would
   answer differently on two boxes holding the same menu. See
   `_infer_widget_type` in `resources/lib/skinshortcuts/dialog/pickers.py`.

   Related, and the reason inference was being suppressed: a plugin add-on
   resolved from `<content source="addons" target="video"/>` used to take
   `content.target` as its widget type, giving `widgetType="video"`. That is a
   target, not one of the documented types, so it matched no skin condition while
   still being non-empty.

6. **`pathLabel`.** A readable twin of the existing `path` property, so a skin can
   show "Movies / Titles", or an add-on's own name, where it would otherwise print
   `videodb://movies/titles/`. Named for the `{base}Label` convention upstream
   already uses for `widgetLabel` and `backgroundLabel`. It falls back to the raw
   path, so it is never emptier than what it replaces. See `describe_path` in
   `resources/lib/skinshortcuts/constants.py`.

Nothing else is changed. Upstream's module layout, naming, typing, docstring
style, error handling and translations are left as they are, on purpose.
