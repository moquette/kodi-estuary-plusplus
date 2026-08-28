"""skin.estuary.pov boot service: two tvOS-only repairs, written on every start.

1. The _scproxy shim, which is what makes Python add-ons work at all on tvOS.
2. The Siri remote keymap, ported from skin.estuary7's scripts/services.py,
   which has shipped the same payload fleet-wide since 2026-07-15.

Both are things Kodi will only read out of a directory a skin cannot ship into,
so a boot service is the only mechanism available. Both are strict no-ops off
tvOS, gated on xbmc.getCondVisibility('System.Platform.TVOS'), and that gate is
enforced by tests rather than merely intended: Fire TV, Android and desktop boxes
must get neither file.

Both writes are idempotent BY CONTENT: the file is read back and rewritten only
if its bytes differ, so a normal start does no disk IO at all.

The shim is written FIRST, deliberately, and the reason is a race that CANNOT be
won outright. Kodi DISPATCHES service add-ons in add-on id order (Service.cpp:60-67
iterates m_installedAddons, which AddonManager.h:38 declares as a std::map keyed
by id) but it dispatches them with ExecuteAsync, one thread each, so EXECUTION
order is decided by the scheduler. Measured on a clean Kodi 22 bench over eight
runs with two probe services bracketing alphabetically: dispatch order was
alphabetical 8 times out of 8, execution order was INVERTED 3 times out of 8, on
margins of 0.1 to 0.9 ms. So there is no start order to rely on, and on the one
start where the shim does not yet exist, an add-on that loses that coin flip
still fails at import.

That costs exactly one Kodi start, and only ever the FIRST one after this skin is
installed. Everything invoked later in the same session is already fine, because
Kodi rebuilds an add-on's sys.path from its declared dependencies on EVERY
invocation (PythonInvoker.cpp:203-228), so the next add-on to start picks the
file up with no restart needed. Add-on DOWNLOADS are unaffected either way,
since Kodi fetches those in C++ over CCurlFile; it is only add-on EXECUTION that
needs this file.
"""

import os

import xbmc
import xbmcvfs

LOG_PREFIX = "estuary.pov: "

# Kodi's shipped system/keymaps/customcontroller.SiriRemote.xml makes four
# choices the owner does not want. See the Apple TV playbook section 15 for the
# full stock-versus-ours table. In short:
#
#   FullscreenVideo + FullscreenLiveTV, button 6 (back): stock Stop -> Back.
#     Back killed playback outright; now it leaves fullscreen and keeps playing,
#     which is what the Fire TV remote does.
#   FullscreenLiveTV only, button 5 (select): stock Pause -> OSD. Pause is a
#     dead button on live streams with no timeshift.
#   Home, button 6 (back): stock ActivateWindow(FavouritesBrowser) -> FullScreen.
#     That stock binding is the Favourites window that will not go away when you
#     exit a video. FullScreen is a no-op when nothing is playing.
#   global, button 21 (double play/pause): stock noop -> FullScreen, so there is
#     a way back INTO fullscreen once back has left it. Without this, changing
#     back away from Stop would strand playback with no route to the video.
#
# Written with plain open() on purpose. Per playbook section 8 the only filename
# prefix excluded from NSUserDefaults vectoring is customcontroller.SiriRemote*,
# and t7b-siriremote.xml does NOT carry that prefix, so it IS vectoring-eligible.
# It stays a POSIX file only because the write API here is open() rather than
# xbmcvfs. Do NOT "fix" this to use xbmcvfs: that would spend the 512 KB key
# budget on a file Kodi's keymap loader reads happily from disk, and would leave
# a durable key shadowing the file after a restore.
KEYMAP_NAME = "t7b-siriremote.xml"

KEYMAP = "\n".join(
    [
        '<?xml version="1.0" encoding="UTF-8"?>',
        "<!-- Written by skin.estuary.pov (boot service). Back exits fullscreen",
        "     video with playback continuing, double play/pause returns to it, and",
        "     back at Home no longer opens the Favourites browser. Delete this file",
        "     and run Action(reloadkeymaps) to revert to stock behaviour. -->",
        "<keymap>",
        "  <FullscreenVideo>",
        '    <customcontroller name="SiriRemote">',
        '      <button id="6">Back</button>',
        "    </customcontroller>",
        "  </FullscreenVideo>",
        "  <FullscreenLiveTV>",
        "    <!-- Kodi consults the live-TV section first when PVR content plays and",
        "         falls back to FullscreenVideo, so both are written. select opens",
        "         the OSD on live TV only; movies and shows keep select=Pause. -->",
        '    <customcontroller name="SiriRemote">',
        '      <button id="5">OSD</button>',
        '      <button id="6">Back</button>',
        "    </customcontroller>",
        "  </FullscreenLiveTV>",
        "  <Home>",
        "    <!-- stock opens the Favourites browser here, which is the window that",
        "         will not go away on exiting a video. FullScreen is a no-op when",
        "         nothing is playing. -->",
        '    <customcontroller name="SiriRemote">',
        '      <button id="6">FullScreen</button>',
        "    </customcontroller>",
        "  </Home>",
        "  <global>",
        "    <!-- stock maps double play/pause to noop, which leaves no way back",
        "         into fullscreen once back has exited it. Stop stays on hold",
        "         play/pause (button 20) and in the OSD. -->",
        '    <customcontroller name="SiriRemote">',
        '      <button id="21">FullScreen</button>',
        "    </customcontroller>",
        "  </global>",
        "</keymap>",
        "",
    ]
)


def _log(message, level=xbmc.LOGINFO):
    xbmc.log(LOG_PREFIX + message, level=level)


# --------------------------------------------------------------------------- #
# 1. The _scproxy shim
# --------------------------------------------------------------------------- #
# Kodi's tvOS build disables CPython's _scproxy extension while CPython carries
# on reporting sys.platform == "darwin", so Lib/urllib/request.py:2035 imports a
# module that is not there, at MODULE TOP LEVEL. Anything that touches requests
# or urllib therefore dies at import on every tvOS box: POV, Multi Weather, and
# EZ Maintenance++'s Dropbox and pastebin paths, none of which are ours to patch.
#
# Upstream cause, measured against the box's own build commit 77395cf42e:
# tools/depends/target/python3/Makefile:81-83 sets py_cv_module__scproxy=n/a for
# all darwin_embedded, and the compensating 16-ios-platform.patch that stops
# CPython reporting "darwin" is applied only under findstring iphone, while
# configure.ac:490-493 maps tvos to appletvos. iOS gets both halves; tvOS gets
# only the removal.
#
# DELETE THIS the first time a tvOS Kodi build imports urllib.request without
# _scproxy. It is a workaround for someone else's defect, not a feature, and
# unlike the per-user site directory this location is at sys.path index 0 for
# its consumers, so once upstream ships a real _scproxy that lives on the path
# this file would shadow it. That is the one reason it must not be left behind
# forever. It cannot shadow a BUILT-IN _scproxy, which wins over sys.path
# outright, so the worst case is proxy discovery staying disabled on a box that
# has no proxy anyway.
SCPROXY_NAME = "_scproxy.py"

# WHERE, and why not the obvious place.
#
# NOT the per-user site directory. CPython resolves that to
# $HOME/.local/lib/python<X.Y>/site-packages, and $HOME on tvOS is the app DATA
# CONTAINER ROOT (getenv("HOME") and nothing else, PlatformPosix.cpp:34-41).
# MEASURED on atv1 (tvOS 27.0, Kodi 22.0-BETA1): the sandbox refuses with
# "[Errno 1] Operation not permitted" to create ANY new entry at that root or
# directly under Library/, so the service logged a failure on every single boot
# and POV stayed dead. PYTHONUSERBASE cannot move it either, being read by
# site.py from an environment Kodi has already finished setting before
# Py_Initialize (XBPython.cpp:44-63). devicectl cannot reach the stock path
# either: `copy to` returns CoreDeviceError 7000 for any destination containing
# a dot-directory component.
#
# THIS instead: script.module.requests' library directory, which is inside
# special://home where Kodi can write, and which is already on the sys.path of
# every add-on that declares it. PythonInvoker builds an add-on's path from its
# declared dependencies and RECURSES through them (PythonInvoker.cpp:203-228,
# the walk at :709-727, each inserted at index 0), and script.module.requests
# declares library="lib".
#
# So the shim reaches exactly the add-ons whose dependency closure contains
# script.module.requests, and nothing else. MEASURED on atv1 by reading each
# installed addon.xml: plugin.video.pov, weather.multi and
# script.openweathermap.maps all declare it, as does script.ezmaintenanceplusplus
# in this tree. The metadata scrapers and service.xbmc.versioncheck do NOT, so
# they are not covered by this and must not be claimed as fixed.
#
# Writing there is established practice here, not a new liberty. The
# bootstrapper already replaces this whole dependency closure, including
# script.module.requests/lib, from a version-controlled tree
# (bootstrapper/bin/bundle:519-537). EZM++'s restore extracts into
# special://home/addons/<any id>/ and is hardware-verified on both platforms
# (wiz.py:1444, wiz.py:2217). skin.estuary8's installRepo replaces entire add-on
# directories at runtime (helpers.py:121-175).
SHIM_DIR_PATH = "special://home/addons/script.module.requests/lib/"

SCPROXY = "\n".join(
    [
        '"""Stand-in for CPython\'s _scproxy, written by skin.estuary.pov.',
        "",
        "Kodi's tvOS build ships no _scproxy while sys.platform stays 'darwin', so",
        "urllib.request cannot be imported at all without this file.",
        "",
        "SystemConfiguration proxy discovery does not exist on a tvOS box, so this",
        "reports the truth: no proxies are configured. urllib.request then makes",
        "direct connections, and http_proxy / https_proxy environment variables are",
        "still honoured, because getproxies_environment is consulted first.",
        "",
        "Contract taken from CPython 3.14 Lib/urllib/request.py:2035 and the",
        "_proxy_bypass_macosx_sysconf docstring at :1953.",
        '"""',
        "",
        "",
        "def _get_proxy_settings():",
        '    return {"exclude_simple": False, "exceptions": []}',
        "",
        "",
        "def _get_proxies():",
        "    return {}",
        "",
    ]
)


def _shim_target_dir():
    """Resolve SHIM_DIR_PATH through Kodi. The why is on SHIM_DIR_PATH above.

    Resolved through xbmcvfs rather than built from os.path.expanduser, because
    expanduser on tvOS returns the container root, which is the unwritable place
    this whole approach exists to avoid.
    """
    return xbmcvfs.translatePath(SHIM_DIR_PATH)


def write_scproxy():
    """Write the shim if its bytes differ. Returns a one-line summary."""
    directory = _shim_target_dir()
    path = os.path.join(directory, SCPROXY_NAME)

    # Deliberately NOT os.makedirs. If script.module.requests is absent then
    # nothing on the box depends on it, so the shim would help nobody, and
    # creating addons/script.module.requests/ with no addon.xml in it would
    # leave a malformed add-on directory for Kodi's scanner to find and for a
    # later dependency install to land on top of. Absent is a valid state, not a
    # failure: it is reported and the boot carries on.
    if not os.path.isdir(directory):
        return "%s skipped, script.module.requests is not installed" % SCPROXY_NAME

    current = None
    if os.path.isfile(path):
        try:
            with open(path, "r") as handle:
                current = handle.read()
        except OSError:
            current = None

    if current == SCPROXY:
        return "%s already current in %s" % (SCPROXY_NAME, SHIM_DIR_PATH)

    with open(path, "w") as handle:
        handle.write(SCPROXY)
    return "wrote %s to %s" % (SCPROXY_NAME, SHIM_DIR_PATH)


# Long enough for Kodi's own doomed startup fetch to finish and release the
# weather job, short enough that nobody watches a blank panel. MEASURED on atv1:
# that fetch ran 05:14:33.391 to 05:14:34.895, and a refresh fired 100 ms into it
# was silently dropped, which is the bug this constant exists to avoid.
WEATHER_RETRY_SECONDS = 10


def refresh_weather():
    """Re-fetch the weather, because Kodi's own startup fetch loses the race.

    Kodi has no hook that runs before add-ons do, and it kicks its startup
    weather fetch off about a second before service add-ons get their
    interpreters. weather.multi declares script.module.requests (measured on
    atv1), so on the boot that first writes the shim that fetch has already died
    on the missing _scproxy, and the weather stays blank until the next
    scheduled refresh, up to half an hour later.

    Unconditional rather than conditional on having just written the file. A
    refresh that only fired when the shim changed would fix the weather exactly
    once and never again, and the cost of being wrong the other way is one extra
    HTTP fetch per start.

    Weather.Refresh is a Kodi builtin (WeatherBuiltins.cpp), not an add-on call,
    so this stays inside the skin's own business: it names no add-on, works with
    whatever provider the box is set to, and does nothing at all if none is set.
    One extra fetch per start.

    The wait is not politeness, it is required: firing while the first fetch is
    still in flight is a no-op, because Kodi will not queue a second weather job
    over a running one. waitForAbort rather than sleep so a box shut down inside
    the window exits immediately instead of holding the service open.
    """
    monitor = xbmc.Monitor()
    if monitor.waitForAbort(WEATHER_RETRY_SECONDS):
        return "weather re-fetch skipped, Kodi is shutting down"
    xbmc.executebuiltin("Weather.Refresh")
    return "weather re-fetch requested"


# --------------------------------------------------------------------------- #
# 2. The Siri remote keymap
# --------------------------------------------------------------------------- #


def write_keymap():
    """Write the keymap if its bytes differ, and reload keymaps only then."""
    directory = xbmcvfs.translatePath("special://profile/keymaps/")
    path = os.path.join(directory, KEYMAP_NAME)

    current = None
    if os.path.isfile(path):
        try:
            with open(path, "r") as handle:
                current = handle.read()
        except OSError:
            current = None

    if current == KEYMAP:
        return "%s already current" % KEYMAP_NAME

    if not os.path.isdir(directory):
        os.makedirs(directory)
    with open(path, "w") as handle:
        handle.write(KEYMAP)
    xbmc.executebuiltin("Action(reloadkeymaps)")
    return "wrote %s and reloaded keymaps" % KEYMAP_NAME


# The shim comes first: it is the one that other add-ons are racing, and every
# instruction between here and the write is time POV or Multi Weather can spend
# dying at import. Each write is isolated, so one failing never costs the other.
WRITES = (
    ("_scproxy shim", write_scproxy),
    ("keymap", write_keymap),
    ("weather refresh", refresh_weather),
)


def main():
    """tvOS only. On every other platform this service does nothing at all."""
    if not xbmc.getCondVisibility("System.Platform.TVOS"):
        _log("not tvOS, boot service is a no-op", level=xbmc.LOGDEBUG)
        return
    # One INFO line per start, deliberately. A repair that only reports itself at
    # debug level is a repair nobody can confirm happened without reproducing the
    # whole boot with debug logging on, and this one runs on a box where getting
    # a log at all costs a devicectl round trip.
    done = []
    for label, write in WRITES:
        try:
            done.append(write())
        except Exception as error:  # noqa: BLE001 - a boot service must never die
            done.append("%s FAILED: %s" % (label, error))
            _log("%s failed: %s" % (label, error), level=xbmc.LOGWARNING)
    _log("tvOS start: " + "; ".join(done))


if __name__ == "__main__":
    main()
