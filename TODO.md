# TODO

## Revisit the Categories widgets on Movies and TV Shows

Both tabs lost their "Categories" row (`$LOCALIZE[31148]`) when the stock
library rows were replaced with POV rows. That was deliberate, per the
"POV rows only" decision, but it is worth a second look.

**What was removed.** A `WidgetListCategories` row at the top of each tab,
fed from `library://video/movies/` and `library://video/tvshows/`. It
rendered the horizontal strip of navigation buttons: Titles, Genres, Years,
Actors, Sets, Studios. Both were gated on `Library.HasContent(...)`, so they
only appeared when the local library had content.

The Movies one also carried `additional_movie_items="true"`, which appends
In Theaters, Upcoming and Next Aired via `MovieSubmenuItems`. Those route to
`script.embuary.info`, which is not installed on the bedroom box, so they
were dead buttons there regardless. The TV one has the same arrangement
through `additional_tvshow_items`.

To restore either verbatim, take the row from the baseline commit:

    git show aa31e34:skin.estuary.mymod/xml/Home.xml | sed -n '54,60p'   # movies
    git show aa31e34:skin.estuary.mymod/xml/Home.xml | sed -n '85,91p'   # tvshows

**The open question is which categories row belongs there.** The stock one
navigates the local Kodi library, which sits oddly on a tab where every
other row is POV, and vanishes entirely on a box with no library. A POV
equivalent pointed at `?mode=navigator.main&action=MovieList` (or
`TVShowList`) would be coherent with the rest of the tab, has no library
dependency, and is the same destination the main-menu item now opens.

Undecided: POV, stock library, or both; and whether it sits above the
In Progress row where it used to be, or below the poster rows.

## Install-from-zip over NFS fails on the bedroom box

Installing `skin.estuary.mymod.zip` from `nfs://192.168.7.2/Users/moquette/
Kodi/Share/rollback/` failed on 2026-08-27:

    CAddonInfoBuilder::Generate: Unable to load 'zip://nfs%3a%2f%2f.../
    skin.estuary.mymod.zip/skin.estuary.mymod/addon.xml', Line: 0, Error:

`Line: 0` with an empty error is tinyxml2's file-could-not-be-opened, so
Kodi never read the bytes; it was not rejecting the XML.

Ruled out by measurement: the archive is valid (`unzip -t` clean, deflate,
no data descriptor, no Zip64, no extra fields); mini's copy is SHA256
identical to the build; the same file reads correctly over the same NFS
export from another machine; there was no stale copy in `addons/packages/`;
and the skin was not active at the time.

So the fault is in Kodi's bundled libnfs plus zip VFS on that device.
Unproven theory: `CZipManager` caches a zip's central directory keyed by
path and invalidates on size and mtime, and the file was replaced at a path
Kodi had already read while keeping the same name; stale NFS attributes
would then have it seeking to old offsets in a new file.

Worked around by pushing the changed files over adb, not fixed. A Kodi
restart has happened since, which would clear any such cache, so the NFS
path may simply work now. A verified-good local copy is at
`/sdcard/Download/skin.estuary.mymod.zip` on the bedroom box for a clean
test, though the files are already current, so a meaningful test means
reverting them to 4.1.0 first.
