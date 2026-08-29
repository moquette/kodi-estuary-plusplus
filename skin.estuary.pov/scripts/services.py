"""skin.estuary.pov boot service: the Siri remote keymap, written on every start.

Ported from skin.estuary7's scripts/services.py, which has shipped the same
payload fleet-wide since 2026-07-15. Kodi reads keymaps only out of
userdata/keymaps/, which a skin cannot ship into, so a boot service is the only
mechanism available.

Strict no-op off tvOS, gated on xbmc.getCondVisibility('System.Platform.TVOS'),
and that gate is enforced by tests rather than merely intended: Fire TV, Android
and desktop boxes must get no file.

The write is idempotent BY CONTENT: the file is read back and rewritten only if
its bytes differ, so a normal start does no disk IO at all.

THE _scproxy SHIM USED TO LIVE HERE AND HAS MOVED. Do not put it back.
1.2.2 through 1.2.5 wrote it from this service, and that placement could not fix
a fresh install, structurally. Kodi installs a parent's dependencies BEFORE the
parent, so on the owner's own first run on atv1 (MEASURED 2026-08-29, kodi.log)
plugin.video.pov was installed at 07:42:31.754, its service started at
07:42:31.884 and died on the missing _scproxy at 07:42:32.991, and this skin was
not found on disk until 07:42:33.108, 117 ms after the error the user was staring
at. It is now service.tvos.pythonfix, declared in this skin's addon.xml ahead of
plugin.video.pov, because a DEPENDENCY installs before the add-ons that need it
and a skin never can. That also makes it work for boxes with no skin of ours on
them at all, which was always the honest shape: repairing the box's Python
runtime is not a skin's business.
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


# One entry, and it stays a table rather than a bare call. Every write is
# isolated by main()'s try, so a second repair added here can never cost the
# keymap, and the log line stays one line per start whatever is in it.
WRITES = (("keymap", write_keymap),)


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
