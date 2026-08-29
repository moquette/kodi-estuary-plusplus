"""The skin's boot service: one tvOS-only write, and NOTHING off tvOS.

The Fire OS no-op is the load-bearing test here. The owner asked directly whether
this change could affect his Fire TV boxes and the answer given was no, on the
strength of one System.Platform.TVOS gate. This file is what makes that answer
true rather than intended: delete the gate and test_keymap_not_written_on_android
fails.

The _scproxy shim USED to be written from here as well, in 1.2.2 through 1.2.5,
and its tests lived in this file. They now live in test_pythonfix_service.py
against service.tvos.pythonfix, and what is left behind here is
test_the_skin_no_longer_writes_the_shim, which fails the moment anyone puts it
back.
"""

from __future__ import annotations

import importlib
import re
import sys

import pytest

import fake_kodi
from conftest import ROOT


def _boot(tmp_path, platform):
    """One Kodi start on a box of the given platform. Returns (recorder, module)."""
    rec = fake_kodi.install(platform, tmp_path)
    sys.modules.pop("services", None)
    services = importlib.import_module("services")
    services.main()
    return rec, services


def _keymap(tmp_path):
    return tmp_path / "keymaps" / "t7b-siriremote.xml"


def _written_files(tmp_path):
    """Every file the service left anywhere under the fake profile."""
    return sorted(p for p in tmp_path.rglob("*") if p.is_file())


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


@pytest.mark.parametrize("platform", ["ANDROID", "LINUX", "OSX", "WINDOWS", "IOS"])
def test_no_op_on_every_non_tvos_platform(tmp_path, platform):
    rec, _ = _boot(tmp_path, platform)
    assert _written_files(tmp_path) == []
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


def test_every_start_logs_one_summary_line_at_info(tmp_path):
    """A repair that only reports at debug level cannot be confirmed on a box."""
    rec, _ = _boot(tmp_path, "TVOS")
    summaries = [m for level, m in rec.logs if level == fake_kodi.LOGINFO]
    assert len(summaries) == 1, "exactly one INFO line per start, got %r" % (summaries,)
    assert "keymap" in summaries[0]


def test_the_summary_reports_a_failure_rather_than_swallowing_it(tmp_path):
    blocked = tmp_path / "keymaps"
    blocked.write_text("this is a file, so makedirs must fail")
    rec, _ = _boot(tmp_path, "TVOS")
    summaries = [m for level, m in rec.logs if level == fake_kodi.LOGINFO]
    assert "FAILED" in summaries[0]


# --------------------------------------------------------------------------- #
# The shim has moved out, and must not come back
# --------------------------------------------------------------------------- #
def test_the_skin_no_longer_writes_the_shim(tmp_path):
    """The whole point of 1.2.6, asserted rather than remembered.

    A skin cannot fix a fresh install, because Kodi installs a parent's
    dependencies BEFORE the parent: on atv1 2026-08-29 POV was installed at
    07:42:31.754 and had already failed at 07:42:32.991, and this skin was not on
    disk until 07:42:33.108. Putting the write back here would restore that
    ordering bug while looking like a belt-and-braces improvement, so it fails
    here instead.
    """
    _boot(tmp_path, "TVOS")
    assert _written_files(tmp_path) == [_keymap(tmp_path)], (
        "the skin's service writes the keymap and nothing else; the _scproxy shim "
        "belongs to service.tvos.pythonfix"
    )


def test_the_skin_declares_the_shim_addon_before_the_addons_that_need_it():
    """Declaration order in addon.xml IS the fix. Measured, not assumed.

    Kodi installs sibling dependencies in the order the parent declares them, and
    starts a service add-on within milliseconds of installing it (measured on a
    clean Kodi 22 bench: "Found addon" and "CServiceAddonManager: starting" in the
    same millisecond, the script's own first line 4 ms later). So the shim add-on
    has to be declared ahead of plugin.video.pov, and POV last, or the ordering
    that makes a fresh install work quietly goes away with no test failing.
    """
    text = (ROOT / "skin.estuary.pov" / "addon.xml").read_text(encoding="utf-8")
    order = re.findall(r'<import addon="([^"]+)"', text)
    assert "service.tvos.pythonfix" in order, (
        "the shim add-on must be a declared dependency, or Kodi never installs it"
    )
    assert order.index("service.tvos.pythonfix") < order.index("plugin.video.pov"), (
        "the shim must install before POV, or POV starts and dies before it exists"
    )
    assert order[-1] == "plugin.video.pov", (
        "POV goes last so the other dependencies' download time separates it from "
        "the shim add-on's service start"
    )
