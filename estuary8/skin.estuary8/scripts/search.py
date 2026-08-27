# -*- coding: utf-8 -*-
"""Multi-provider streaming search for Estuary 8.

Behaviour ported from FENtastic Plus' script.fentastic.helper search_utils
(keyboard prompt, skin strings, provider fan-out). Reskinned to live inside the
skin: no companion add-on, invoked via
RunScript(special://skin/scripts/search.py,mode=...). Results open in the
standard Videos window, so the old search-history recording is gone.
"""
import sys
from urllib.parse import quote

import xbmc
import xbmcgui

# Variables
WINDOW_HOME = 10000
WINDOW_VIDEOS = 10025

# The skin's existing List view (View_50_List, "List"): the stock single-column
# list, the container control id Container.SetViewMode expects. Results are
# forced into it so streaming search shows a plain readable list rather than the
# Videos window's default view. No view is created; this only selects one that
# already ships.
LIST_VIEW_ID = 50

# Per-provider MOVIE search paths, taken verbatim from the content_path values
# declared in xml/Custom_1107_SearchDialog.xml. The query is URL-encoded and
# substituted in place of the skin's
# $INFO[Skin.String(SearchInputEncoded)] token. Keyed by current_search_provider
# id: 0 TMDb Helper, 1 Fen Light, 2 Umbrella, 3 POV, 4 The Gears, 5 Red Light.
PROVIDER_MOVIE_SEARCH = {
    "0": "plugin://plugin.video.themoviedb.helper/?info=search&tmdb_type=movie&query={q}",
    "1": "plugin://plugin.video.fenlight/?mode=build_movie_list&action=tmdb_movies_search&query={q}",
    "2": "plugin://plugin.video.umbrella/?action=movieSearchterm&name={q}",
    "3": "plugin://plugin.video.pov/?mode=build_movie_list&action=tmdb_movies_search&query={q}",
    "4": "plugin://plugin.video.gears/?mode=build_movie_list&action=tmdb_movies_search&query={q}",
    "5": "plugin://plugin.video.redlight/?mode=build_movie_list&action=tmdb_movies_search&query={q}",
}

# Per-provider TV SHOW search paths, the TV counterpart of the map above, taken
# verbatim from the TV-row content_path values in FENtastic's
# Custom_1121_SearchResults.xml. Used only for the unfiltered fallback when the
# filter plugin is absent; the filter plugin carries its own copy.
PROVIDER_TVSHOW_SEARCH = {
    "0": "plugin://plugin.video.themoviedb.helper/?info=search&tmdb_type=tv&query={q}",
    "1": "plugin://plugin.video.fenlight/?mode=build_tvshow_list&action=tmdb_tv_search&isFolder=true&query={q}",
    "2": "plugin://plugin.video.umbrella/?action=tvSearchterm&name={q}",
    "3": "plugin://plugin.video.pov/?mode=build_tvshow_list&action=tmdb_tv_search&query={q}",
    "4": "plugin://plugin.video.gears/?mode=build_tvshow_list&action=tmdb_tv_search&query={q}",
    "5": "plugin://plugin.video.redlight/?mode=build_tvshow_list&action=tmdb_tv_search&isFolder=true&query={q}",
}


def search_input(search_term=None):
    # Behaviour-only gate for the Home search button. When streaming search
    # is disabled the magnifier (control 801) falls back to the skin's
    # simple search dialog (window 1107) instead of running a provider
    # search. This changes only the ACTION; the button is never hidden.
    # Only the fresh-prompt path (no term) is redirected, so re_search is
    # unaffected.
    if not search_term and not xbmc.getCondVisibility(
        "Skin.HasSetting(StreamingSearch)"
    ):
        xbmc.executebuiltin("ActivateWindow(1107)")
        return

    if not search_term or not search_term.strip():
        title = (
            "Search"
            if xbmcgui.getCurrentWindowId() == WINDOW_HOME
            else "New Search"
        )
        kb = xbmc.Keyboard("", title)
        kb.doModal()
        if not kb.isConfirmed():
            return
        search_term = kb.getText().strip()
        if not search_term:
            return

    search_term = search_term.strip()
    encoded = quote(search_term)

    # Resolve the active provider (default to TMDb Helper if unset).
    provider = (
        xbmc.getInfoLabel("Skin.String(current_search_provider)") or "0"
    )

    # The two category toggles in Skin Settings. They are stored as the
    # opt-OUT flags HideMovieResults / HideTVShowResults, so the DEFAULT
    # (neither set) is both categories on, which is what the filter plugin
    # also defaults to. "Search Movies" ON == HideMovieResults unset.
    want_movies = (
        0 if xbmc.getCondVisibility("Skin.HasSetting(HideMovieResults)") else 1
    )
    want_tvshows = (
        0 if xbmc.getCondVisibility("Skin.HasSetting(HideTVShowResults)") else 1
    )

    # Route the results through plugin.video.estuary8.search, our own filter
    # plugin. It reads the provider's search as a directory, drops the
    # art-less placeholder cards (POV's box_office.png results and the
    # item_next.png "Next Page" card), and re-serves the survivors with their
    # original playable paths, so the poster wall shows only real art. The
    # provider add-on is never forked; the filter plugin carries the same
    # provider map and reads POV exactly as Kodi would. If the filter plugin
    # is not installed we fall back to the provider's own search path, so
    # search still works unfiltered rather than breaking.
    SEARCH_FILTER_ADDON = "plugin.video.estuary8.search"
    if xbmc.getCondVisibility(f"System.HasAddon({SEARCH_FILTER_ADDON})"):
        path = (
            f"plugin://{SEARCH_FILTER_ADDON}/"
            f"?provider={provider}&query={encoded}"
            f"&movies={want_movies}&tvshows={want_tvshows}"
        )
    else:
        # No filter plugin: fall back to the provider's own search. The
        # fallback can only carry one category, so honour the toggles with
        # movies taking precedence, then TV shows.
        if want_movies:
            fallback_map = PROVIDER_MOVIE_SEARCH
        elif want_tvshows:
            fallback_map = PROVIDER_TVSHOW_SEARCH
        else:
            fallback_map = PROVIDER_MOVIE_SEARCH
        path = fallback_map.get(provider, fallback_map["0"]).format(q=encoded)

    # Preserve the search strings the rest of the skin reads (run_last_search
    # reads SearchInput; SearchInputEncoded feeds the skin's search token).
    xbmc.executebuiltin(f"Skin.SetString(SearchInput,{search_term})")
    xbmc.executebuiltin(f"Skin.SetString(SearchInputEncoded,{encoded})")
    xbmc.executebuiltin(f"Skin.SetString(SearchInputTraktEncoded,{encoded})")

    # Open the results in the standard Videos window (MyVideoNav, 10025),
    # which already carries Estuary 8's real top bar and poster layout,
    # using the filter plugin path (or the provider's own path as fallback)
    # resolved above.
    xbmc.executebuiltin(f'ActivateWindow(Videos,"{path}",return)')

    # Force the skin's existing List view (id 50) for the results.
    # ActivateWindow returns before the Videos window is up and the provider
    # has populated it, so Container.SetViewMode would otherwise land on the
    # Home container that launched the search. Wait for the Videos window and
    # its content, then set the view once. The filter plugin serves content
    # "videos" (movies plus TV shows together); the unfiltered provider
    # fallback may serve "movies" or "tvshows", so accept any of the three.
    monitor = xbmc.Monitor()
    for _ in range(50):
        if monitor.waitForAbort(0.1):
            return
        if xbmcgui.getCurrentWindowId() == WINDOW_VIDEOS and (
            xbmc.getCondVisibility("Container.Content(videos)")
            or xbmc.getCondVisibility("Container.Content(movies)")
            or xbmc.getCondVisibility("Container.Content(tvshows)")
        ):
            xbmc.executebuiltin(
                f"Container.SetViewMode({LIST_VIEW_ID})"
            )
            break


def re_search(term=None):
    if not term:
        xbmc.log(
            "Estuary8 search: re_search called with empty query", xbmc.LOGWARNING
        )
        return
    search_input(term)


def run_last_search():
    search_term = xbmc.getInfoLabel("Skin.String(SearchInput)")

    if not search_term:
        xbmc.executebuiltin(
            "RunScript(special://skin/scripts/search.py,mode=search_input)"
        )
        return

    # Re-run the last term through the current provider, into Videos.
    search_input(search_term)


def change_search_provider():
    providers = [
        ("0", "TMDb Helper", "plugin.video.themoviedb.helper"),
        ("1", "Fen Light", "plugin.video.fenlight"),
        ("2", "Umbrella", "plugin.video.umbrella"),
        ("3", "POV", "plugin.video.pov"),
        ("4", "The Gears", "plugin.video.gears"),
        ("5", "Red Light", "plugin.video.redlight"),
    ]

    installed = [
        (pid, name, addon_id)
        for pid, name, addon_id in providers
        if xbmc.getCondVisibility(f"System.HasAddon({addon_id})")
    ]

    if not installed:
        xbmcgui.Dialog().notification(
            "Estuary 8", "No search providers are installed"
        )
        return

    current = xbmc.getInfoLabel("Skin.String(current_search_provider)")

    labels = [name for pid, name, addon_id in installed]

    preselect = 0
    for idx, (pid, name, addon_id) in enumerate(installed):
        if pid == current:
            preselect = idx
            break

    choice = xbmcgui.Dialog().select(
        "Choose Search Provider", labels, preselect=preselect
    )

    if choice < 0:
        return

    provider_id, _provider_name, _addon_id = installed[choice]

    # No change
    if provider_id == current:
        return

    # Selecting a provider is CONFIGURATION ONLY. Record the choice and return,
    # staying in Skin Settings. It must never launch a search: the Home
    # magnifier (control 801) is the only control that ever starts one. Earlier
    # builds ended here with ActivateWindow(home) followed by run_last_search(),
    # which on a fresh or wiped profile (no prior SearchInput) threw the user
    # straight into a keyboard the instant they picked a provider while enabling
    # streaming search.
    xbmc.executebuiltin(
        f"Skin.SetString(current_search_provider,{provider_id})"
    )


def _parse_args():
    """RunScript passes each comma-separated token as its own argv entry."""
    params = {}
    for arg in sys.argv[1:]:
        if "=" in arg:
            key, value = arg.split("=", 1)
            params[key] = value
    return params


def main():
    params = _parse_args()
    mode = params.get("mode", "search_input")
    query = params.get("query")

    if mode == "search_input":
        search_input()
    elif mode == "re_search":
        re_search(query)
    elif mode == "select_search_provider":
        change_search_provider()
    else:
        xbmc.log(f"Estuary8 search: unknown mode {mode!r}", xbmc.LOGWARNING)


if __name__ == "__main__":
    main()
