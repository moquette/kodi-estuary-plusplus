#
# Estuary 8 Search Filter
# Copyright (C) 2026 Tony.7.Bones
#
# This program is free software; you can redistribute it and/or modify it
# under the terms of the GNU General Public License as published by the Free
# Software Foundation; either version 2 of the License, or (at your option)
# any later version.
#
# This program is distributed in the hope that it will be useful, but WITHOUT
# ANY WARRANTY; without even the implied warranty of MERCHANTABILITY or FITNESS
# FOR A PARTICULAR PURPOSE. See the GNU General Public License for more details.
#
# SPDX-License-Identifier: GPL-2.0-only
"""Art-less-result filter for Estuary 8's streaming search.

Opened as::

    plugin://plugin.video.estuary8.search/?provider=<id>&query=<url-encoded>
        [&movies=<0|1>&tvshows=<0|1>]

it resolves the underlying provider's own movie and/or TV-show search
directories for that provider id, reads each as a DIRECTORY through JSON-RPC
``Files.GetDirectory``, drops the items that carry no real poster (POV's
``box_office.png`` art-less cards and its ``item_next.png`` "Next Page" card),
and re-serves the survivors with their original label, art, info and playable
path intact. ALL surviving movies are served first, then ALL surviving TV
shows. The ``movies`` and ``tvshows`` flags select which categories to pull;
both default on when absent.

The provider add-ons are never forked or modified. They are read exactly as
Kodi would navigate them, so PLAY and folder navigation still run through the
provider unchanged. The only thing this plugin does is withhold the junk.
"""

import json
import sys
from urllib.parse import parse_qsl, quote, unquote

import xbmc
import xbmcgui
import xbmcplugin

ADDON_ID = "plugin.video.estuary8.search"

# Per-provider MOVIE search paths, carried verbatim from the skin's
# scripts/search.py PROVIDER_MOVIE_SEARCH map. Keyed by current_search_provider
# id: 0 TMDb Helper, 1 Fen Light, 2 Umbrella, 3 POV, 4 The Gears, 5 Red Light.
# The query is url-encoded and substituted for {q}.
PROVIDER_MOVIE_SEARCH = {
    "0": "plugin://plugin.video.themoviedb.helper/?info=search&tmdb_type=movie&query={q}",
    "1": "plugin://plugin.video.fenlight/?mode=build_movie_list&action=tmdb_movies_search&query={q}",
    "2": "plugin://plugin.video.umbrella/?action=movieSearchterm&name={q}",
    "3": "plugin://plugin.video.pov/?mode=build_movie_list&action=tmdb_movies_search&query={q}",
    "4": "plugin://plugin.video.gears/?mode=build_movie_list&action=tmdb_movies_search&query={q}",
    "5": "plugin://plugin.video.redlight/?mode=build_movie_list&action=tmdb_movies_search&query={q}",
}

# Per-provider TV SHOW search paths, the TV counterpart of PROVIDER_MOVIE_SEARCH.
# Carried verbatim from the TV-row content_path values in the in-repo FENtastic
# reference build/skin.fentastic/xml/Custom_1121_SearchResults.xml, keyed by the
# same provider id: 0 TMDb Helper, 1 Fen Light, 2 Umbrella, 3 POV, 4 The Gears,
# 5 Red Light. The query is url-encoded and substituted for {q}.
PROVIDER_TVSHOW_SEARCH = {
    "0": "plugin://plugin.video.themoviedb.helper/?info=search&tmdb_type=tv&query={q}",
    "1": "plugin://plugin.video.fenlight/?mode=build_tvshow_list&action=tmdb_tv_search&isFolder=true&query={q}",
    "2": "plugin://plugin.video.umbrella/?action=tvSearchterm&name={q}",
    "3": "plugin://plugin.video.pov/?mode=build_tvshow_list&action=tmdb_tv_search&query={q}",
    "4": "plugin://plugin.video.gears/?mode=build_tvshow_list&action=tmdb_tv_search&query={q}",
    "5": "plugin://plugin.video.redlight/?mode=build_tvshow_list&action=tmdb_tv_search&isFolder=true&query={q}",
}

# Poster art whose path contains one of these is a provider placeholder, not a
# real poster. box_office.png is POV's art-less fallback; item_next.png is its
# "Next Page" navigation card. Both arrive url-encoded inside an image:// wrapper
# (e.g. ...media%2fbox_office.png/), so a lowercase substring test catches them.
PLACEHOLDER_MARKERS = ("box_office.png", "item_next.png")

# Item properties requested from the provider directory. Measured valid for
# Files.GetDirectory (List.Fields.Files) against plugin.video.pov on Kodi 22.
DIRECTORY_PROPERTIES = [
    "title",
    "art",
    "plot",
    "plotoutline",
    "year",
    "premiered",
    "genre",
    "director",
    "studio",
    "mpaa",
    "rating",
    "runtime",
    "mimetype",
    "file",
]


def _log(message, level=xbmc.LOGINFO):
    xbmc.log(f"{ADDON_ID}: {message}", level)


def _has_real_poster(item):
    """True only when the item carries a genuine poster (not empty, not a
    provider placeholder)."""
    art = item.get("art") or {}
    poster = (art.get("poster") or "").strip()
    if not poster:
        return False
    low = poster.lower()
    return not any(marker in low for marker in PLACEHOLDER_MARKERS)


def _fetch_directory(directory):
    """Read the provider's search directory in-process via JSON-RPC. Returns the
    provider's own item dicts, or an empty list on error."""
    request = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "Files.GetDirectory",
        "params": {
            "directory": directory,
            "media": "video",
            "properties": DIRECTORY_PROPERTIES,
        },
    }
    try:
        raw = xbmc.executeJSONRPC(json.dumps(request))
        data = json.loads(raw)
    except (ValueError, TypeError) as exc:
        _log(f"Files.GetDirectory could not be parsed: {exc}", xbmc.LOGERROR)
        return []
    if "error" in data:
        _log(f"Files.GetDirectory failed: {data['error']}", xbmc.LOGERROR)
        return []
    return data.get("result", {}).get("files", []) or []


def _as_list(value):
    if not value:
        return []
    return value if isinstance(value, list) else [value]


def _build_listitem(item, media_type):
    """Rebuild a ListItem that preserves the provider item's label, art and
    info. media_type is "movie" or "tvshow". The playable path is set by the
    caller from item['file']."""
    label = item.get("label") or item.get("title") or ""
    li = xbmcgui.ListItem(label=label)

    art = item.get("art") or {}
    if art:
        li.setArt(art)

    # Info via the InfoTagVideo API (the non-deprecated path on Kodi Piers).
    # Guard every field so a missing or odd value can never abort the listing.
    try:
        tag = li.getVideoInfoTag()
        tag.setMediaType(media_type)
        title = item.get("title") or label
        if title:
            tag.setTitle(title)
        if item.get("plot"):
            tag.setPlot(item["plot"])
        if item.get("plotoutline"):
            tag.setPlotOutline(item["plotoutline"])
        year = item.get("year")
        if isinstance(year, int) and year > 0:
            tag.setYear(year)
        if item.get("premiered"):
            tag.setPremiered(item["premiered"])
        genres = _as_list(item.get("genre"))
        if genres:
            tag.setGenres(genres)
        directors = _as_list(item.get("director"))
        if directors:
            tag.setDirectors(directors)
        studios = _as_list(item.get("studio"))
        if studios:
            tag.setStudios(studios)
        if item.get("mpaa"):
            tag.setMpaa(item["mpaa"])
        rating = item.get("rating")
        if isinstance(rating, (int, float)) and rating > 0:
            tag.setRating(float(rating))
    except (RuntimeError, TypeError, ValueError) as exc:
        _log(f"info tag partially set for {label!r}: {exc}", xbmc.LOGWARNING)

    return li


def _serve_placeholder(handle):
    """Serve a single non-folder placeholder instead of an empty directory.

    Kodi's stock media window (``CGUIMediaWindow`` on Kodi 22) inserts a ``..``
    parent item as the sole entry whenever the returned file list is EMPTY, and
    that fallback deliberately ignores the ``filelists.showparentdiritems``
    setting ("this check MUST be last and ignore the hide parent fileitems
    settings"). A search result wall must never show a back-arrow as its first
    item, so when nothing survives filtering we return one non-navigable
    informational card. The list is then non-empty, the empty-list fallback
    never fires, and the wall shows "No matching results" rather than "..".
    """
    li = xbmcgui.ListItem(label="No matching results")
    li.setProperty("IsPlayable", "false")
    try:
        tag = li.getVideoInfoTag()
        tag.setMediaType("movie")
        tag.setTitle("No matching results")
    except (RuntimeError, TypeError, ValueError):
        pass
    # isFolder=False keeps the card non-navigable, so it carries no parent path.
    xbmcplugin.addDirectoryItem(handle, "", li, isFolder=False)


def _parse_params(argv):
    query_string = argv[2] if len(argv) > 2 else ""
    query_string = query_string.removeprefix("?")
    return dict(parse_qsl(query_string))


def _flag(params, name):
    """Read a &<name>=<0|1> plugin flag. Absent or unparseable defaults to on,
    so an old skin that passes neither flag still gets both categories."""
    value = params.get(name)
    if value is None:
        return True
    return value.strip() != "0"


def _collect(provider, query, search_map, media_type):
    """Fetch one category's provider directory, drop the art-less junk, and
    return (kept_entries, total_from_provider). Order within the category is the
    provider's own order, preserved."""
    template = search_map.get(provider, search_map["0"])
    directory = template.format(q=quote(query))

    items = _fetch_directory(directory)
    entries = []
    for item in items:
        if not _has_real_poster(item):
            continue
        li = _build_listitem(item, media_type)
        url = item.get("file") or ""
        is_folder = item.get("filetype") == "directory"
        if not is_folder:
            li.setProperty("IsPlayable", "true")
        entries.append((url, li, is_folder))
    return entries, len(items)


def run(argv):
    handle = int(argv[1])
    params = _parse_params(argv)

    provider = params.get("provider", "0")
    query = unquote(params.get("query", ""))
    want_movies = _flag(params, "movies")
    want_tvshows = _flag(params, "tvshows")

    if not query.strip():
        _log("no query supplied; serving a placeholder card", xbmc.LOGWARNING)
        xbmcplugin.setContent(handle, "movies")
        _serve_placeholder(handle)
        xbmcplugin.endOfDirectory(handle, succeeded=True, cacheToDisc=False)
        return

    # ALL surviving movies first, then ALL surviving TV shows, each in its own
    # provider order. Kodi keeps this insertion order because the only sort
    # method offered below is UNSORTED.
    entries = []
    movie_kept = movie_total = tv_kept = tv_total = 0
    if want_movies:
        movie_entries, movie_total = _collect(provider, query, PROVIDER_MOVIE_SEARCH, "movie")
        movie_kept = len(movie_entries)
        entries.extend(movie_entries)
    if want_tvshows:
        tv_entries, tv_total = _collect(provider, query, PROVIDER_TVSHOW_SEARCH, "tvshow")
        tv_kept = len(tv_entries)
        entries.extend(tv_entries)

    _log(
        f"provider {provider} query {query!r}: "
        f"movies want={want_movies} {movie_kept}/{movie_total} kept, "
        f"tv want={want_tvshows} {tv_kept}/{tv_total} kept, "
        f"{len(entries)} total served"
    )

    xbmcplugin.setPluginCategory(handle, f"Search: {query}")
    xbmcplugin.setContent(handle, "movies")
    if entries:
        xbmcplugin.addDirectoryItems(handle, entries, len(entries))
    else:
        # Nothing survived filtering. Serve a placeholder rather than an empty
        # directory so Kodi's empty-list fallback cannot make ".." item 0.
        _serve_placeholder(handle)
    xbmcplugin.addSortMethod(handle, xbmcplugin.SORT_METHOD_UNSORTED)
    xbmcplugin.endOfDirectory(handle, succeeded=True, cacheToDisc=False)


if __name__ == "__main__":
    run(sys.argv)
