"""The skin's boot service: two tvOS-only writes, and NOTHING off tvOS.

The Fire OS no-op is the load-bearing test here, and it now has to cover BOTH
writes. The owner asked directly whether this change could affect his Fire TV
boxes and the answer given was no, on the strength of one System.Platform.TVOS
gate. This file is what makes that answer true rather than intended: delete the
gate and test_keymap_not_written_on_android and test_scproxy_not_written_on_android
both fail.
"""

from __future__ import annotations

import importlib
import sys
import urllib.request

import pytest

import fake_kodi

# The dependency whose library directory carries the shim. Spelled out here
# rather than imported from services.py so the test cannot silently follow the
# code to a different add-on: this id is the whole reason the fix reaches POV,
# Multi Weather and EZ Maintenance++, all three of which declare it.
REQUESTS_ID = "script.module.requests"


def _boot(tmp_path, platform, requests_installed=True):
    """One Kodi start on a box of the given platform. Returns (recorder, module).

    requests_installed models the only realistic variation: the service writes
    into an add-on it does not own, and that add-on may simply not be there.
    """
    if requests_installed:
        _shim_dir(tmp_path).mkdir(parents=True, exist_ok=True)
    rec = fake_kodi.install(platform, tmp_path)
    sys.modules.pop("services", None)
    services = importlib.import_module("services")
    services.main()
    return rec, services


def _keymap(tmp_path):
    return tmp_path / "keymaps" / "t7b-siriremote.xml"


def _addons(tmp_path):
    """Where fake_kodi maps special://home/addons/ to."""
    return tmp_path / "home" / "addons"


def _shim_dir(tmp_path):
    return _addons(tmp_path) / REQUESTS_ID / "lib"


def _scproxy(tmp_path):
    return _shim_dir(tmp_path) / "_scproxy.py"


def _scproxy_files(tmp_path):
    """Every _scproxy.py written anywhere under special://home, found by search.

    A search rather than a single stat, so that a shim written to the WRONG
    directory shows up as a failure here instead of passing as an absence.
    """
    home = tmp_path / "home"
    return sorted(home.rglob("_scproxy.py")) if home.exists() else []


# --------------------------------------------------------------------------- #
# tvOS: the file is written, and written correctly
# --------------------------------------------------------------------------- #
def test_keymap_written_on_tvos(tmp_path):
    rec, _ = _boot(tmp_path, "TVOS")
    path = _keymap(tmp_path)
    assert path.is_file(), "tvOS must get the keymap"
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


def test_second_boot_is_idempotent_and_does_not_reload(tmp_path):
    """Idempotent BY CONTENT: no rewrite, and no keymap reload, when unchanged."""
    _boot(tmp_path, "TVOS")
    body = _keymap(tmp_path).read_text()
    rec2, _ = _boot(tmp_path, "TVOS")
    assert _keymap(tmp_path).read_text() == body
    assert "Action(reloadkeymaps)" not in rec2.builtins


def test_changed_payload_is_rewritten_and_reloads(tmp_path):
    """A box carrying an older payload gets the new one, and keymaps reload."""
    _boot(tmp_path, "TVOS")
    _keymap(tmp_path).write_text("<keymap><!-- stale --></keymap>\n")
    rec, services = _boot(tmp_path, "TVOS")
    assert _keymap(tmp_path).read_text() == services.KEYMAP
    assert "Action(reloadkeymaps)" in rec.builtins


# --------------------------------------------------------------------------- #
# Everything that is not tvOS: strict no-op
# --------------------------------------------------------------------------- #
def test_keymap_not_written_on_android(tmp_path):
    """Fire TV and every other Android box must stay untouched.

    Ported from estuary7/tests/test_services_selfheal.py. This is the test the
    owner's "will this break Fire OS" question rests on.
    """
    rec, _ = _boot(tmp_path, "ANDROID")
    assert not _keymap(tmp_path).exists(), (
        "the Siri keymap is tvOS-only; Fire OS boxes must stay untouched"
    )
    assert rec.builtins == []


def test_scproxy_not_written_on_android(tmp_path):
    """The other half of the same promise, and the newer half.

    Fire OS has a working _scproxy, so a shim there would be a module shadowing
    a real one for no reason. It goes into an add-on this skin does not own, so
    on any box that is not tvOS that directory must come out of the boot
    byte-for-byte untouched.
    """
    _boot(tmp_path, "ANDROID")
    assert _scproxy_files(tmp_path) == [], (
        "the _scproxy shim is tvOS-only; Fire OS boxes must stay untouched"
    )


@pytest.mark.parametrize("platform", ["ANDROID", "LINUX", "OSX", "WINDOWS", "IOS"])
def test_no_op_on_every_non_tvos_platform(tmp_path, platform):
    rec, _ = _boot(tmp_path, platform)
    assert not _keymap(tmp_path).exists()
    assert _scproxy_files(tmp_path) == []
    assert list(_shim_dir(tmp_path).iterdir()) == [], (
        "off tvOS a third party's add-on directory must be left exactly as found"
    )
    assert rec.builtins == []
    assert rec.translated == [], "off tvOS the service must not resolve any path"


def test_the_gate_is_actually_consulted(tmp_path):
    """Guards against the gate being removed rather than merely not firing."""
    rec, _ = _boot(tmp_path, "ANDROID")
    assert "System.Platform.TVOS" in rec.conditions


def test_a_write_failure_never_kills_the_boot_service(tmp_path):
    """A service that raises takes nothing else down with it."""
    blocked = tmp_path / "keymaps"
    blocked.write_text("this is a file, so makedirs must fail")
    rec, _ = _boot(tmp_path, "TVOS")
    assert any(level == fake_kodi.LOGWARNING for level, _ in rec.logs)


# --------------------------------------------------------------------------- #
# tvOS: the _scproxy shim
# --------------------------------------------------------------------------- #
def test_scproxy_written_on_tvos(tmp_path):
    """One file, in script.module.requests' library directory, and nowhere else."""
    _boot(tmp_path, "TVOS")
    assert _scproxy_files(tmp_path) == [_scproxy(tmp_path)]


def test_the_shim_lands_on_the_path_kodi_builds_for_a_dependent_addon(tmp_path):
    """Agreement with Kodi's dependency resolution, not with ourselves.

    The shim is useless one directory away from a path entry, and that failure is
    silent: no error, no log line, just add-ons that carry on dying at import. So
    the shape is asserted rather than left to a comment. PythonInvoker builds an
    add-on's sys.path from its declared dependencies and recurses through them
    (PythonInvoker.cpp:203-228, the walk at :709-727), and each dependency
    contributes the directory named by its own library= attribute.

    MEASURED on atv1 2026-08-28 by reading the installed addon.xml files:
    plugin.video.pov, weather.multi and script.openweathermap.maps all declare
    script.module.requests, and script.module.requests declares library="lib".
    """
    rec, services = _boot(tmp_path, "TVOS")
    assert services.SHIM_DIR_PATH == "special://home/addons/%s/lib/" % REQUESTS_ID
    assert services.SHIM_DIR_PATH in rec.translated, (
        "the directory must be resolved through Kodi, not built with expanduser"
    )


def test_the_shim_is_not_written_when_requests_is_absent(tmp_path):
    """Absent is a valid state, not a failure, and must not be papered over.

    If script.module.requests is not installed then nothing on the box depends
    on it and the shim would help nobody. Creating the directory anyway would
    leave addons/script.module.requests/ with no addon.xml in it for Kodi's
    add-on scanner to find, and for a later dependency install to land on top
    of. So the write is skipped, the boot carries on, and the keymap still gets
    written.
    """
    rec, _ = _boot(tmp_path, "TVOS", requests_installed=False)
    assert _scproxy_files(tmp_path) == []
    assert not _addons(tmp_path).exists(), (
        "the service must never create an add-on directory it does not own"
    )
    assert _keymap(tmp_path).is_file(), "the keymap does not depend on requests"
    assert not any(level == fake_kodi.LOGWARNING for level, _ in rec.logs), (
        "a missing optional target is not a warning"
    )


def test_scproxy_second_boot_is_idempotent_by_content(tmp_path):
    _boot(tmp_path, "TVOS")
    path = _scproxy(tmp_path)
    stamp = path.stat().st_mtime_ns
    body = path.read_text()

    _boot(tmp_path, "TVOS")
    assert path.read_text() == body
    assert path.stat().st_mtime_ns == stamp, "unchanged content must not be rewritten"


def test_changed_scproxy_payload_is_rewritten(tmp_path):
    """A box carrying an older shim gets the new one.

    This is also the self-heal case that matters in the field: an upstream
    update to script.module.requests replaces its lib directory and takes the
    shim with it, and the next start must put it back rather than silently
    leaving every networked add-on broken again.
    """
    _, services = _boot(tmp_path, "TVOS")
    path = _scproxy(tmp_path)
    path.write_text("# stale, and a different length from the real payload\n")

    _boot(tmp_path, "TVOS")
    assert path.read_text() == services.SCPROXY


def test_a_deleted_shim_comes_back_on_the_next_start(tmp_path):
    """The other half of self-heal: gone entirely, not merely stale."""
    _, services = _boot(tmp_path, "TVOS")
    _scproxy(tmp_path).unlink()

    _boot(tmp_path, "TVOS")
    assert _scproxy(tmp_path).read_text() == services.SCPROXY


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
# The two writes are independent
# --------------------------------------------------------------------------- #
def test_a_failing_scproxy_write_still_leaves_the_keymap_written(tmp_path):
    """One broken write must not cost the other, in either direction.

    A directory where the file belongs is the cheapest way to make open(w) raise
    something the service did not anticipate, which is the point: the handler has
    to catch the class, not one expected errno.
    """
    _shim_dir(tmp_path).mkdir(parents=True, exist_ok=True)
    _scproxy(tmp_path).mkdir()

    rec, _ = _boot(tmp_path, "TVOS")
    assert _keymap(tmp_path).is_file(), "the keymap must survive a shim failure"
    assert any(level == fake_kodi.LOGWARNING for level, _ in rec.logs)


def test_a_failing_keymap_write_still_leaves_the_scproxy_shim_written(tmp_path):
    blocked = tmp_path / "keymaps"
    blocked.write_text("this is a file, so makedirs must fail")

    rec, _ = _boot(tmp_path, "TVOS")
    assert _scproxy_files(tmp_path) == [_scproxy(tmp_path)], (
        "the shim must survive a keymap failure"
    )
    assert any(level == fake_kodi.LOGWARNING for level, _ in rec.logs)


def test_the_shim_is_written_before_the_keymap(tmp_path):
    """Order is load-bearing: the shim is the one other add-ons are racing.

    Kodi dispatches services in add-on id order but runs them on separate threads
    (Service.cpp:60-67 with ExecuteAsync), so execution order is a coin flip and
    was measured inverting in 3 of 8 bench runs. The race cannot be won, only
    shortened, and putting the keymap first would lengthen it for no reason.
    """
    _, services = _boot(tmp_path, "TVOS")
    labels = [label for label, _ in services.WRITES]
    assert labels.index("_scproxy shim") < labels.index("keymap")


# --------------------------------------------------------------------------- #
# The weather re-fetch
# --------------------------------------------------------------------------- #
def test_weather_is_refreshed_on_every_tvos_start(tmp_path):
    """Every start, not just the one that writes the shim.

    weather.multi declares script.module.requests (measured on atv1), so on the
    boot that first writes the shim Kodi's own startup fetch has already died on
    the missing _scproxy. A refresh conditional on the file having changed would
    fix the weather exactly once and then never again, which is the failure this
    test exists to prevent.
    """
    rec, _ = _boot(tmp_path, "TVOS")
    assert "Weather.Refresh" in rec.builtins

    rec2, _ = _boot(tmp_path, "TVOS")
    assert "Action(reloadkeymaps)" not in rec2.builtins, "nothing changed, so no reload"
    assert "Weather.Refresh" in rec2.builtins, "but the weather still needs re-fetching"


def test_weather_is_not_refreshed_off_tvos(tmp_path):
    """Fire OS has a working Python, so its startup fetch never failed."""
    for platform in ("ANDROID", "LINUX", "OSX", "WINDOWS", "IOS"):
        rec, _ = _boot(tmp_path, platform)
        assert "Weather.Refresh" not in rec.builtins


def test_the_weather_refresh_names_no_addon(tmp_path):
    """It must stay a Kodi builtin.

    RunAddon/RunScript against a named weather add-on would make this skin depend
    on one particular add-on being installed, which is the cross-artifact coupling
    the root CLAUDE.md forbids. Weather.Refresh works with whatever provider the
    box is set to, and does nothing at all if none is.
    """
    rec, _ = _boot(tmp_path, "TVOS")
    for command in rec.builtins:
        assert not command.startswith(("RunAddon", "RunScript", "RunPlugin"))


def test_the_weather_refresh_waits_for_kodis_own_fetch_to_finish(tmp_path):
    """Firing immediately is a no-op, so the wait is part of the fix.

    Measured on atv1: Kodi's startup fetch ran 05:14:33.391 to 05:14:34.895 and a
    Weather.Refresh fired 100 ms in was silently dropped, because Kodi will not
    queue a second weather job over a running one.
    """
    rec, services = _boot(tmp_path, "TVOS")
    assert rec.waits == [services.WEATHER_RETRY_SECONDS]
    assert services.WEATHER_RETRY_SECONDS >= 5


def test_a_shutdown_inside_the_wait_skips_the_refresh(tmp_path):
    """A boot service must not hold Kodi open, and must not act after abort."""
    _shim_dir(tmp_path).mkdir(parents=True, exist_ok=True)
    rec = fake_kodi.install("TVOS", tmp_path)
    rec.aborting = True
    sys.modules.pop("services", None)
    services = importlib.import_module("services")
    services.main()
    assert "Weather.Refresh" not in rec.builtins
    assert _scproxy_files(tmp_path), "the shim is still written before the wait"


def test_every_start_logs_one_summary_line_at_info(tmp_path):
    """A repair that only reports at debug level cannot be confirmed on a box."""
    rec, _ = _boot(tmp_path, "TVOS")
    summaries = [m for level, m in rec.logs if level == fake_kodi.LOGINFO]
    assert len(summaries) == 1, "exactly one INFO line per start, got %r" % (summaries,)
    assert "_scproxy" in summaries[0] and "keymap" in summaries[0]
    assert "weather" in summaries[0]


def test_the_summary_reports_a_failure_rather_than_swallowing_it(tmp_path):
    blocked = tmp_path / "keymaps"
    blocked.write_text("this is a file, so makedirs must fail")
    rec, _ = _boot(tmp_path, "TVOS")
    summaries = [m for level, m in rec.logs if level == fake_kodi.LOGINFO]
    assert "FAILED" in summaries[0]
