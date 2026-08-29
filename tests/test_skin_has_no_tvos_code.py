"""skin.estuary.pov ships NO tvOS code, no Python, and no service. Asserted.

This is the file that makes "tvOS is somebody else's problem" a property of the
build rather than an intention. It replaces test_services_keymap.py, whose
payload moved into service.tvos.pythonfix at skin 1.3.0.

The three-release history, because the easy mistake is to add one of these back
and it looks like an improvement every time:

  1.2.2  the skin's boot service wrote BOTH the _scproxy shim and the Siri
         remote keymap.
  1.2.7  the shim moved out into service.tvos.pythonfix, which the skin then
         declared as a hard <import>. That fixed the ordering and shipped a
         tvOS-only workaround to every Fire TV, Android, Windows, Linux and
         macOS box that installed the skin.
  1.2.8  the <import> went. The keymap stayed.
  1.3.0  the keymap went too, and with it scripts/, the service extension and
         the xbmc.python declaration that existed only to support them.

tvOS is under 1% of Kodi installs. It does not get to shape a skin that runs on
five other platforms, and a Siri remote belongs to the box rather than to
whichever skin happens to be selected.
"""

from __future__ import annotations

import re

from conftest import ROOT

SKIN = ROOT / "skin.estuary.pov"
ADDON_XML = (SKIN / "addon.xml").read_text(encoding="utf-8")


def test_the_skin_ships_no_python_at_all():
    """No scripts directory, no .py anywhere in the packaged tree.

    A search rather than a check for the one file that used to be there, so a
    differently named script cannot pass as an absence.
    """
    assert not (SKIN / "scripts").exists(), "scripts/ was deleted at 1.3.0"
    assert [p for p in SKIN.rglob("*.py") if "__pycache__" not in p.parts] == []


def test_the_skin_declares_no_service_extension():
    """A service extension is the only way a skin can run code at startup.

    Without this line the skin cannot write a keymap, cannot write a shim and
    cannot run on boot at all, whatever anybody adds to the tree.
    """
    points = re.findall(r"<extension\s+point=\"([^\"]+)\"", ADDON_XML)
    assert "xbmc.service" not in points
    assert points == ["xbmc.gui.skin", "xbmc.addon.metadata"]


def test_the_skin_does_not_declare_the_python_api():
    """It was declared only for the boot service and went with it.

    Leaving it would be harmless to Kodi and misleading to a reader, and it is
    the loose thread somebody pulls when adding a script back: an already
    declared api makes the addition look free.
    """
    imports = re.findall(r'<import addon="([^"]+)"', ADDON_XML)
    assert "xbmc.python" not in imports


def test_the_skin_does_not_declare_the_tvos_addon():
    """The 1.2.8 decoupling, asserted rather than remembered.

    Re-adding the import is the easy mistake, because it reads like making a
    fresh Apple TV install "just work". Three reasons it is still wrong, all
    measured:

    1. As a sibling dependency the ordering was won by FIFO position on the
       Python invoker queue, with a margin of 7 to 12 ms. Installed deliberately
       first there is no ordering to win at all.
    2. The add-on's own disclaimer tells the user to delete it once Kodi ships
       an Apple TV build that no longer needs it. A hard import here makes that
       instruction unfollowable.
    3. When upstream fixes _scproxy, decoupled means a user deletes an add-on.
       Coupled means we cut a skin release.

    An existing box does NOT lose the add-on on update. MEASURED on a clean
    Kodi 22.0-BETA1 (21.90.801) bench: RemoveOrphanedDepsRecursively has exactly
    two callers, CAddonUnInstallJob::DoWork (AddonInstaller.cpp:1308) and the
    "remove orphaned dependencies" settings action (AddonSystemSettings.cpp:74),
    and neither runs on an update. Belt and braces, CAddonMgr::IsOrphaned
    (AddonManager.cpp:344-349) returns false for anything whose MainType is not
    in dependencyTypes, which is {SCRAPER_LIBRARY, SCRIPT_LIBRARY, SCRIPT_MODULE}
    (AddonType.cpp:20-24). xbmc.service maps to AddonType::SERVICE
    (AddonInfo.cpp:76), so this add-on can never be classified orphaned by
    either path.
    """
    imports = re.findall(r'<import addon="([^"]+)"', ADDON_XML)
    assert "service.tvos.pythonfix" not in imports, (
        "the tvOS add-on is STANDALONE as of 1.2.8; importing it here puts a "
        "tvOS-only workaround on every non-tvOS box that installs this skin"
    )
    assert imports[-1] == "plugin.video.pov", (
        "POV stays last. Nothing depends on that any more, but moving it is a "
        "behaviour change for no gain"
    )


def test_no_file_in_the_skin_mentions_tvos_or_the_siri_remote():
    """The catch-all, and the one that would fail first on a well meant revert.

    The skin's own XML has no business naming a platform it does not target. A
    hit here means either a tvOS behaviour crept back in, or a comment is
    describing code that no longer exists, and both are worth failing on.
    """
    hay = []
    for path in SKIN.rglob("*"):
        if not path.is_file() or path.suffix.lower() not in (".xml", ".txt", ".po"):
            continue
        if path.name == "changelog.txt" or path == SKIN / "addon.xml":
            # Both legitimately describe the move, in prose, for users.
            continue
        text = path.read_text(encoding="utf-8", errors="ignore")
        for needle in ("SiriRemote", "t7b-siriremote", "_scproxy", "System.Platform.TVOS"):
            if needle in text:
                hay.append("%s: %s" % (path.relative_to(SKIN), needle))
    assert hay == [], "tvOS code or claims found in the skin: %r" % (hay,)
