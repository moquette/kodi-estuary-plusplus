"""The skin's boot service: writes the Siri keymap on tvOS, NOTHING elsewhere.

The Fire OS no-op is the load-bearing test here. The owner asked directly whether
this change could affect his Fire TV boxes and the answer given was no, on the
strength of the System.Platform.TVOS gate. This file is what makes that answer
true rather than intended: delete the gate and test_keymap_not_written_on_android
fails.
"""

from __future__ import annotations

import importlib
import pathlib
import sys

import pytest

import fake_kodi


def _boot(tmp_path, platform):
    """One Kodi start on a box of the given platform. Returns (recorder, module)."""
    rec = fake_kodi.install(platform, tmp_path)
    sys.modules.pop("services", None)
    services = importlib.import_module("services")
    services.main()
    return rec, services


def _keymap(tmp_path):
    return tmp_path / "keymaps" / "t7b-siriremote.xml"


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
    assert not _keymap(tmp_path).exists()
    assert rec.builtins == []


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
