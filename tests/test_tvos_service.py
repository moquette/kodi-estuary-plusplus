"""service.tvos.pythonfix: two tvOS repairs, and NOTHING off tvOS.

This file replaces test_pythonfix_service.py and test_services_keymap.py, which
covered the same two payloads while they lived in two different add-ons. As of
skin.estuary.pov 1.3.0 both are in this one add-on and the skin ships no Python,
so one suite covers one service.

The no-op tests are the load-bearing ones. The shim writes into directories
belonging to third parties, so on any box that is not tvOS those directories must
come out of the boot byte-for-byte untouched, and the owner's "will this break my
Fire TV" question is answered by test_no_op_on_every_non_tvos_platform rather than
by a promise.

The tests import the REAL service.py and run its REAL payload against a fake
xbmc, rather than asserting on its source text. A substring check would pass even
if the platform gate had been deleted.
"""

from __future__ import annotations

import importlib
import re
import sys
import urllib.request

import pytest

import fake_kodi
from conftest import ROOT

ADDON = ROOT / "service.tvos.pythonfix"

# The add-on whose library directory carries the shim that matters. Spelled out
# here rather than imported from service.py so the test cannot silently follow
# the code to a different add-on: this id is the whole reason the fix reaches
# POV, Multi Weather and EZ Maintenance++, all three of which declare it.
REQUESTS_ID = "script.module.requests"

# The other four are requests' own dependencies, so Kodi installs them with it
# and PythonInvoker puts all five on a dependent add-on's sys.path. Listed here
# independently of service.py for the same reason.
MODULE_IDS = (
    REQUESTS_ID,
    "script.module.urllib3",
    "script.module.certifi",
    "script.module.idna",
    "script.module.chardet",
)


def _boot(tmp_path, platform, modules=MODULE_IDS):
    """One Kodi start on a box of the given platform. Returns (recorder, module).

    `modules` models the only realistic variation: the service writes into
    add-ons it does not own, and any of them may simply not be there.
    """
    for addon_id in modules:
        (_addons(tmp_path) / addon_id / "lib").mkdir(parents=True, exist_ok=True)
    rec = fake_kodi.install(platform, tmp_path)
    sys.modules.pop("service", None)
    service = importlib.import_module("service")
    service.main()
    return rec, service


def _addons(tmp_path):
    """Where fake_kodi maps special://home/addons/ to."""
    return tmp_path / "home" / "addons"


def _shim_dir(tmp_path, addon_id=REQUESTS_ID):
    return _addons(tmp_path) / addon_id / "lib"


def _scproxy(tmp_path, addon_id=REQUESTS_ID):
    return _shim_dir(tmp_path, addon_id) / "_scproxy.py"


def _scproxy_files(tmp_path):
    """Every _scproxy.py written anywhere under the fake profile, found by search.

    A search rather than a set of stats, so that a shim written to the WRONG
    directory shows up as a failure here instead of passing as an absence.
    """
    return sorted(tmp_path.rglob("_scproxy.py"))


def _keymap(tmp_path):
    return tmp_path / "keymaps" / "t7b-siriremote.xml"


def _written_files(tmp_path):
    """Every file the service left anywhere under the fake profile."""
    return sorted(p for p in tmp_path.rglob("*") if p.is_file())


# --------------------------------------------------------------------------- #
# The shim: written, and written everywhere Kodi will look for it
# --------------------------------------------------------------------------- #
def test_scproxy_written_to_every_module_dir_on_tvos(tmp_path):
    """One copy per module library directory, and nowhere else."""
    _boot(tmp_path, "TVOS")
    assert _scproxy_files(tmp_path) == sorted(
        _scproxy(tmp_path, addon_id) for addon_id in MODULE_IDS
    )


def test_the_shim_survives_an_update_to_any_single_module(tmp_path):
    """The whole reason there is more than one copy.

    MEASURED against the Kodi 22 source: an add-on update is a directory SWAP,
    not an extract over the top. CAddonInstallJob::Install calls
    CFilesystemInstaller::InstallToFilesystem (AddonInstaller.cpp:1203-1204),
    which unpacks into a temp uuid folder, renames the WHOLE old directory aside
    and RemoveRecursive's it (FilesystemInstaller.cpp:74-89). Files that were
    never in any zip go with it.

    So updating script.module.requests deletes its copy of the shim mid session,
    and with only one copy every networked add-on on the box would break again
    until the next Kodi start. Kodi offers no way to hear about that: there is no
    AddOn announcement flag at all (IAnnouncer.h:16-30), nothing under
    xbmc/addons/ calls Announce, and AddonEvents::ReInstalled has no Python
    bridge. Redundancy is the mechanism, so it is asserted rather than trusted.
    """
    _, service = _boot(tmp_path, "TVOS")

    # Kodi replaces the directory wholesale, so model that: remove it entirely.
    for path in _shim_dir(tmp_path).iterdir():
        path.unlink()

    survivors = _scproxy_files(tmp_path)
    assert len(survivors) == len(MODULE_IDS) - 1, (
        "one module updating must not take the shim off the path"
    )
    for path in survivors:
        assert path.read_text() == service.SCPROXY


def test_the_shim_lands_on_the_paths_kodi_builds_for_a_dependent_addon(tmp_path):
    """Agreement with Kodi's dependency resolution, not with ourselves.

    The shim is useless one directory away from a path entry, and that failure is
    silent: no error, no log line, just add-ons that carry on dying at import. So
    the shape is asserted rather than left to a comment. PythonInvoker builds an
    add-on's sys.path from its declared dependencies and recurses through them
    (PythonInvoker.cpp:208-213, the walk at :709-727, each inserted at :230-239),
    and each dependency contributes the directory named by its own library=
    attribute, which is "lib" for all five of these.

    MEASURED on atv1 2026-08-28 by reading the installed addon.xml files:
    plugin.video.pov, weather.multi and script.openweathermap.maps all declare
    script.module.requests, and script.module.requests declares the other four.
    """
    rec, service = _boot(tmp_path, "TVOS")
    assert service.SHIM_DIR_PATHS == tuple(
        "special://home/addons/%s/lib/" % addon_id for addon_id in MODULE_IDS
    )
    for path in service.SHIM_DIR_PATHS:
        assert path in rec.translated, (
            "every target must be resolved through Kodi, not built with expanduser"
        )


def test_requests_is_written_first(tmp_path):
    """Order inside the shim write, and it is documentation rather than luck.

    script.module.requests is the module whose import raises the error and the
    one every affected add-on declares directly, so it is the copy a reader is
    most likely to find and the shortest path back to the reason. The other four
    are insurance.
    """
    _, service = _boot(tmp_path, "TVOS")
    assert service.SHIM_DIR_PATHS[0] == "special://home/addons/%s/lib/" % REQUESTS_ID


def test_the_addon_declares_the_dependency_it_writes_into():
    """The declaration is what guarantees the directories exist when this runs.

    Kodi installs a dependency's own dependencies before the dependency itself,
    so declaring script.module.requests is not decoration: it is what makes the
    "the directories are already there" assumption true on a fresh install, and
    it pulls in the other four transitively. Dropping the import line would leave
    a service that silently skips on exactly the box it exists for.
    """
    text = (ADDON / "addon.xml").read_text(encoding="utf-8")
    assert re.search(r'<import addon="%s"' % re.escape(REQUESTS_ID), text), (
        "service.tvos.pythonfix must declare the add-on whose directory it writes into"
    )


def test_only_requests_is_declared(tmp_path):
    """One import, not five, and the service adapts instead of failing a check.

    Kodi has no minversion attribute, so every <import> is a hard version FLOOR
    somebody has to maintain. The other four arrive transitively. Declaring them
    would add four floors for no gain and would make a dependency change upstream
    an install failure rather than a skipped write.
    """
    text = (ADDON / "addon.xml").read_text(encoding="utf-8")
    imports = set(re.findall(r'<import addon="([^"]+)"', text))
    assert imports == {"xbmc.python", REQUESTS_ID}


def test_absent_module_dirs_are_skipped_not_created(tmp_path):
    """Absent is a reportable state, not a failure, and must not be papered over.

    Creating addons/script.module.<x>/ with no addon.xml in it would leave a
    malformed add-on directory for Kodi's add-on scanner to find, and for a later
    dependency install to land on top of.
    """
    rec, _ = _boot(tmp_path, "TVOS", modules=(REQUESTS_ID,))
    assert _scproxy_files(tmp_path) == [_scproxy(tmp_path)]
    assert sorted(p.name for p in _addons(tmp_path).iterdir()) == [REQUESTS_ID], (
        "the service must never create an add-on directory it does not own"
    )
    assert not any(level == fake_kodi.LOGWARNING for level, _ in rec.logs), (
        "a missing optional target is not a warning"
    )


def test_no_module_dirs_at_all_is_reported_and_survivable(tmp_path):
    """Nothing on this box could have been using requests, so say so and go on."""
    rec, _ = _boot(tmp_path, "TVOS", modules=())
    assert _scproxy_files(tmp_path) == []
    assert not _addons(tmp_path).exists()
    summary = [m for level, m in rec.logs if level == fake_kodi.LOGINFO][-1]
    assert "skipped" in summary
    assert _keymap(tmp_path).is_file(), "a skipped shim must not cost the keymap"


def test_scproxy_second_boot_is_idempotent_by_content(tmp_path):
    _boot(tmp_path, "TVOS")
    stamps = {p: p.stat().st_mtime_ns for p in _scproxy_files(tmp_path)}
    bodies = {p: p.read_text() for p in stamps}

    _boot(tmp_path, "TVOS")
    for path, stamp in stamps.items():
        assert path.read_text() == bodies[path]
        assert path.stat().st_mtime_ns == stamp, "unchanged content must not be rewritten"


def test_changed_scproxy_payload_is_rewritten(tmp_path):
    """A box carrying an older shim gets the new one, in every directory."""
    _, service = _boot(tmp_path, "TVOS")
    for path in _scproxy_files(tmp_path):
        path.write_text("# stale, and a different length from the real payload\n")

    _boot(tmp_path, "TVOS")
    for path in _scproxy_files(tmp_path):
        assert path.read_text() == service.SCPROXY


def test_a_deleted_shim_comes_back_on_the_next_start(tmp_path):
    """Self-heal, which is the backstop behind the redundancy rather than the
    front line. Gone entirely, not merely stale."""
    _, service = _boot(tmp_path, "TVOS")
    for path in _scproxy_files(tmp_path):
        path.unlink()

    _boot(tmp_path, "TVOS")
    written = _scproxy_files(tmp_path)
    assert len(written) == len(MODULE_IDS)
    for path in written:
        assert path.read_text() == service.SCPROXY


def test_scproxy_payload_satisfies_the_real_urllib_request(tmp_path):
    """The contract, checked against the consumer rather than against a comment.

    CPython 3.14 Lib/urllib/request.py:2035 imports exactly these two names, and
    _proxy_bypass_macosx_sysconf at :1953 documents the dict shape. A shim that
    imports cleanly but returns the wrong shape would break urllib the first time
    a host was checked, which is worse than not importing at all.
    """
    _boot(tmp_path, "TVOS")
    shim = {}
    exec(compile(_scproxy(tmp_path).read_text(), "_scproxy.py", "exec"), shim)

    settings = shim["_get_proxy_settings"]()
    assert set(settings) == {"exclude_simple", "exceptions"}
    assert settings["exclude_simple"] is False
    assert settings["exceptions"] == []
    assert shim["_get_proxies"]() == {}

    for host in ("example.com", "localhost", "127.0.0.1", "api.trakt.tv:443"):
        assert urllib.request._proxy_bypass_macosx_sysconf(host, settings) is False


# --------------------------------------------------------------------------- #
# The Siri remote keymap, moved here from skin.estuary.pov at skin 1.3.0
# --------------------------------------------------------------------------- #
def test_keymap_written_on_tvos(tmp_path):
    rec, _ = _boot(tmp_path, "TVOS")
    assert _keymap(tmp_path).is_file(), "tvOS must get the keymap"
    assert "Action(reloadkeymaps)" in rec.builtins


@pytest.mark.parametrize(
    "window,button,action",
    [
        ("FullscreenVideo", "6", "Back"),
        ("FullscreenLiveTV", "5", "OSD"),
        ("FullscreenLiveTV", "6", "Back"),
        ("Home", "6", "FullScreen"),
        ("global", "21", "FullScreen"),
    ],
)
def test_keymap_carries_the_playbook_mappings(tmp_path, window, button, action):
    """Every row of the stock-versus-ours table in playbook section 15."""
    _boot(tmp_path, "TVOS")
    body = _keymap(tmp_path).read_text()
    section = body.split("<%s>" % window, 1)[1].split("</%s>" % window, 1)[0]
    assert '<button id="%s">%s</button>' % (button, action) in section


def test_the_keymap_names_kodi_windows_and_no_skin_control(tmp_path):
    """Why this payload could move out of a skin at all, asserted not assumed.

    Every binding names a Kodi WINDOW and a Kodi ACTION. Nothing here is specific
    to Estuary POV, to any skin's control ids, or to any skin at all, which is
    what makes a Siri remote the box's property rather than a skin's. If a future
    edit introduced a skin-specific binding this add-on would silently become
    skin-coupled, so it fails here instead.
    """
    _boot(tmp_path, "TVOS")
    body = _keymap(tmp_path).read_text()
    windows = re.findall(r"^  </?(\w+)>", body, re.MULTILINE)
    assert set(windows) == {"FullscreenVideo", "FullscreenLiveTV", "Home", "global"}
    for skin_word in ("estuary", "Estuary", "pov", "POV", "Skin.", "Control."):
        assert skin_word not in body


def test_keymap_overrides_only_the_siri_controller(tmp_path):
    """Fire TV remote input arrives on a different path; scope must stay Siri."""
    _boot(tmp_path, "TVOS")
    body = _keymap(tmp_path).read_text()
    assert body.count('<customcontroller name="SiriRemote">') == 4
    assert "<keyboard>" not in body and "<remote>" not in body


def test_home_back_no_longer_opens_favourites(tmp_path):
    """The owner's actual symptom: the stock binding must be gone."""
    _boot(tmp_path, "TVOS")
    body = _keymap(tmp_path).read_text()
    assert "FavouritesBrowser" not in body
    home = body.split("<Home>", 1)[1].split("</Home>", 1)[0]
    assert '<button id="6">FullScreen</button>' in home


def test_the_keymap_filename_stays_out_of_the_vectored_prefix(tmp_path):
    """Playbook section 8: customcontroller.SiriRemote* is the ONLY excluded
    prefix, so this name is vectoring-eligible and stays a POSIX file only
    because the write is plain open(). Renaming it to the stock prefix would
    shadow Kodi's own shipped keymap instead of adding to it."""
    _, service = _boot(tmp_path, "TVOS")
    assert service.KEYMAP_NAME == "t7b-siriremote.xml"
    assert not service.KEYMAP_NAME.startswith("customcontroller.SiriRemote")


def test_keymap_second_boot_is_idempotent_and_does_not_reload(tmp_path):
    """Idempotent BY CONTENT: no rewrite, and no keymap reload, when unchanged."""
    _boot(tmp_path, "TVOS")
    body = _keymap(tmp_path).read_text()
    rec2, _ = _boot(tmp_path, "TVOS")
    assert _keymap(tmp_path).read_text() == body
    assert "Action(reloadkeymaps)" not in rec2.builtins


def test_changed_keymap_is_rewritten_and_reloads(tmp_path):
    """A box carrying an older payload gets the new one, and keymaps reload."""
    _boot(tmp_path, "TVOS")
    _keymap(tmp_path).write_text("<keymap><!-- stale --></keymap>\n")
    rec, service = _boot(tmp_path, "TVOS")
    assert _keymap(tmp_path).read_text() == service.KEYMAP
    assert "Action(reloadkeymaps)" in rec.builtins


def test_the_keymap_directory_is_created_when_absent(tmp_path):
    """special://profile/keymaps/ is KODI's directory for exactly this file and
    may legitimately not exist on a fresh profile, so unlike the shim targets it
    is created rather than skipped."""
    _boot(tmp_path, "TVOS")
    assert _keymap(tmp_path).is_file()


# --------------------------------------------------------------------------- #
# Everything that is not tvOS: strict no-op
# --------------------------------------------------------------------------- #
def test_nothing_is_written_on_android(tmp_path):
    """Fire TV and every other Android box must stay untouched.

    This is the test the owner's "will this break Fire OS" question rests on.
    Fire OS has a working _scproxy, so a shim there would shadow a real module,
    and its remote is not a Siri remote.
    """
    _boot(tmp_path, "ANDROID")
    assert _scproxy_files(tmp_path) == []
    assert not _keymap(tmp_path).exists()


@pytest.mark.parametrize("platform", ["ANDROID", "LINUX", "OSX", "WINDOWS", "IOS"])
def test_no_op_on_every_non_tvos_platform(tmp_path, platform):
    rec, _ = _boot(tmp_path, platform)
    assert _written_files(tmp_path) == [], (
        "off tvOS a third party's add-on directory must be left exactly as found"
    )
    assert rec.builtins == [], (
        "no builtin runs on any platform except the keymap reload on tvOS"
    )
    assert rec.translated == [], "off tvOS the service must not resolve any path"


def test_no_builtin_beyond_the_keymap_reload_ever_runs(tmp_path):
    """The regression guard against Weather.Refresh creeping back.

    1.0.x fired it ten seconds into every tvOS start and it never did anything.
    WeatherBuiltins.cpp:83 maps weather.refresh to SwitchLocation<0>, which sends
    GUI_MSG_MOVE_OFFSET to WINDOW_WEATHER (:36-43) rather than calling
    CWeatherManager::Refresh(). GUIWindowWeather.cpp:103-116 handles that message
    only when m_maxLocation > 0; the only assignment to m_maxLocation is in
    UpdateLocations() (:143), which returns immediately unless the Weather window
    is on screen (:132-134). At boot it never is. Adding it back would restore a
    ten second interpreter lifetime for a message Kodi drops.
    """
    rec, _ = _boot(tmp_path, "TVOS")
    assert rec.builtins == ["Action(reloadkeymaps)"]

    rec2, _ = _boot(tmp_path, "TVOS")
    assert rec2.builtins == [], "an unchanged start must execute no builtin at all"


def test_the_service_never_waits(tmp_path):
    """A boot service exits as soon as its files are on disk.

    1.0.x held an interpreter open for ten seconds on every tvOS start for the
    weather call above. fake_kodi deliberately provides NO xbmc.Monitor, so any
    reintroduced wait raises AttributeError here rather than passing quietly.
    """
    import xbmc

    _boot(tmp_path, "TVOS")
    assert not hasattr(xbmc, "Monitor")


def test_the_gate_is_actually_consulted(tmp_path):
    """Guards against the gate being removed rather than merely not firing."""
    rec, _ = _boot(tmp_path, "ANDROID")
    assert "System.Platform.TVOS" in rec.conditions


# --------------------------------------------------------------------------- #
# Isolation and reporting
# --------------------------------------------------------------------------- #
def test_the_shim_is_attempted_before_the_keymap(tmp_path):
    """Order is load-bearing: the shim is the one other add-ons can be racing.

    On a box where this add-on is installed mid session, every instruction in
    front of the shim write is time POV or Multi Weather can spend dying at
    import. The keymap is only read when the user next presses a button.
    """
    _, service = _boot(tmp_path, "TVOS")
    assert [label for label, _ in service.WRITES] == [
        "_scproxy shim",
        "Siri remote keymap",
    ]


def test_a_write_failure_never_kills_the_service(tmp_path):
    """A service that raises takes nothing else down with it.

    A directory where the file belongs is the cheapest way to make open(w) raise
    something the service did not anticipate, which is the point: the handler has
    to catch the class, not one expected errno.
    """
    _shim_dir(tmp_path).mkdir(parents=True, exist_ok=True)
    _scproxy(tmp_path).mkdir()

    rec, _ = _boot(tmp_path, "TVOS")
    assert any(level == fake_kodi.LOGWARNING for level, _ in rec.logs)
    assert _keymap(tmp_path).is_file(), "a shim failure must not cost the keymap"


def test_a_keymap_failure_never_costs_the_shim(tmp_path):
    """The other direction, so the isolation is proved both ways."""
    (tmp_path / "keymaps").write_text("this is a file, so makedirs must fail")
    rec, _ = _boot(tmp_path, "TVOS")
    assert any(level == fake_kodi.LOGWARNING for level, _ in rec.logs)
    assert len(_scproxy_files(tmp_path)) == len(MODULE_IDS)


def test_every_start_logs_one_summary_line_at_info(tmp_path):
    """A repair that only reports at debug level cannot be confirmed on a box.

    One line, not two. 1.0.x logged the shim separately because the weather wait
    delayed the summary by ten seconds and made its timestamp useless. With the
    wait gone the summary lands at the instant the writes do.
    """
    rec, _ = _boot(tmp_path, "TVOS")
    info = [m for level, m in rec.logs if level == fake_kodi.LOGINFO]
    assert len(info) == 1, "exactly one INFO line per start, got %r" % (info,)
    assert "tvOS start:" in info[0]
    assert "_scproxy" in info[0] and "keymap" in info[0]


def test_the_summary_reports_a_failure_rather_than_swallowing_it(tmp_path):
    _shim_dir(tmp_path).mkdir(parents=True, exist_ok=True)
    _scproxy(tmp_path).mkdir()
    rec, _ = _boot(tmp_path, "TVOS")
    summaries = [m for level, m in rec.logs if level == fake_kodi.LOGINFO]
    assert "FAILED" in summaries[-1]


def test_the_log_prefix_names_this_addon_and_no_skin(tmp_path):
    """The prefix is how a log line is traced back to its owner.

    It was "estuary.pov: " while the keymap lived in the skin, which would now
    send a reader to a skin that ships no Python at all.
    """
    rec, service = _boot(tmp_path, "TVOS")
    assert service.LOG_PREFIX == "tvos.fixes: "
    for _, message in rec.logs:
        assert message.startswith("tvos.fixes: ")
        assert "estuary" not in message


# --------------------------------------------------------------------------- #
# The packaged add-on
# --------------------------------------------------------------------------- #
def test_every_declared_asset_exists_on_disk():
    """A declared-but-missing asset 404s silently in Kodi's add-on browser.

    Nothing in repo/_tools/ validates assets: generate_repo.py, build_site.py and
    release.py contain no reference to icon, png, jpg or assets at all. So there
    is no gate anywhere between a typo here and a blank row on a box.

    Kodi 22 has no implicit icon.png fallback either. AddonInfoBuilder.cpp:432-471
    is the only place m_icon is set from an addon.xml, and the strings "icon.png"
    and "fanart.jpg" appear nowhere in that file, so the <assets> block is
    mandatory to have an icon at all.
    """
    text = (ADDON / "addon.xml").read_text(encoding="utf-8")
    assets = re.findall(
        r"<(icon|fanart|banner|clearlogo|screenshot)>([^<]+)</\1>", text
    )
    assert assets, "the add-on must declare at least an icon"
    for kind, rel in assets:
        assert (ADDON / rel).is_file(), "declared <%s> %s does not exist" % (kind, rel)


def test_the_icon_is_the_size_and_mode_this_repo_uses_for_services():
    """512x512 RGBA, the script/service convention (script.ezmaintenanceplusplus,
    repository.tony7bones). 256x256 RGB is the SKIN convention and this is not a
    skin. Checked without Pillow, straight out of the PNG IHDR chunk, so the test
    suite gains no dependency.
    """
    raw = (ADDON / "resources" / "icon.png").read_bytes()
    assert raw[:8] == b"\x89PNG\r\n\x1a\n"
    assert raw[12:16] == b"IHDR"
    width = int.from_bytes(raw[16:20], "big")
    height = int.from_bytes(raw[20:24], "big")
    colour_type = raw[25]
    assert (width, height) == (512, 512)
    assert colour_type == 6, "RGBA, so the rounded corners are transparent"


def test_the_addon_id_never_changes():
    """Kodi keys installs, the repository catalog and the hosted mirror on the id.

    The display name broadened at 1.1.0 when the keymap moved in, and the id
    deliberately did not follow it. Renaming the id would orphan every box that
    already has this installed, silently: the old add-on stays, the new one
    installs beside it, and both services write the same files.
    """
    text = (ADDON / "addon.xml").read_text(encoding="utf-8")
    assert 'id="service.tvos.pythonfix"' in text
