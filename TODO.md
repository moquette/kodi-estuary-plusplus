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
