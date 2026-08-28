"""Minimal xbmc / xbmcvfs stand-ins, enough to boot the real services.py.

Deliberately NOT a mock of the module under test: the tests import the real
scripts/services.py and run its real payload against these. A substring check on
the source text would pass even if the platform gate were deleted.
"""

import sys
import types

LOGDEBUG, LOGINFO, LOGWARNING = 0, 1, 2


class Recorder:
    """Everything the service did, in order."""

    def __init__(self, platform, profile_dir):
        self.platform = platform
        self.profile_dir = str(profile_dir)
        self.builtins = []
        self.logs = []
        self.conditions = []
        self.translated = []
        self.waits = []
        self.aborting = False


def install(platform, profile_dir):
    """Put fake xbmc/xbmcvfs in sys.modules and return the Recorder."""
    rec = Recorder(platform, profile_dir)

    xbmc = types.ModuleType("xbmc")
    xbmc.LOGDEBUG, xbmc.LOGINFO, xbmc.LOGWARNING = LOGDEBUG, LOGINFO, LOGWARNING

    def getCondVisibility(condition):
        rec.conditions.append(condition)
        # Kodi answers exactly one platform condition true.
        return condition == "System.Platform.%s" % rec.platform

    def executebuiltin(command):
        rec.builtins.append(command)

    def log(message, level=LOGINFO):
        rec.logs.append((level, message))

    class Monitor:
        """Kodi's abort monitor. Records the wait; answers with rec.aborting."""

        def waitForAbort(self, seconds):
            rec.waits.append(seconds)
            return rec.aborting

    xbmc.getCondVisibility = getCondVisibility
    xbmc.executebuiltin = executebuiltin
    xbmc.log = log
    xbmc.Monitor = Monitor

    xbmcvfs = types.ModuleType("xbmcvfs")

    def translatePath(path):
        rec.translated.append(path)
        if path == "special://profile/keymaps/":
            return rec.profile_dir + "/keymaps/"
        if path.startswith("special://home/"):
            return rec.profile_dir + "/home/" + path[len("special://home/") :]
        raise AssertionError("unexpected special path: %s" % path)

    xbmcvfs.translatePath = translatePath

    sys.modules["xbmc"] = xbmc
    sys.modules["xbmcvfs"] = xbmcvfs
    return rec
