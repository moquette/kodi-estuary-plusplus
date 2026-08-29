"""tvOS Python Fix: put back the _scproxy module Kodi's tvOS build removes.

Kodi's tvOS build disables CPython's _scproxy extension while CPython carries on
reporting sys.platform == "darwin", so Lib/urllib/request.py:2035 imports a module
that is not there, at MODULE TOP LEVEL. Anything that touches requests or urllib
therefore dies at import on every tvOS box: POV, Multi Weather, and EZ
Maintenance++'s Dropbox and pastebin paths, none of which are ours to patch.

Upstream cause, measured against atv1's own build commit 77395cf42e:
tools/depends/target/python3/Makefile:81-83 sets py_cv_module__scproxy=n/a for all
darwin_embedded, and the compensating 16-ios-platform.patch that stops CPython
reporting "darwin" is applied only under findstring iphone, while
configure.ac:490-493 maps tvos to appletvos. iOS gets both halves; tvOS gets only
the removal.

DELETE THIS ADD-ON the first time a tvOS Kodi build imports urllib.request without
_scproxy. It is a workaround for someone else's defect, not a feature, and the
directory it writes into is at sys.path index 0 for its consumers, so once
upstream ships a real _scproxy on the path this file would shadow it. It cannot
shadow a BUILT-IN _scproxy, which wins over sys.path outright, so the worst case
is proxy discovery staying disabled on a box that has no proxy anyway.

WHY THIS IS ITS OWN ADD-ON AND NOT A SKIN SERVICE
-------------------------------------------------
It lived in skin.estuary.pov's boot service in 1.2.2 through 1.2.5, and that
placement could not fix a fresh install, structurally. MEASURED on atv1
2026-08-29 07:42, from the owner's own first-run, and reproduced on a clean
macOS Kodi 22 bench with an isolated HOME the same morning:

    07:42:31.660  Found addon: 'script.module.requests v2.31.0'
    07:42:31.754  Found addon: 'plugin.video.pov v6.08.15'
    07:42:31.884  >> POV <<: Main Monitor Service Starting
    07:42:32.991  ModuleNotFoundError: No module named '_scproxy'   <- the error
    07:42:33.108  Found addon: 'skin.estuary.pov v1.2.5'            <- 117 ms LATER
    07:42:43.140  estuary.pov: tvOS start: wrote _scproxy.py        <- 10 s later

Kodi installs a parent's dependencies BEFORE the parent, so POV was installed,
started and dead before the skin carrying its fix was on disk at all. No skin can
win that, because the fix has to exist before the thing it fixes is installed. An
add-on that is itself a DEPENDENCY can, which is the whole reason this exists.

THE ORDERING THIS RELIES ON, ALL MEASURED ON A CLEAN KODI 22 BENCH
------------------------------------------------------------------
1. Dependencies install depth first, a node's own dependencies before the node.
   That is what puts script.module.requests and its four modules ahead of this
   add-on, and it is why the target directory is guaranteed to exist.
2. Sibling dependencies install in the order the parent DECLARES them, not
   alphabetically. Measured by flipping two <import> lines in the skin and
   watching the install order flip with them.
3. A newly installed service add-on is started IMMEDIATELY, mid session, with no
   Kodi restart. Measured with a throwaway probe service: Kodi logged
   "Found addon" and "CServiceAddonManager: starting" in the SAME millisecond and
   the script's own first line 4 ms later.

So the skin declares this add-on ahead of plugin.video.pov, this add-on declares
script.module.requests, and the resulting order is
certifi, chardet, idna, urllib3, requests, THIS, ... , plugin.video.pov.

It is still a race and that is stated rather than glossed: this service is
dispatched asynchronously, so what is guaranteed is the INSTALL order, not that
this Python interpreter has finished before POV's install completes.

THE MARGIN IS MILLISECONDS, NOT SECONDS, and an earlier version of this comment
had that wrong. MEASURED 2026-08-29 over three first installs from the live
repository onto three clean Kodi 22 profiles, which is the case that matters
because it is the one the owner hit:

    install gap, this add-on to POV      5.87 s, 4.20 s, 3.53 s
    EXECUTION gap, this script's first
    line to POV's service starting       11 ms,  7 ms,   12 ms

The install gap is comfortable and is what declaring the autocompletion subtree
between the two buys. The execution gap is not, and the reason is that a service
add-on's interpreter does not run when it is dispatched. On run 3 this add-on was
installed at 09:53:14.331, CPythonInvoker(2) logged "start processing" at
09:53:14.332, and the script's first line did not appear until 09:53:21.219,
6.887 s later: Python execution is queued behind the install storm, and every
service that was dispatched during it runs in a burst once the storm ends.

So what actually protects this is NOT slack, it is FIFO: this add-on's
interpreter is dispatched seconds before POV's, so it is ahead of POV's in that
queue and runs first, by the milliseconds above rather than by the seconds the
install gap suggests. Do not read the install gap as headroom, and do not remove
the ordering on the strength of it. Won 3 of 3 there, and 5 of 5 on an earlier
bench where the dependencies were already present and the margin was 0.455 s to
3.9 s, which is the same mechanism under less contention.

Losing the race costs exactly one add-on's service start on one boot, because
Kodi rebuilds an add-on's sys.path from its declared dependencies on EVERY
invocation (PythonInvoker.cpp:203-228), so everything invoked afterwards picks
the file up with no restart.

Strict no-op off tvOS, gated on xbmc.getCondVisibility('System.Platform.TVOS'),
and that gate is enforced by tests rather than merely intended: Fire TV, Android
and desktop boxes must get nothing.

The write is idempotent BY CONTENT: the file is read back and rewritten only if
its bytes differ, so a normal start does no disk IO at all.
"""

import os

import xbmc
import xbmcvfs

LOG_PREFIX = "tvos.pythonfix: "

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
# The other four directories on POV's path, certifi, chardet, idna and urllib3,
# would work identically. requests is chosen because it is the one whose import
# raises the error and the one every affected add-on declares directly, so a
# reader who finds the file has the shortest path back to the reason.
#
# Writing a file into an add-on we do not own is NOT the prohibited thing. This
# project's standing rule forbids forking, versioning, patching or SHIPPING
# someone else's code, because upstream's next release silently reverts it and
# leaves us carrying a copy nobody knows about. Nothing here is shipped or
# forked: upstream's own bytes are untouched, an update simply removes the shim,
# and the next start puts it back.
SHIM_DIR_PATH = "special://home/addons/script.module.requests/lib/"

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

# Long enough for Kodi's own doomed startup fetch to finish and release the
# weather job, short enough that nobody watches a blank panel. MEASURED on atv1:
# that fetch ran 05:14:33.391 to 05:14:34.895, and a refresh fired 100 ms into it
# was silently dropped, which is the bug this constant exists to avoid.
WEATHER_RETRY_SECONDS = 10


def _log(message, level=xbmc.LOGINFO):
    xbmc.log(LOG_PREFIX + message, level=level)


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

    # Deliberately NOT os.makedirs. script.module.requests is a declared
    # dependency of this add-on, so Kodi has installed it before this runs and
    # the directory is there. If it somehow is not, then nothing on the box
    # depends on it, the shim would help nobody, and creating
    # addons/script.module.requests/ with no addon.xml in it would leave a
    # malformed add-on directory for Kodi's scanner to find and for a later
    # dependency install to land on top of. Absent is a reportable state, not a
    # failure: it is logged and the boot carries on.
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


def refresh_weather():
    """Re-fetch the weather, because Kodi's own startup fetch loses the race.

    Kodi has no hook that runs before add-ons do, and it kicks its startup
    weather fetch off about a second before service add-ons get their
    interpreters. weather.multi declares script.module.requests (measured on
    atv1), so on any start where the shim is not already on disk, that fetch has
    already died on the missing _scproxy and the weather stays blank until the
    next scheduled refresh, up to half an hour later. The start after an update
    to script.module.requests is exactly that case, because the update takes the
    shim with it.

    Unconditional rather than conditional on having just written the file, and
    that is the behaviour this add-on inherited rather than a fresh choice. The
    cost of being wrong is one extra HTTP fetch per start.

    Weather.Refresh is a Kodi builtin (WeatherBuiltins.cpp), not an add-on call,
    so this names no add-on, works with whatever provider the box is set to, and
    does nothing at all if none is set.

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


# The shim comes first: it is the one that other add-ons are racing, and every
# instruction between here and the write is time POV or Multi Weather can spend
# dying at import. Each step is isolated, so one failing never costs the other.
#
# The flag on each row says whether its result is logged the INSTANT it lands as
# well as in the summary. Only the shim carries it, and it is not decoration:
# the summary cannot be emitted until refresh_weather's ten second wait is over,
# so it timestamps the shim ten seconds late. That is useless for the one
# question anybody will ever ask this log, which is whether the shim beat POV's
# service start. That gap was 0.455 s to 3.9 s on a bench whose dependencies were
# already installed, and 7 ms to 12 ms on three first installs from the live
# repository (see the module docstring), so ten seconds of slack in the timestamp
# is not a rounding error, it is the difference between a measurement and a
# guess. It cost three of those five bench runs their evidence.
WRITES = (
    ("_scproxy shim", write_scproxy, True),
    ("weather refresh", refresh_weather, False),
)


def main():
    """tvOS only. On every other platform this service does nothing at all."""
    if not xbmc.getCondVisibility("System.Platform.TVOS"):
        _log("not tvOS, service is a no-op", level=xbmc.LOGDEBUG)
        return
    # INFO rather than debug, deliberately. A repair that only reports itself at
    # debug level is a repair nobody can confirm happened without reproducing the
    # whole boot with debug logging on, and this one runs on a box where getting
    # a log at all costs a devicectl round trip.
    done = []
    for label, write, log_immediately in WRITES:
        try:
            result = write()
        except Exception as error:  # noqa: BLE001 - a boot service must never die
            result = "%s FAILED: %s" % (label, error)
            _log("%s failed: %s" % (label, error), level=xbmc.LOGWARNING)
        else:
            if log_immediately:
                _log(result)
        done.append(result)
    _log("tvOS start: " + "; ".join(done))


if __name__ == "__main__":
    main()
