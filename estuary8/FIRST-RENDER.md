# Estuary 8 0.1.0: first render on Kodi 22

Verified 2026-07-27 on the macOS bench. This is the first deliverable proved,
not asserted.

## What was proved

| check | result |
| --- | --- |
| Kodi build | `22.0-BETA1 (21.90.801) Git:20260727-a872eae1a5` |
| add-on resolved | `skin.estuary8`, name `Estuary 8`, version `0.1.0` |
| enabled / broken | `enabled: true`, `broken: false` |
| skin loaded | `load skin from: .../addons/skin.estuary8/ (version: 0.1.0)` |
| `ERROR` lines in log | **0** |
| `Unable to load` | **0** |
| Home renders | yes, main menu and empty-state panel both draw |

The only warning in the run is
`JSONRPC: Could not parse type "Setting.Details.SettingList"`, which is Kodi 22's
JSON-RPC schema change and has nothing to do with the skin. It was already
recorded in `../notes/kodi22-spike-findings.md`.

Evidence: `../notes/e8/estuary8-first-render.png` (gitignored, like all
screenshots in this repo).

## Two things that bit, worth not repeating

**Kodi's "keep this skin?" prompt reverts on timeout.** Switching with
`Settings.SetSettingValue lookandfeel.skin` over JSON-RPC raises a confirmation
dialog with a countdown, and if nothing answers it, Kodi silently reverts to the
previous skin. That is what happened on the first attempt and it looks exactly
like a failure to load. The reliable method is to stop Kodi, write
`lookandfeel.skin` directly into `userdata/guisettings.xml`, then start it. No
prompt, no revert.

**`ls` is aliased in this environment.** `L=$(ls -t a b | head -1)` captured a
whole `ls -l` line rather than a path, so every subsequent `grep "$L"` searched
nothing and reported zero errors from a log it never opened. Use literal paths.
The same alias already produced a miscount recorded in `../CLAUDE.md`.

## Two blockers for the build loop, neither caused by this work

**Kodi 22 lives in the session scratchpad.** The running app is
`/private/tmp/claude-501/.../scratchpad/kodi22-spike/Kodi22.app`. Scratchpads get
wiped. Rapid iteration against Kodi 22 needs it moved somewhere durable first.

**The bench library is empty.** `VideoLibrary.GetMovies` and `GetTVShows` both
return 0. Widgets, ratings and watched marks cannot be judged against an empty
library, and "the widget did not populate" would be indistinguishable from a
bug. This is pre-existing, not a regression: `MyVideos131.db` and
`MyVideos147.db` are both schema-sized at about 390KB.
