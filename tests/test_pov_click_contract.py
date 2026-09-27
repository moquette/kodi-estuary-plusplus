"""POV widget items must be invoked with RunPlugin, never as a play resolution.

The defect this pins down, measured on the Kodi 22 macOS bench on 2026-08-30:
selecting a movie from a Home row went through CDirectoryProvider::OnClick,
which turns any non-folder video item into PlayMedia. PlayMedia starts Kodi's
playback resolution and waits for setResolvedUrl, but POV never calls it on any
code path (its only wrapper in modules/kodi_utils.py has zero callers; POV plays
via xbmc.Player from inside the script). Backing out of the source results left
that resolution to die, PlayListPlayer counted it as a failed item, and once an
unanswered failure was more than 20 seconds old (advancedsettings
playlisttimeout, PlayListPlayer.cpp) the next one raised the modal "Playback
failed. One or more items failed to play." Under 20 seconds it was silent, which
is exactly the randomness the owner reported.

The fix is a conditional container onclick in WidgetListPoster: POV non-folder
items go out as RunPlugin, the same handle -1 invocation Kodi's own media
windows already use for non-IsPlayable plugin items, so there is no play
contract to abandon. Folder items (TV shows) fall through to the default browse
(GUIBaseContainer.cpp only bypasses the provider when an onclick condition
matches).

Both halves are asserted here: the onclick must stay in every include that
renders a POV row, and every POV row must keep using an include that has it. A
new widget include adopted for POV rows without the onclick would quietly bring
the dialog back, with nothing in any log to say why.
"""

import pathlib
import re

ROOT = pathlib.Path(__file__).resolve().parent.parent
XML = ROOT / "skin.estuary.plusplus" / "xml"

HOME = (XML / "Home.xml").read_text(encoding="utf-8")
INCLUDES = (XML / "Includes_Home.xml").read_text(encoding="utf-8")

ONCLICK = (
    '<onclick condition="String.Contains(ListItem.FilenameAndPath,plugin.video.pov)'
    ' + !ListItem.IsFolder">RunPlugin($ESCINFO[ListItem.FilenameAndPath])</onclick>'
)


def include_body(name: str) -> str:
    """The text of one <include name=...> block in Includes_Home.xml."""
    match = re.search(
        r'<include name="%s">.*?\n\t</include>' % re.escape(name), INCLUDES, re.DOTALL
    )
    assert match, f"include {name} not found in Includes_Home.xml"
    return match.group(0)


def pov_row_includes() -> set[str]:
    """Every include name used with a plugin.video.pov content_path in Home.xml."""
    names = set()
    for match in re.finditer(r'<include content="([^"]+)"[^>]*>(.*?)</include>', HOME, re.DOTALL):
        if "plugin.video.pov" in match.group(2) and "content_path" in match.group(2):
            names.add(match.group(1))
    assert names, "no POV widget rows found in Home.xml; the regex or the file moved"
    return names


def test_every_pov_row_include_carries_the_runplugin_onclick():
    for name in sorted(pov_row_includes()):
        body = include_body(name)
        assert ONCLICK in body, (
            f"{name} renders POV rows but has no RunPlugin onclick for POV items. "
            "Selecting a movie there starts a playback resolution POV never "
            "answers, and backing out of the source results brings back the "
            '"One or more items failed to play" dialog.'
        )


def test_the_onclick_excludes_folders_so_tvshow_rows_still_browse():
    # The negated IsFolder is what keeps TV show and season folders on the
    # default browse action. Dropping it would RunPlugin a directory URL,
    # which renders nothing and eats the click.
    assert "!ListItem.IsFolder" in ONCLICK
    assert INCLUDES.count(ONCLICK) >= 1
