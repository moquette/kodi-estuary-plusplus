"""service.tvos.pythonfix: the _scproxy shim, and NOTHING off tvOS.

Every test here moved out of test_services_keymap.py with the code it covers,
and the two Fire OS no-op tests are the load-bearing ones: this add-on writes
into a directory belonging to a third party, so on any box that is not tvOS that
directory must come out of the boot byte-for-byte untouched.

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

# The dependency whose library directory carries the shim. Spelled out here
# rather than imported from service.py so the test cannot silently follow the
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
    sys.modules.pop("service", None)
    service = importlib.import_module("service")
    service.main()
    return rec, service


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
# tvOS: the shim is written, and written where Kodi will find it
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
    rec, service = _boot(tmp_path, "TVOS")
    assert service.SHIM_DIR_PATH == "special://home/addons/%s/lib/" % REQUESTS_ID
    assert service.SHIM_DIR_PATH in rec.translated, (
        "the directory must be resolved through Kodi, not built with expanduser"
    )


def test_the_addon_declares_the_dependency_it_writes_into():
    """The declaration is what guarantees the directory exists when this runs.

    Kodi installs a dependency's own dependencies before the dependency itself,
    so declaring script.module.requests here is not decoration: it is what makes
    write_scproxy's "the directory is already there" assumption true on a fresh
    install. Dropping the import line would leave a service that silently skips
    on exactly the box it exists for.
    """
    text = (ROOT / "service.tvos.pythonfix" / "addon.xml").read_text(encoding="utf-8")
    assert re.search(r'<import addon="%s"' % re.escape(REQUESTS_ID), text), (
        "service.tvos.pythonfix must declare the add-on whose directory it writes into"
    )


def test_the_shim_is_not_written_when_requests_is_absent(tmp_path):
    """Absent is a reportable state, not a failure, and must not be papered over.

    script.module.requests is a declared dependency, so Kodi installs it first and
    this should not happen. If it somehow does, then nothing on the box depends on
    it and the shim would help nobody. Creating the directory anyway would leave
    addons/script.module.requests/ with no addon.xml in it for Kodi's add-on
    scanner to find, and for a later dependency install to land on top of.
    """
    rec, _ = _boot(tmp_path, "TVOS", requests_installed=False)
    assert _scproxy_files(tmp_path) == []
    assert not _addons(tmp_path).exists(), (
        "the service must never create an add-on directory it does not own"
    )
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

    This is also the self-heal case that matters in the field: an upstream update
    to script.module.requests replaces its lib directory and takes the shim with
    it, and the next start must put it back rather than silently leaving every
    networked add-on broken again.
    """
    _, service = _boot(tmp_path, "TVOS")
    path = _scproxy(tmp_path)
    path.write_text("# stale, and a different length from the real payload\n")

    _boot(tmp_path, "TVOS")
    assert path.read_text() == service.SCPROXY


def test_a_deleted_shim_comes_back_on_the_next_start(tmp_path):
    """The other half of self-heal: gone entirely, not merely stale."""
    _, service = _boot(tmp_path, "TVOS")
    _scproxy(tmp_path).unlink()

    _boot(tmp_path, "TVOS")
    assert _scproxy(tmp_path).read_text() == service.SCPROXY


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
# Everything that is not tvOS: strict no-op
# --------------------------------------------------------------------------- #
def test_scproxy_not_written_on_android(tmp_path):
    """Fire OS has a working _scproxy, so a shim there would shadow a real module.

    It goes into an add-on this one does not own, so on any box that is not tvOS
    that directory must come out of the boot byte-for-byte untouched.
    """
    _boot(tmp_path, "ANDROID")
    assert _scproxy_files(tmp_path) == [], (
        "the _scproxy shim is tvOS-only; Fire OS boxes must stay untouched"
    )


@pytest.mark.parametrize("platform", ["ANDROID", "LINUX", "OSX", "WINDOWS", "IOS"])
def test_no_op_on_every_non_tvos_platform(tmp_path, platform):
    rec, _ = _boot(tmp_path, platform)
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
    assert "Weather.Refresh" in rec.builtins, "a shim failure must not cost the weather"


# --------------------------------------------------------------------------- #
# Order, and the race it is shortening
# --------------------------------------------------------------------------- #
def test_the_shim_is_written_before_anything_else(tmp_path):
    """Order is load-bearing: the shim is the one other add-ons are racing.

    This service is dispatched asynchronously right after Kodi installs this
    add-on, and POV's service starts within milliseconds of POV being installed
    (measured: 1 ms on a clean Kodi 22 bench, 130 ms on atv1). Every instruction
    between the interpreter starting and the write landing is time POV or Multi
    Weather can spend dying at import, so nothing may be put in front of it.
    """
    _, service = _boot(tmp_path, "TVOS")
    labels = [row[0] for row in service.WRITES]
    assert labels[0] == "_scproxy shim"


def test_the_shim_is_written_before_the_ten_second_weather_wait(tmp_path):
    """The wait must never be able to delay the write, in any refactor."""
    _shim_dir(tmp_path).mkdir(parents=True, exist_ok=True)
    rec = fake_kodi.install("TVOS", tmp_path)
    rec.aborting = True
    sys.modules.pop("service", None)
    service = importlib.import_module("service")
    service.main()
    assert "Weather.Refresh" not in rec.builtins
    assert _scproxy_files(tmp_path), "the shim is still written before the wait"


# --------------------------------------------------------------------------- #
# The weather re-fetch
# --------------------------------------------------------------------------- #
def test_weather_is_refreshed_on_every_tvos_start(tmp_path):
    """Every start, not just the one that writes the shim.

    weather.multi declares script.module.requests (measured on atv1), so on any
    start where the shim is not already on disk, Kodi's own startup fetch has
    already died on the missing _scproxy. The start after an update to
    script.module.requests is exactly that case, because the update takes the
    shim with it.
    """
    rec, _ = _boot(tmp_path, "TVOS")
    assert "Weather.Refresh" in rec.builtins

    rec2, _ = _boot(tmp_path, "TVOS")
    assert "Weather.Refresh" in rec2.builtins, "the weather still needs re-fetching"


def test_weather_is_not_refreshed_off_tvos(tmp_path):
    """Fire OS has a working Python, so its startup fetch never failed."""
    for platform in ("ANDROID", "LINUX", "OSX", "WINDOWS", "IOS"):
        rec, _ = _boot(tmp_path, platform)
        assert "Weather.Refresh" not in rec.builtins


def test_the_weather_refresh_names_no_addon(tmp_path):
    """It must stay a Kodi builtin.

    RunAddon/RunScript against a named weather add-on would make this add-on
    depend on one particular weather provider being installed, which is the
    cross-artifact coupling this project forbids. Weather.Refresh works with
    whatever provider the box is set to, and does nothing at all if none is.
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
    rec, service = _boot(tmp_path, "TVOS")
    assert rec.waits == [service.WEATHER_RETRY_SECONDS]
    assert service.WEATHER_RETRY_SECONDS >= 5


# --------------------------------------------------------------------------- #
# Reporting
# --------------------------------------------------------------------------- #
def test_the_shim_result_is_logged_before_the_weather_wait(tmp_path):
    """The shim gets its own INFO line, at the instant it lands.

    The summary cannot be emitted until refresh_weather's ten second wait is
    over, which timestamps the shim ten seconds late. The one question anybody
    will ever ask this log is whether the shim beat POV's service start, and the
    measured margin is between 0.455 s and 3.9 s, so a ten second error makes the
    log useless for it. Three of five bench runs lost their evidence to exactly
    that before this line existed.
    """
    rec, _ = _boot(tmp_path, "TVOS")
    info = [m for level, m in rec.logs if level == fake_kodi.LOGINFO]
    assert len(info) == 2, "the shim line then the summary, got %r" % (info,)
    assert "_scproxy" in info[0]
    assert "weather" not in info[0], (
        "the first line must land before the weather wait, not after it"
    )
    assert "tvOS start:" in info[1]
    assert "_scproxy" in info[1] and "weather" in info[1]


def test_the_summary_reports_a_failure_rather_than_swallowing_it(tmp_path):
    _shim_dir(tmp_path).mkdir(parents=True, exist_ok=True)
    _scproxy(tmp_path).mkdir()
    rec, _ = _boot(tmp_path, "TVOS")
    summaries = [m for level, m in rec.logs if level == fake_kodi.LOGINFO]
    assert "FAILED" in summaries[-1]
