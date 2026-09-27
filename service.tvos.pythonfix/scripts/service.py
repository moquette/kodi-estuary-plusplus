"""Everything Kodi's Apple TV build needs put right, in one place. tvOS only.

Two repairs, both of them KODI's business rather than any skin's or any other
add-on's, and both of which can only be done by a running process because Kodi
reads the files at startup and no package can ship into them:

1. THE _scproxy SHIM. Kodi's tvOS build disables CPython's _scproxy extension
   while CPython carries on reporting sys.platform == "darwin", so
   Lib/urllib/request.py:2035 imports a module that is not there, at MODULE TOP
   LEVEL. Anything that touches requests or urllib dies at import on every tvOS
   box: POV, Multi Weather, and EZ Maintenance++'s Dropbox and pastebin paths,
   none of which are ours to patch.

   Upstream cause, measured against atv1's own build commit 77395cf42e:
   tools/depends/target/python3/Makefile:81-83 sets py_cv_module__scproxy=n/a
   for all darwin_embedded, and the compensating 16-ios-platform.patch that
   stops CPython reporting "darwin" is applied only under findstring iphone,
   while configure.ac:490-493 maps tvos to appletvos. iOS gets both halves;
   tvOS gets only the removal.

2. THE SIRI REMOTE KEYMAP. Kodi's shipped
   system/keymaps/customcontroller.SiriRemote.xml makes four choices the owner
   does not want, and Kodi reads keymaps ONLY from userdata/keymaps/, which no
   package can ship into. The bindings name Kodi windows and Kodi actions and
   nothing else, so this is a correction to Kodi's own remote handling and it
   belongs with the other one.

WHY BOTH LIVE HERE AND NOT IN A SKIN
------------------------------------
The shim lived in skin.estuary.pov's boot service in 1.2.2 through 1.2.5 and the
keymap lived there through 1.2.8, and neither placement was right.

The shim's case is structural. MEASURED on atv1 2026-08-29 07:42, from the
owner's own first run, and reproduced on a clean macOS Kodi 22 bench with an
isolated HOME the same morning:

    07:42:31.660  Found addon: 'script.module.requests v2.31.0'
    07:42:31.754  Found addon: 'plugin.video.pov v6.08.15'
    07:42:31.884  >> POV <<: Main Monitor Service Starting
    07:42:32.991  ModuleNotFoundError: No module named '_scproxy'   <- the error
    07:42:33.108  Found addon: 'skin.estuary.pov v1.2.5'            <- 117 ms LATER

Kodi installs a parent's dependencies BEFORE the parent, so POV was installed,
started and dead before the skin carrying its fix was on disk at all. No skin can
win that, because the fix has to exist before the thing it fixes is installed.

The keymap's case is ownership, and it is the simpler argument. A Siri remote
belongs to the box, not to whatever skin happens to be selected. Written from a
skin it arrives only for users of that skin, it is written again by every other
skin that copies the idea, and an Apple TV owner who switches skins loses it for
no reason he can see. Written from here it is one add-on, installed once, and
the skin is a skin.

So the skin (skin.estuary.pov then, skin.estuary.plusplus since 1.5.0) has NO boot
service, NO scripts directory and no tvOS code of any kind as of 1.3.0, and this
add-on is the only thing on the box that knows tvOS is different. Do not put
either write back into a skin.

INSTALLED FIRST AND ALONE, SO THERE IS NO RACE TO WIN
-----------------------------------------------------
This add-on is user-installed from the Tony.7.Bones repository, not pulled in as
anybody's dependency. skin.estuary.pov 1.2.7 declared it as a hard <import>,
which fixed the ordering but shipped a tvOS-only workaround to every Fire TV,
Android, Windows, Linux and macOS box, and 1.2.8 removed that import.

That change is what makes the ordering question go away rather than sharpen it.
As a sibling dependency the margin was won by FIFO position on the Python invoker
queue and was MEASURED at 7 ms, 11 ms and 12 ms over three first installs from
the live repository, which is not a margin anybody should be relying on.
Installed deliberately, before anything that needs it, the shim is on disk before
the consumer exists. Do not reintroduce an <import> of this add-on anywhere to
"guarantee" ordering; installing it first is the guarantee.

Losing anyway costs exactly one add-on's service start on one boot, because Kodi
rebuilds an add-on's sys.path from its declared dependencies on EVERY invocation
(PythonInvoker.cpp:203-228), so everything invoked afterwards picks the file up
with no restart.

DELETE THIS ADD-ON the first time a tvOS Kodi build imports urllib.request
without _scproxy and ships a Siri remote keymap worth keeping. It is a workaround
for someone else's defects, not a feature. The shim cannot shadow a BUILT-IN
_scproxy, which wins over sys.path outright, so a leftover copy on a repaired
build costs nothing but a stale file.

Strict no-op off tvOS, gated on xbmc.getCondVisibility('System.Platform.TVOS'),
and that gate is enforced by tests rather than merely intended: Fire TV, Android
and desktop boxes must get nothing at all.

Both writes are idempotent BY CONTENT: each file is read back and rewritten only
if its bytes differ, so a normal start does no disk IO at all.
"""

import os

import xbmc
import xbmcvfs

LOG_PREFIX = "tvos.fixes: "

SCPROXY_NAME = "_scproxy.py"

# WHERE THE SHIM GOES, why not the obvious place, and why more than one.
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
# a dot-directory component. That route is closed; do not re-derive it.
#
# THESE instead: the library directories of script.module.requests and of its own
# four dependencies. All five live inside special://home where Kodi can write,
# all five declare <extension point="xbmc.python.module" library="lib">, and
# PythonInvoker builds an add-on's sys.path from its declared dependencies and
# RECURSES through them (PythonInvoker.cpp:203-228, the walk at :709-727, each
# inserted at index 0). So an add-on that declares script.module.requests gets
# all five directories on its path, not just the one.
#
# The redundancy is the point, and it is the answer to the one recurring failure
# this add-on would otherwise have. MEASURED against the Kodi 22 source: an
# update is a directory SWAP, not an extract over the top.
# CAddonInstallJob::Install calls CFilesystemInstaller::InstallToFilesystem
# (AddonInstaller.cpp:1203-1204), which unpacks the new tree into a temp uuid
# folder, renames the WHOLE old directory aside, moves the new one into place and
# then RemoveRecursive's the old one (FilesystemInstaller.cpp:74-89). Files that
# were never in any zip go with it. So an update to script.module.requests
# deletes the shim, and every networked add-on on the box breaks again until this
# service next runs. Uninstall is the same code shape (:96-110).
#
# Writing all five turns "one module updated" from an outage into a no-op,
# because urllib only needs to find _scproxy on ONE path entry, and five
# independent upstream modules do not update in the same instant. The next start
# repairs whichever ones were replaced.
#
# THE THREE ALTERNATIVES WERE MEASURED AND ARE WORSE. Do not re-derive them.
#   - A directory Kodi owns and nobody can update. There isn't one. Every entry
#     on an add-on's sys.path comes from PythonInvoker.cpp:230-239, fed by
#     exactly three producers: the invoking script's own directory (:205, useless
#     for shimming another add-on's interpreter), each SCRIPT_MODULE dependency's
#     LibPath (:208-213 and the walk at :709-727, which is these five), and a
#     no-addon-context fallback (:224-227) that is the same third-party dirs.
#     Everything else is PYTHONHOME/PYTHONPATH pointed at special://frameworks
#     (XBPython.cpp:56-57), inside the read-only app bundle.
#   - A resident service that reacts to the update. Kodi 22 has no AddOn
#     announcement flag at all (IAnnouncer.h:16-30) and nothing under xbmc/addons/
#     calls Announce, so xbmc.Monitor never hears about an install, update or
#     uninstall. The C++ AddonEvents::ReInstalled bus (AddonEvents.h:41-123) has
#     no Python bridge, and Service.cpp:43-47 restarts only the add-on that was
#     itself reinstalled, never its dependents.
#   - A resident service that POLLS. Possible, but it buys a shorter window at
#     the cost of a Python interpreter resident for the whole session on a box
#     with a documented memory-kill history. Redundancy removes the window
#     instead of shrinking it, and costs nothing after the write.
#
# Cost of the redundancy, stated rather than glossed: five 1 KB files instead of
# one, written once, only when their bytes differ. Deleting this add-on leaves up
# to five stale files behind instead of one, and each of those is removed by the
# next update to the module it sits in. A stale shim cannot shadow a real
# _scproxy, because a built-in module wins over sys.path outright.
#
# requests is FIRST deliberately: it is the module whose import raises the error
# and the one every affected add-on declares directly, so a reader who finds the
# file has the shortest path back to the reason. The other four are insurance.
#
# MEASURED on atv1 by reading each installed addon.xml: plugin.video.pov,
# weather.multi and script.openweathermap.maps all declare
# script.module.requests, as does script.ezmaintenanceplusplus in this tree. The
# metadata scrapers and service.xbmc.versioncheck do NOT, so they are not covered
# by this and must not be claimed as fixed.
#
# Writing a file into an add-on we do not own is NOT the prohibited thing. This
# project's standing rule forbids forking, versioning, patching or SHIPPING
# someone else's code, because upstream's next release silently reverts it and
# leaves us carrying a copy nobody knows about. Nothing here is shipped or
# forked: upstream's own bytes are untouched, an update simply removes the shim,
# and the next start puts it back.
SHIM_DIR_PATHS = (
    "special://home/addons/script.module.requests/lib/",
    "special://home/addons/script.module.urllib3/lib/",
    "special://home/addons/script.module.certifi/lib/",
    "special://home/addons/script.module.idna/lib/",
    "special://home/addons/script.module.chardet/lib/",
)

SCPROXY = "\n".join(
    [
        '"""Stand-in for CPython\'s _scproxy, written by service.tvos.pythonfix.',
        "",
        "Kodi's tvOS build ships no _scproxy while sys.platform stays 'darwin', so",
        "urllib.request cannot be imported at all without this file.",
        "",
        "SystemConfiguration proxy discovery does not exist on a tvOS box, so this",
        "reports the truth: no proxies are configured. urllib.request then makes",
        "direct connections, and http_proxy / https_proxy environment variables are",
        "still honoured, because getproxies_environment is consulted first.",
        "",
        "Copies of this file are written into several script.module.* library",
        "directories on purpose, so that updating any one of those modules cannot",
        "take the shim off the path. Delete them all, and the add-on, once Kodi's",
        "Apple TV build ships a real _scproxy.",
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
KEYMAP_DIR_PATH = "special://profile/keymaps/"

KEYMAP_NAME = "t7b-siriremote.xml"

KEYMAP = "\n".join(
    [
        '<?xml version="1.0" encoding="UTF-8"?>',
        "<!-- Written by service.tvos.pythonfix. Back exits fullscreen video with",
        "     playback continuing, double play/pause returns to it, and back at Home",
        "     no longer opens the Favourites browser. Delete this file and run",
        "     Action(reloadkeymaps) to revert to stock behaviour. -->",
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


def _write_if_changed(directory, name, body):
    """Write body to directory/name only if the bytes differ. True if written.

    Returns None when the directory is absent, which is a reportable state rather
    than a failure, and the two callers treat it differently.
    """
    path = os.path.join(directory, name)
    if not os.path.isdir(directory):
        return None

    current = None
    if os.path.isfile(path):
        try:
            with open(path, "r") as handle:
                current = handle.read()
        except OSError:
            current = None

    if current == body:
        return False

    with open(path, "w") as handle:
        handle.write(body)
    return True


def write_scproxy():
    """Write the shim into every module library directory present.

    Deliberately NOT os.makedirs. script.module.requests is a declared dependency
    of this add-on, so Kodi has installed it and its own four dependencies before
    this runs and the directories are there. If one somehow is not, then nothing
    on the box depends on it, a shim there would help nobody, and creating
    addons/script.module.<x>/ with no addon.xml in it would leave a malformed
    add-on directory for Kodi's scanner to find and for a later dependency
    install to land on top of. Absent is skipped, not created.

    All-absent is the only case worth reporting on its own, because it means
    nothing on this box could have been using requests in the first place.
    """
    written = []
    present = 0
    for path in SHIM_DIR_PATHS:
        directory = xbmcvfs.translatePath(path)
        result = _write_if_changed(directory, SCPROXY_NAME, SCPROXY)
        if result is None:
            continue
        present += 1
        if result:
            written.append(path.split("/")[-3])

    if not present:
        return "%s skipped, no script.module.* target is installed" % SCPROXY_NAME
    if not written:
        return "%s already current in %d of %d dirs" % (
            SCPROXY_NAME,
            present,
            len(SHIM_DIR_PATHS),
        )
    return "wrote %s to %d of %d dirs (%s)" % (
        SCPROXY_NAME,
        len(written),
        len(SHIM_DIR_PATHS),
        ", ".join(written),
    )


def write_keymap():
    """Write the keymap if its bytes differ, and reload keymaps only then.

    os.makedirs here and NOT in write_scproxy, and the difference is ownership:
    special://profile/keymaps/ is Kodi's own directory for exactly this file and
    may legitimately not exist yet on a fresh profile, whereas the shim targets
    belong to other add-ons and creating one would fabricate a broken add-on.
    """
    directory = xbmcvfs.translatePath(KEYMAP_DIR_PATH)
    if not os.path.isdir(directory):
        os.makedirs(directory)

    if not _write_if_changed(directory, KEYMAP_NAME, KEYMAP):
        return "%s already current" % KEYMAP_NAME
    xbmc.executebuiltin("Action(reloadkeymaps)")
    return "wrote %s and reloaded keymaps" % KEYMAP_NAME


# The shim comes FIRST and the order is load bearing, not cosmetic. It is the one
# other add-ons can be racing on a box where this was installed mid session, and
# every instruction in front of it is time POV or Multi Weather can spend dying at
# import. The keymap is only read when the user next presses a button, so it can
# never be the urgent one.
#
# A table rather than two bare calls, because main() isolates each row in its own
# try: a keymap failure can never cost the shim, and a third repair added later
# inherits that for free without touching main().
WRITES = (
    ("_scproxy shim", write_scproxy),
    ("Siri remote keymap", write_keymap),
)


def main():
    """tvOS only. On every other platform this service does nothing at all.

    NO xbmc.executebuiltin call belongs here beyond the keymap reload, and that
    one is inside write_keymap where it only fires on a real write. In particular
    do not add Weather.Refresh back. 1.0.x fired it ten seconds into every tvOS
    start and it never did anything: WeatherBuiltins.cpp:83 maps weather.refresh
    to SwitchLocation<0>, which sends GUI_MSG_MOVE_OFFSET to WINDOW_WEATHER
    (WeatherBuiltins.cpp:36-43) rather than calling CWeatherManager::Refresh();
    GUIWindowWeather.cpp:103-116 handles that message only when m_maxLocation > 0;
    the only assignment to m_maxLocation is in UpdateLocations()
    (GUIWindowWeather.cpp:143), which returns immediately unless the Weather
    window is the one on screen (:132-134). At boot it never is, so the message
    was dropped every time. Removing it also gave this service its life back: it
    now exits as soon as both files are on disk instead of holding an interpreter
    open for ten seconds on every start.
    """
    if not xbmc.getCondVisibility("System.Platform.TVOS"):
        _log("not tvOS, service is a no-op", level=xbmc.LOGDEBUG)
        return
    # One INFO line per start, deliberately, and INFO rather than debug. A repair
    # that only reports itself at debug level is a repair nobody can confirm
    # happened without reproducing the whole boot with debug logging on, and this
    # one runs on a box where getting a log at all costs a devicectl round trip.
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
