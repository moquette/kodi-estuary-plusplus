# Future item: port "sticky RSS" from Estuary 8

Status: PLANNED, not started. Re-checked 2026-09-26: nothing from this plan is in the
skin (no `rss_ticker_visible`, `player_osd_active`, `show_rss_always`, string 31178 or
rss control 9906/9907/9908 under `skin.estuary.plusplus/`). The line numbers below were
verified against the skin (then `skin.estuary.pov`, now `skin.estuary.plusplus`) at
commit `dffd7a8` (2026-08-31) and the skin has moved since: at 1.5.0 `Includes.xml` has
`MediaFlags` at line 306, `BottomBar` at 1324 and `BottomBarTwoListInfo` at 1386, and
`strings.po` has `#31177` at 888. Re-verify every anchor before executing.

## Context

Estuary 8 (decommissioned 2026-08-31, archived at `moquette/kodi-estuary8`) shipped an
opt-in "Always show RSS feed" feature in 0.1.44/0.1.45: the RSS ticker draws in every menu
window and over fullscreen playback, not only on Home. The owner wants it duplicated in
`skin.estuary.plusplus`, including the ticker staying up during movies, TV shows, and IPTV
live TV.

The donor's final state was verified end-to-end on a Piers bench and its two commits
(`056c47d1`, `3e4a4cbc`) document the hard-won lessons a port must keep:

1. **One master expression.** `rss_ticker_visible` = the skin setting AND Kodi's own
   Interface > Skin > "Show RSS news feeds" switch. Every ticker and every piece of content
   that yields tests this expression, never the skin setting alone (otherwise content stays
   hidden after the master switch goes off - the donor's 0.1.44 defect).
2. **Explicit rss control ids.** `CRssManager::GetReader` caches one reader per
   (controlID, windowID) pair and re-points the observer on a hit; two id-0 rss controls in
   window Home silently kill Home's feed updates, and an id-0 ticker in fullscreenvideo
   never drew at all. Ids 9906/9907/9908 are load-bearing.
3. **Yield is asymmetric.** Bottom-strip content hides when a ticker actually draws - except
   where that content cannot reasonably yield (File Manager paths, settings help text), where
   the ticker stands down instead via a `rss_visible=false` param.

## Owner decisions (binding, given 2026-08-31)

- Full scope: menu windows AND playback (VideoFullScreen covers movies/TV/live TV; music
  visualisation included for parity).
- Toggle default OFF, opt-in - stock look until enabled.
- **No scrim / no special background treatment.** The donor drew a CC000000 osdfade under
  the playback ticker because a bare ticker over near-white video measured 1.53:1
  (illegible). Owner rejected non-stock treatment, so the playback tickers rely on
  `shadowcolor` alone - recorded here as an accepted risk. In menu windows the ticker sits
  on the stock `frame/InfoBar.png` gradient Estuary++'s BottomBar already draws.

All paths below are under `skin.estuary.plusplus/`. Estuary++ idiom for colors: `button_focus` /
`text_shadow` (match Home.xml:1262-1277), not the donor's `$VAR[SkinColorVar]`.

## Steps

### 1. strings.po - one new string
`language/resource.language.en_gb/strings.po`, after the `#31177` block (line 890),
splitting the `#empty strings from id 31178 to 31229` comment:

```
#: /xml/SkinSettings.xml
#. Skin toggle: keep the RSS ticker on screen in every window and over playback
msgctxt "#31178"
msgid "Always show RSS feed"
msgstr ""

#empty strings from id 31179 to 31229
```

### 2. Includes.xml - two expressions
After line 30, beside the existing expression block. Carry the donor's comment explaining
why both switches are ANDed.

```xml
<expression name="rss_ticker_visible">Skin.HasSetting(show_rss_always) + System.GetBool(lookandfeel.enablerssfeeds)</expression>
<expression name="player_osd_active">Player.Seeking | Player.HasPerformedSeek(3) | [Player.Paused + !Player.Caching] | Player.Forwarding | Player.Rewinding | Player.ShowInfo | Player.ShowTime | Window.IsActive(seekbar) | Window.IsActive(fullscreeninfo) | Window.IsActive(videoosd) | Window.IsActive(musicosd) | Window.IsActive(playerprocessinfo) | Window.IsActive(pvrosdchannels) | Window.IsActive(pvrchannelguide) | Window.IsActive(videobookmarks) | Window.IsActive(subtitlesearch) | Window.IsActive(osdvideosettings) | Window.IsActive(osdaudiosettings) | Window.IsActive(osdsubtitlesettings) | Window.IsActive(osdcmssettings) | Window.IsActive(gameosd) | Window.IsActive(pvrradiordsinfo) | Window.IsVisible(1103) | !String.IsEmpty(Player.SeekNumeric) | !String.IsEmpty(PVR.ChannelNumberInput) | $EXP[infodialog_active]</expression>
```

`player_osd_active` is measured on Estuary++, not copied: the player-state cluster is the verbatim
trigger list of DialogSeekBar.xml:5 (Estuary++ has no `Hide_OSDInfo` setting and no `isSeeking`
expression; `[Player.Paused + !Player.Caching]` is Estuary++'s own idiom); each window term is a
bottom-anchored or band-crossing overlay reachable during playback, verified per file.
Donor windows Estuary++ trimmed (1134/1135/1138/1141, lrclyrics) are dropped; Estuary++'s
Custom_1110 Tempo and sliderdialog are top-anchored and excluded.

### 3. Includes.xml - shared ticker in BottomBar (reaches 25 windows)
BottomBar include, lines 1291-1352:
- After line 1292: `<param name="rss_visible">true</param>`
- After the info group's closing `</control>` (line 1348), before
  `<include>TouchButtons</include>`, the ticker, with the donor's DO-NOT-DROP-THE-ID
  comment adapted:

```xml
<control type="rss" id="9906">
	<left>600</left>
	<right>20</right>
	<bottom>5</bottom>
	<height>35</height>
	<font>font12</font>
	<urlset>1</urlset>
	<hitrect x="-100" y="0" w="1" h="1" />
	<titlecolor>button_focus</titlecolor>
	<textcolor>button_focus</textcolor>
	<shadowcolor>text_shadow</shadowcolor>
	<headlinecolor>FFC0C0C0</headlinecolor>
	<visible>$EXP[rss_ticker_visible] + !Window.IsVisible(home) + $PARAM[rss_visible]</visible>
	<animation effect="fade" time="300">VisibleChange</animation>
</control>
```

`left 600` clears BottomBar's left furniture (menu button x12-48, label x64-364). The root
group's existing `slide 0,112` on `$EXP[infodialog_active]` (line 1295) carries the ticker
off-screen under info dialogs for free.

### 4. Includes.xml - MediaFlags yield gates (rss_yield param)
MediaFlags include, lines 323-514 (four grouplists):
- After line 324: `<param name="rss_yield">true</param>` (with the donor's one-line comment).
- Grouplist #1 (line 326, video flags, callers wrap in bottom 10 h40 groups) and
  grouplist #3 (line 435, music flags, bottom 10 h60): add
  `<visible>![$EXP[rss_ticker_visible] + $PARAM[rss_yield]]</visible>`
- Grouplists #2 (fullscreenvideo) and #4 (visualisation) need NO gate: they only draw while
  `player_osd_active` is already true, so the playback tickers have already yielded.
  (Pre-existing stray `)` after `</visible>` at line 475 - leave untouched, separate
  concern.)
- Dialog call sites pass `<param name="rss_yield" value="false" />` (a modal dialog slides
  the underlying BottomBar+ticker off-screen, so yielding there throws content away for
  nothing - the donor's DialogPVRInfo lesson): DialogSeekBar.xml:54, DialogVideoInfo.xml:791,
  DialogMusicInfo.xml:560, DialogPVRInfo.xml:348.
- Window-hosted call sites keep the default (no edit): Home.xml:1261, MyVideoNav.xml:94,
  MyMusicNav.xml:36, MyPlaylist.xml:37, MyPVRRecordings.xml:80.

### 5. Includes.xml - BottomBarTwoListInfo gate
Lines 1353-1402 (sole consumer MyMusicPlaylistEditor.xml:98; both counters bottom 0 h65
in-band). First child of the root group: `<visible>!$EXP[rss_ticker_visible]</visible>`

### 6. Home.xml - ticker visibility rewrite
Line 1275 becomes:
```xml
<visible>$EXP[rss_ticker_visible] | Skin.HasSetting(hide_mediaflags) | !ControlGroup(2000).HasFocus</visible>
```
Home keeps its own full-width id-0 ticker; the shared 9906 stays suppressed on Home by
`!Window.IsVisible(home)` plus its unique id. The donor's menu-editor exclusion is omitted:
Estuary++ ships no script window that overlays Home (verified).

### 7 + 8. Playback tickers
Append as last control before `</controls>`:
- `VideoFullScreen.xml` (after line 75): the Step-3 rss block with `id="9907"`,
  `left 20 / right 20`, visible `$EXP[rss_ticker_visible] + !$EXP[player_osd_active]`.
- `MusicVisualisation.xml` (before line 148): identical with `id="9908"`.
No scrim controls (owner decision).

### 9. BottomBar stand-down call sites (`rss_visible=false`)
- `FileManager.xml:73` - footer paths + counters span the whole band; donor measured that
  hiding them buys a ticker with almost nowhere to draw.
- `SettingsCategory.xml:142` - help textbox id 6 (bottom 25 h104) owns the strip.
- `SkinSettings.xml:537` - textbox id 6 (bottom 27 h100) same.
Each: `<include content="BottomBar"><param name="rss_visible" value="false" /></include>`
Verified NOT needed (band clear): Settings, SettingsProfile, SettingsSystemInfo, EventLog,
MyWeather, MyPics, MyGames, MyPrograms, MyFavourites, MyPVRProviders, MyPVRSearch,
MyPVRGuide, Custom_1100_AddonLauncher.

### 10. Per-window yield gates (`<visible>!$EXP[rss_ticker_visible]</visible>`)
- `MyPVRTimers.xml:67-79` - NextTimer label (x1050-1900, y1010-1070).
- `MyPVRChannels.xml:184-196` - NextProgramme label, same geometry.
- `AddonBrowser.xml:89-98` - "Last updated" group (overlaps x600-1505); add beside the
  existing `$EXP[sidebar_visible]` visible.
- MyPVRGuide: NO gate - its EPG detail group grazes the band by 10 empty pixels (measured).

### 11. SkinSettings.xml - the toggle
Grouplist 700 (General section), after radiobutton 705's `</control>` (line 69); id 710
free:
```xml
<control type="radiobutton" id="710">
	<label>$LOCALIZE[31178]</label>
	<include>DefaultSettingButton</include>
	<onclick condition="System.GetBool(lookandfeel.enablerssfeeds)">Skin.ToggleSetting(show_rss_always)</onclick>
	<onclick condition="!System.GetBool(lookandfeel.enablerssfeeds)">ActivateWindow(InterfaceSettings)</onclick>
	<selected>$EXP[rss_ticker_visible]</selected>
</control>
```
Two conditional onclicks (master switch off routes to InterfaceSettings instead of toggling
a dead setting); `<selected>` is the expression so the tick reflects "actually drawing".
Default OFF.

## Verification

1. **Reference scan**: sweep the skin for dangling references (includes referenced but
   never defined, `$VAR`/`$EXP` undefined, fonts not in Font.xml, 31xxx label ids missing
   from strings.po, texture paths missing from media/) - zero new findings expected. Both
   new expressions are defined in Step 2 and the one new string in Step 1; no new fonts or
   textures are introduced.
2. **Repo gates**: a qa agent (not the main assistant, per project rule) runs
   `bin/check-all estuarypp` from the kodi meta-root - all 5 gates green (pytest,
   ruff, the two `build_skin.py --check` runs, `check_version_bump.py`).
3. **Bench observation** (bench/reset-bench, bench/kodi; mirrors the donor's 0.1.45 pass):
   - Toggle OFF: pixel-identical to stock (ticker only on Home under existing rules).
   - Both switches ON: ticker in menu windows; MediaFlags rows, PVR labels, playlist-editor
     counters, AddonBrowser "Last updated" yield.
   - Master switch off mid-flight: every ticker vanishes AND all yielded content returns.
   - Playback: ticker over playing video; pause/OSD/bookmarks/process-info/PVR OSD/volume/
     channel-number entry each hide it; returns on resume. Live TV during channel switching.
   - File Manager paths intact + no ticker; settings help text intact + no ticker.
   - Reader-cache trap: soak Home 15+ min with sticky on - Home's feed keeps updating; the
     fullscreen ticker actually draws (the donor's id-0 regression test).
   - Toggle: tick mirrors drawing; click with master off jumps to InterfaceSettings.

No version bump or release steps in this plan; releasing follows the normal repo flow when
the owner says ship.

## Open items (accepted recommendations)
- `subtitlesearch` term is donor-parity (dialog is centered, clears the band); kept.
- Kodi 22's fullscreen-game window also loads VideoFullScreen.xml, so games get the ticker
  as a superset of the ask; accept (add `!Player.HasGame` to 9907 if unwanted).
- MyPVRGuide no-gate rests on static geometry; if the bench shows overlap, gate its detail
  group like Step 10.
