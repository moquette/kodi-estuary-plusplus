"""skin.estuary.pov boot service: write the Siri remote keymap on tvOS.

Ported from skin.estuary7's scripts/services.py, which has shipped this same
keymap fleet-wide since 2026-07-15. Nothing else lives here.

Kodi loads keymaps only from userdata/keymaps/, and a skin cannot ship into that
directory, so a boot service is the only way a skin can correct its own remote
behaviour. This is squarely the skin's own business: it changes what the buttons
on the remote do inside this skin's windows, creates no dependency on any add-on,
and nothing outside the skin needs to be installed for it to work.

Strict no-op off tvOS. The gate is xbmc.getCondVisibility('System.Platform.TVOS')
and it is enforced by a test, not merely intended: Fire TV and Android boxes must
never get a keymap file.
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
        _log("%s already current" % KEYMAP_NAME, level=xbmc.LOGDEBUG)
        return False

    if not os.path.isdir(directory):
        os.makedirs(directory)
    with open(path, "w") as handle:
        handle.write(KEYMAP)
    xbmc.executebuiltin("Action(reloadkeymaps)")
    _log("wrote %s and reloaded keymaps" % KEYMAP_NAME)
    return True


def main():
    """tvOS only. On every other platform this service does nothing at all."""
    if not xbmc.getCondVisibility("System.Platform.TVOS"):
        _log("not tvOS, boot service is a no-op", level=xbmc.LOGDEBUG)
        return
    try:
        write_keymap()
    except Exception as error:  # noqa: BLE001 - a boot service must never die
        _log("keymap write failed: %s" % error, level=xbmc.LOGWARNING)


if __name__ == "__main__":
    main()
