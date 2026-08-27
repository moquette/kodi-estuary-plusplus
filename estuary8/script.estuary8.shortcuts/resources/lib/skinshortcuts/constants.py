"""Constants for Skin Shortcuts."""

from __future__ import annotations

try:
    import xbmcvfs

    IN_KODI = True
except ImportError:
    IN_KODI = False

MENUS_FILE = "menus.xml"
WIDGETS_FILE = "widgets.xml"
BACKGROUNDS_FILE = "backgrounds.xml"
PROPERTIES_FILE = "properties.xml"
TEMPLATES_FILE = "templates.xml"
VIEWS_FILE = "views.xml"
INCLUDES_FILE = "script-skinshortcuts-includes.xml"

DEFAULT_ICON = "DefaultShortcut.png"
DEFAULT_TARGET = "videos"
DEFAULT_VIEW_PREFIX = "ShortcutView_"

WIDGET_TYPES = frozenset(
    {
        "movies",
        "tvshows",
        "episodes",
        "musicvideos",
        "artists",
        "albums",
        "songs",
        "pvr",
        "pictures",
        "programs",
        "addons",
        "files",
        "custom",
    }
)

WIDGET_TARGETS = frozenset(
    {
        "videos",
        "music",
        "pictures",
        "programs",
        "pvr",
        "files",
    }
)

PROPERTY_TYPES = frozenset(
    {
        "select",
        "text",
        "number",
        "bool",
        "image",
        "path",
    }
)


WINDOW_MAP: dict[str, str] = {
    "video": "Videos",
    "videos": "Videos",
    "music": "Music",
    "audio": "Music",
    "pictures": "Pictures",
    "images": "Pictures",
    "programs": "Programs",
    "executable": "Programs",
    "pvr": "TVChannels",
    "tv": "TVChannels",
    "radio": "RadioChannels",
    "livetv": "TVChannels",
    "liveradio": "RadioChannels",
}

TARGET_MAP: dict[str, str] = {
    "video": "videos",
    "videos": "videos",
    "music": "music",
    "audio": "music",
    "pictures": "pictures",
    "images": "pictures",
    "programs": "programs",
    "executable": "programs",
}

ADDONS_SOURCE_MAP: dict[str, tuple[str, str]] = {
    "video": ("addons://sources/video/", "videos"),
    "videos": ("addons://sources/video/", "videos"),
    "audio": ("addons://sources/audio/", "music"),
    "music": ("addons://sources/audio/", "music"),
    "image": ("addons://sources/image/", "pictures"),
    "pictures": ("addons://sources/image/", "pictures"),
    "executable": ("addons://sources/executable/", "programs"),
    "programs": ("addons://sources/executable/", "programs"),
    "game": ("addons://sources/game/", "games"),
    "games": ("addons://sources/game/", "games"),
}


def get_shortcuts_path() -> str:
    """Path to the current skin's shortcuts folder."""
    if not IN_KODI:
        return ""
    return xbmcvfs.translatePath("special://skin/shortcuts/")


def extract_path_from_action(action: str) -> str:
    """Extract the bare content path from a full action string."""
    lower = action.lower()
    if lower.startswith("activatewindow("):
        inner = action[15:-1]
        parts = inner.split(",")
        if len(parts) >= 2:
            return parts[1].strip()
    elif lower.startswith("playmedia("):
        return action[10:-1]
    elif lower.startswith("runaddon("):
        addon_id = action[9:-1]
        return f"plugin://{addon_id}/"
    return action


NODE_LABELS = {
    "tvshows": "TV shows",
    "musicvideos": "Music videos",
    "inprogresstvshows": "In progress TV shows",
    "recentlyaddedmovies": "Recently added movies",
    "recentlyaddedepisodes": "Recently added episodes",
    "recentlyaddedmusicvideos": "Recently added music videos",
    "recentlyaddedalbums": "Recently added albums",
    "recentlyplayedalbums": "Recently played albums",
    "pvr": "PVR",
    "musicdb": "Music",
    "videodb": "Video",
}

PATH_SCHEMES = ("videodb://", "musicdb://", "library://", "addons://", "pvr://")


def _addon_name(addon_id: str) -> str:
    """Installed add-on's display name, empty when it cannot be resolved."""
    if not IN_KODI or not addon_id:
        return ""
    try:
        import xbmcaddon

        return xbmcaddon.Addon(addon_id).getAddonInfo("name")
    except (ImportError, RuntimeError):
        return ""


def _prettify_node(segment: str) -> str:
    """One path segment as a reader would say it."""
    key = segment.lower()
    if key in NODE_LABELS:
        return NODE_LABELS[key]
    return segment.replace("_", " ").replace("-", " ").capitalize()


def describe_path(path: str) -> str:
    """Readable twin of a content path, for showing a user instead of the path.

    The management dialog already exposes `path`, which is a machine string:
    videodb://movies/titles/, or plugin://plugin.video.example/?mode=12. A skin
    that puts it on screen, as a "Change action" row does, shows exactly that.
    This renders the same value as "Movies / Titles" or the add-on's own name.

    Named pathLabel where it is set, following the {base}Label convention the
    add-on already uses for widgetLabel and backgroundLabel.

    Total: an unrecognised path falls back to itself, so the worst case is what
    the skin displayed before, never blank.
    """
    if not path:
        return ""

    if path.startswith("plugin://"):
        addon_id = path[len("plugin://") :].split("/", 1)[0].split("?", 1)[0]
        return _addon_name(addon_id) or addon_id or path

    trimmed = path.split("?", 1)[0]
    for scheme in PATH_SCHEMES:
        if trimmed.startswith(scheme):
            segments = [s for s in trimmed[len(scheme) :].split("/") if s]
            # library:// repeats the window as its first segment (library://video/),
            # which says nothing the rest of the path does not.
            if scheme == "library://" and len(segments) > 1:
                segments = segments[1:]
            if not segments:
                return _prettify_node(scheme[:-3])
            return " / ".join(_prettify_node(s) for s in segments)

    # A file-system style path is identified by its folder, not its whole route.
    segments = [s for s in trimmed.replace("\\", "/").split("/") if s and not s.endswith(":")]
    if len(segments) > 1:
        return segments[-1]
    return path
