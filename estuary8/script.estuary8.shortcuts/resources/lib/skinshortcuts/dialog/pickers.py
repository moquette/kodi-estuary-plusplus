"""Picker dialogs mixin - shortcut, widget, background pickers."""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Any, Callable, Literal, Protocol, runtime_checkable

try:
    import xbmc
    import xbmcgui

    IN_KODI = True
except ImportError:
    IN_KODI = False


def _check_visible(visible: str) -> bool:
    """Evaluate a Kodi visibility condition.

    Returns True if condition passes or is empty.
    """
    if not visible:
        return True
    if not IN_KODI:
        return True
    return xbmc.getCondVisibility(visible)


@runtime_checkable
class PickerItem(Protocol):
    """Protocol for leaf items in picker hierarchy (Shortcut, Widget, Background)."""

    name: str
    label: str
    icon: str
    condition: str
    visible: str


@runtime_checkable
class PickerGroup(Protocol):
    """Protocol for group items in picker hierarchy."""

    name: str
    label: str
    icon: str
    condition: str
    visible: str
    items: list


from ..constants import ADDONS_SOURCE_MAP, WINDOW_MAP, extract_path_from_action
from ..loaders import evaluate_condition, load_groupings
from ..localize import LANGUAGE, resolve_label
from ..playlists import (
    SORT_OPTIONS,
    SortOption,
    build_smartplaylist_xml,
    display_options,
    path_has_content,
    save_playlist,
    unpack_multipath,
)
from ..models import (
    Action,
    Background,
    BackgroundGroup,
    Content,
    Input,
    MenuItem,
    Shortcut,
    ShortcutGroup,
    Widget,
    WidgetGroup,
)
from ..providers import ContentProvider, get_browse_provider

if TYPE_CHECKING:
    from ..manager import MenuManager


def _browse_placeholder_for_content(
    content: Content, *, as_widget: bool = False, parent_label: str = ""
) -> Shortcut | Widget | None:
    """Create a "Create menu item to here" placeholder for an addons content section.

    Returns a Shortcut (shortcut picker) or Widget (widget picker) pointing at
    addons://sources/<type>/, so users can commit a menu item or widget to the
    addon category root even when no addons of that type are installed.
    """
    if content.source.lower() != "addons":
        return None

    target = content.target.lower() if content.target else "video"
    if target not in ADDONS_SOURCE_MAP:
        return None

    path, window = ADDONS_SOURCE_MAP[target]
    name = f"content-placeholder-{content.source}-{target}"
    icon = content.icon if content.icon else "DefaultFolder.png"

    label = content.label or parent_label or LANGUAGE(32058)

    if as_widget:
        return Widget(
            name=name,
            label=label,
            path=path,
            type=target,
            target=window,
            icon=icon,
            source="addon",
        )

    return Shortcut(
        name=name,
        label=label,
        actions=[f"ActivateWindow({window},{path},return)"],
        icon=icon,
    )


class PickersMixin:
    """Mixin providing picker dialogs for shortcuts and widgets.

    This mixin implements:
    - Shortcut picker from groupings
    - Widget picker from groups/flat list
    - Content resolution (dynamic shortcuts/widgets)

    Requires DialogBaseMixin to be mixed in first.
    """

    menu_id: str
    shortcuts_path: str
    manager: MenuManager | None
    items: list[MenuItem]

    # CANCEL MEANS CANCEL, AT EVERY DEPTH, IN ONE PRESS.
    #
    # Every dialog the picker opens is an xbmcgui.Dialog().select(), and every
    # one of them reports Back the same way: -1. Upstream reads that as "go up
    # one level" and loops round to redraw the level above, so a pick that is
    # four levels deep needs five presses to abandon.
    #
    # That is what trapped the owner on a Fire TV stick on 2026-07-31. Each
    # level of a browse listing puts "Create menu item to here" at index 0 with
    # no preselect, so every redraw presents the same window and the same
    # focused first row as the one before. He pressed Back four times, read the
    # same first row four times, and reasonably concluded the dialog could not
    # be dismissed. Only Application.Quit got him out.
    #
    # Precisely: the BODY repeats, not the whole screen. The heading does change
    # with the folder, because the browse loop sets dialog_title from
    # current_label. An earlier version of this note, and the 3.0.1.2 release
    # note, both claimed the title bar was identical too. It is not, and the
    # claim is not needed: a listing whose first row and focus never move is
    # already enough to read as a dead end.
    #
    # So this flag makes one rule out of it: a -1 anywhere sets it, and every
    # loop that would otherwise redraw checks it and returns instead. One press
    # of Back leaves the whole picker and lands back on the management dialog,
    # from any depth, in every picker (shortcut, widget, background, browse and
    # the keyboard). It is reset by the entry point of each pick, never by an
    # inner level, so it cannot leak into the next press of the button.
    #
    # KNOWN TRADE-OFF, stated rather than hidden: stepping back up ONE level of
    # a deep add-on browse is gone with it, because -1 is the only signal Kodi
    # gives and it cannot mean two things. Re-entering the picker is one button
    # press; being unable to leave it is not recoverable with a remote.
    _picker_cancelled: bool = False

    if TYPE_CHECKING:

        def _get_selected_item(self) -> MenuItem | None: ...
        def _get_item_properties(self, item: MenuItem) -> dict[str, str]: ...
        def _refresh_selected_item(self) -> None: ...
        def _log(self, msg: str) -> None: ...
        def _set_action(self) -> None: ...

    def _begin_pick(self) -> None:
        """Arm a fresh pick. Called by every entry point, never by an inner level."""
        self._picker_cancelled = False

    def _cancel_pick(self) -> None:
        """Record that the user asked to leave. Unwinds the whole picker stack."""
        self._picker_cancelled = True

    def _icon_overrides(self) -> dict[str, str]:
        """Icon override map from the active skin config, empty if none loaded."""
        if self.manager and self.manager.config:
            return self.manager.config.icon_overrides
        return {}

    def _pick_shortcut_actions(
        self, allow_custom: bool = False
    ) -> tuple[MenuItem, Shortcut, list[str]] | None:
        """Run the groupings picker and resolve the picked shortcut's action(s).

        This is the half both shortcut-picking buttons share, so the picking can
        never drift between them; the only difference between the two buttons is
        what each one WRITES afterwards.

        allow_custom adds the "Custom action..." keyboard row to the picker. Only
        "Change action" (control 307) sets it, because that button writes just the
        action; "Choose item for menu" (401) adopts the whole shortcut and a typed
        builtin has no label, icon or submenu to adopt.

        Returns None whenever there is nothing to apply: no manager, no selected
        item, no groupings declared, the picker cancelled, or one of the action
        sub-dialogs (playlist choice, source display, sort order) cancelled. The
        returned action list is never empty.
        """
        if not self.manager:
            return None

        self._begin_pick()

        item = self._get_selected_item()
        if not item:
            return None

        menus_path = Path(self.shortcuts_path) / "menus.xml"
        groups = load_groupings(menus_path, self.menu_id)

        if not groups:
            xbmcgui.Dialog().notification(
                LANGUAGE(32179),
                LANGUAGE(32180),
            )
            return None

        item_props = self._get_item_properties(item)

        shortcut = self._pick_shortcut(groups, item_props, allow_custom=allow_custom)
        if not shortcut:
            return None

        # A file source can become either a Files view or a generated library
        # playlist, and that choice is what builds the action, so it cannot be
        # skipped by a caller that only wants the action.
        if shortcut.source_media:
            action = self._source_playlist_action(shortcut, item)
            actions = [action] if action else None
        else:
            actions = self._get_shortcut_actions(shortcut)
        if actions is None:
            return None

        return item, shortcut, actions

    def _choose_action(self) -> None:
        """Change the selected item's ACTION, and nothing else.

        Skins label control 307 "Change action", but an action is a Kodi builtin
        such as ActivateWindow(Videos,videodb://movies/titles/,return), which is
        not something a user can reasonably type into a keyboard. The groupings
        picker already expresses those destinations by name, so it is used
        whenever the skin declares any.

        ONLY the action is written. The label, the icon, the visibility
        condition and the submenu binding belong to the user's item, not to the
        shortcut that was picked as a destination, and every one of them is left
        exactly as it was. Adopting the whole shortcut is what control 401 is
        for; see _choose_shortcut.

        This method used to delegate straight to _choose_shortcut, and that
        shipped: one press of a button reading "Change action" renamed a
        configured Movies item to "Video add-ons", replaced its artwork with
        DefaultFolder.png, and wrote submenu="" into userdata, which deleted all
        17 rows of its submenu. Measured on a clean Piers bench, 2026-07-31.

        Manual entry is reachable two ways. It is the FIRST row of the picker,
        "Custom action...", which pops a keyboard and writes whatever builtin the
        user types (ActivateWindow(TVGuide), RunScript(...), anything), so no
        destination is out of reach even when the skin's groupings never named
        it; see _pick_shortcut(allow_custom=True) and _prompt_custom_action. It
        is also the whole flow's fallback when the skin declares no groupings at
        all, the only case where the picker would have nothing to show, via
        _set_action. The protection prompt travels with the button rather than
        with the entry method, because what it guards is a change of action, and
        this is the button that changes the action. Delegating to the picker had
        silently dropped it.
        """
        if not self.manager:
            return

        menus_path = Path(self.shortcuts_path) / "menus.xml"
        if not load_groupings(menus_path, self.menu_id):
            # _set_action runs the protection prompt itself, so it is not run
            # here as well; two dialogs for one press would be the regression
            # in the other direction.
            self._set_action()
            return

        item = self._get_selected_item()
        if item and item.protection and item.protection.protects_action():
            heading = resolve_label(item.protection.heading) or LANGUAGE(32132)
            label = resolve_label(item.label)
            message = resolve_label(item.protection.message) or LANGUAGE(32176) % label
            if not xbmcgui.Dialog().yesno(heading, message):
                return

        picked = self._pick_shortcut_actions(allow_custom=True)
        if not picked:
            return
        item, _shortcut, actions = picked

        self.manager.set_action(self.menu_id, item.name, actions)
        item.actions = [Action(action=a) for a in actions]

        self._refresh_selected_item()

    def _choose_shortcut(self) -> None:
        """Adopt a whole shortcut from groupings, replacing the selected item.

        This is control 401, "Choose item for menu". Label, action, icon,
        visibility and submenu binding are all taken from the picked shortcut,
        which is the point of that button. Control 307 changes only the action;
        see _choose_action.
        """
        if not self.manager:
            return

        picked = self._pick_shortcut_actions()
        if not picked:
            return
        item, shortcut, actions = picked

        result_label = shortcut.label
        self.manager.set_label(self.menu_id, item.name, result_label)
        item.label = result_label
        self.manager.set_action(self.menu_id, item.name, actions)
        item.actions = [Action(action=a) for a in actions] if actions else []

        if shortcut.icon:
            self.manager.set_icon(self.menu_id, item.name, shortcut.icon)
            item.icon = shortcut.icon

        if shortcut.item_visible:
            self.manager.set_visible(self.menu_id, item.name, shortcut.item_visible)
            item.visible = shortcut.item_visible

        previous_submenu = item.submenu
        new_submenu: str | None = None
        if shortcut.name:
            template = self.manager.config.get_default_menu(shortcut.name)
            if template and template.is_submenu:
                new_submenu = shortcut.name

        if new_submenu != previous_submenu:
            self.manager.set_submenu(self.menu_id, item.name, new_submenu)
            item.submenu = new_submenu
            self.manager.drop_per_item_submenu(self.menu_id, item.name)

        self._refresh_selected_item()

    def _get_shortcut_actions(self, shortcut: Shortcut) -> list[str] | None:
        """Get actions from shortcut, showing playlist choice dialog if applicable."""
        if shortcut.action_play:
            action = self._choose_playlist_action(shortcut)
            return [action] if action else None
        # Browse mode resolves to a single action
        if shortcut.browse and shortcut.path:
            return [shortcut.get_action()]
        return shortcut.actions if shortcut.actions else None

    def _choose_playlist_action(self, shortcut: Shortcut) -> str | None:
        """Show dialog asking what to do with a playlist shortcut."""
        if shortcut.action_party:
            result = xbmcgui.Dialog().yesnocustom(  # type: ignore[attr-defined]
                LANGUAGE(32040),
                LANGUAGE(32060),
                customlabel=xbmc.getLocalizedString(589),
                nolabel=LANGUAGE(32061),
                yeslabel=LANGUAGE(32062),
            )
            if result == -1:
                return None
            if result == 0:
                return shortcut.action
            if result == 1:
                return shortcut.action_play
            return shortcut.action_party

        result = xbmcgui.Dialog().yesno(
            LANGUAGE(32040),
            LANGUAGE(32060),
            nolabel=LANGUAGE(32061),
            yeslabel=LANGUAGE(32062),
        )
        return shortcut.action_play if result else shortcut.action

    def _source_playlist_action(self, shortcut: Shortcut, item: MenuItem) -> str | None:
        """Pick how to show a source: Files view, or a path-filtered library playlist.

        Returns the action string, or None if cancelled. The option list is built from
        the source's detected library domain; an exclude with no remaining content falls
        back to Files view rather than an empty playlist.
        """
        paths = unpack_multipath(shortcut.path)
        options = display_options(shortcut.source_media, paths)
        if len(options) == 1:
            return shortcut.get_action()  # not a library source -> Files view, no dialog

        labels = [
            xbmc.getLocalizedString(o.label_id) if o.core else LANGUAGE(o.label_id) for o in options
        ]
        choice = xbmcgui.Dialog().select(LANGUAGE(32078), labels)
        if choice == -1:
            self._cancel_pick()
            return None
        option = options[choice]
        if not option.media_type:
            return shortcut.get_action()

        # Include views are populated: detection confirmed the domain's type, albums and
        # artists derive from songs, and a scanned show has episodes. Only an exclude can
        # legitimately empty out (every item of that type sits under this one source).
        if option.exclude and not path_has_content(option.media_type, paths, exclude=True):
            use_files = xbmcgui.Dialog().yesno(
                LANGUAGE(32078),
                LANGUAGE(32205),
                nolabel=xbmc.getLocalizedString(222),
                yeslabel=LANGUAGE(32079),
            )
            return shortcut.get_action() if use_files else None

        sort = self._pick_sort()
        if sort is None:
            return None

        xml = build_smartplaylist_xml(
            option.media_type,
            shortcut.label,
            paths,
            exclude=option.exclude,
            sort_field=sort.field,
            sort_order=sort.direction,
        )
        path = save_playlist(self.menu_id, item.name, xml)
        window = WINDOW_MAP.get(shortcut.source_media, "Videos")
        return f"ActivateWindow({window},{path},return)"

    def _pick_sort(self) -> SortOption | None:
        """Pick a sort order for a generated playlist. None if cancelled."""
        labels = [xbmc.getLocalizedString(o.label_id) for o in SORT_OPTIONS]
        choice = xbmcgui.Dialog().select(LANGUAGE(32203), labels)
        if choice == -1:
            self._cancel_pick()
            return None
        return SORT_OPTIONS[choice]

    def _pick_shortcut(
        self,
        groups: list[Shortcut | ShortcutGroup | Content | Input],
        item_props: dict[str, str],
        allow_custom: bool = False,
    ) -> Shortcut | None:
        """Pick a shortcut from groupings using generic hierarchy picker.

        When allow_custom is set, a "Custom action..." row is pinned to the top
        of the picker. Choosing it opens a keyboard and returns a synthetic
        Shortcut carrying whatever builtin the user typed, so any Kodi window or
        action (the TV Guide, a script, ActivateWindow of anything) is reachable
        even when the skin's groupings never named it. See _prompt_custom_action.
        """
        custom_action = (
            (LANGUAGE(32207), "DefaultAddonProgram.png", self._prompt_custom_action)
            if allow_custom
            else None
        )
        result = self._pick_from_hierarchy(
            groups,
            item_props,
            title=LANGUAGE(32043),
            leaf_types=(Shortcut,),
            group_types=(ShortcutGroup,),
            default_leaf_icon="DefaultShortcut.png",
            default_group_icon="DefaultFolder.png",
            show_none=False,
            content_resolver=self._resolve_content_to_shortcuts,
            create_folder_group=lambda label, items: ShortcutGroup(
                name=f"folder-{label}",
                label=label,
                icon="DefaultFolder.png",
                items=items,
            ),
            custom_action=custom_action,
            custom_action_first=True,
        )
        return result if isinstance(result, Shortcut) else None

    def _prompt_custom_action(self) -> Shortcut | None:
        """Keyboard entry for an arbitrary action, wrapped as a picker leaf.

        Returns a synthetic Shortcut whose single action is the typed builtin,
        or None to fall back into the picker (keyboard cancelled or left empty).
        The returned Shortcut has no source_media, no browse and no action_play,
        so _get_shortcut_actions resolves it straight to [typed], and
        _choose_action writes ONLY that action onto the item, leaving its label,
        icon, visibility and submenu untouched.

        The keyboard is pre-filled with the item's current action so editing an
        existing builtin is a tweak rather than a retype.
        """
        item = self._get_selected_item()
        current = item.action if item else ""
        keyboard = xbmc.Keyboard(current or "", LANGUAGE(32197))
        keyboard.doModal()
        if not keyboard.isConfirmed():
            return None
        text = keyboard.getText().strip()
        if not text:
            return None
        return Shortcut(name="custom-action", label=text, actions=[text])

    def _pick_widget_from_groups(
        self,
        items: list[WidgetGroup | Widget | Content],
        item_props: dict[str, str],
        slot: str = "",
    ) -> Widget | None | Literal[False]:
        """Show widget picker dialog with back navigation.

        Handles standalone widgets, groups, and dynamic content at the top level.

        Args:
            items: Widget groups, widgets, and/or content references to pick from
            item_props: Current item properties for condition evaluation
            slot: Current widget slot being edited (e.g., "widget", "widget.2")

        Returns:
            Widget if selected, None if cancelled completely, False if "None" chosen.
        """
        self._begin_pick()

        current_widget = item_props.get(slot, "")
        items = self._filter_widgets_by_slot(items, slot)

        result = self._pick_from_hierarchy(
            items,
            item_props,
            title=LANGUAGE(32044),
            leaf_types=(Widget,),
            group_types=(WidgetGroup,),
            default_leaf_icon="DefaultAddonNone.png",
            default_group_icon="DefaultFolder.png",
            show_none=True,
            current_value=current_widget,
            content_resolver=self._resolve_content_to_widgets,
            create_folder_group=lambda label, grp_items: WidgetGroup(
                name=f"folder-{label}",
                label=label,
                items=grp_items,
            ),
        )

        return result

    def _pick_widget_flat(
        self, widgets: list, item_props: dict[str, str] | None = None, slot: str = ""
    ) -> Widget | None | Literal[False]:
        """Pick from flat widget list.

        Args:
            widgets: List of (name, label, icon) tuples
            item_props: Current item properties for finding current widget
            slot: Widget slot name (e.g., "widget", "widget.2")

        Returns:
            Widget if selected, None if cancelled, False if "None" chosen.
        """
        self._begin_pick()

        current_widget = item_props.get(slot, "") if item_props else ""
        preselect = -1
        overrides = self._icon_overrides()

        listitems = []
        none_item = xbmcgui.ListItem(xbmc.getLocalizedString(231))
        none_item.setArt({"icon": overrides.get("DefaultAddonNone.png", "DefaultAddonNone.png")})
        listitems.append(none_item)

        for i, w in enumerate(widgets):
            listitem = xbmcgui.ListItem(resolve_label(w[1]))
            icon = w[2] if len(w) > 2 and w[2] else "DefaultAddonNone.png"
            listitem.setArt({"icon": overrides.get(icon, icon)})
            listitems.append(listitem)
            if preselect == -1 and w[0] == current_widget:
                preselect = i + 1  # +1 for "None" option

        selected = xbmcgui.Dialog().select(
            LANGUAGE(32044), listitems, useDetails=True, preselect=preselect
        )

        if selected == -1:
            self._cancel_pick()
            return None
        if selected == 0:
            return False

        widget_name = widgets[selected - 1][0]
        if self.manager is None:
            return None
        return self.manager.config.get_widget(widget_name)

    def _resolve_content_to_widgets(self, content: Content) -> list[Widget]:
        """Resolve a Content reference to a list of Widget objects for the picker."""
        provider = ContentProvider(icon_overrides=self._icon_overrides())
        resolved = provider.resolve(content)

        source = content.source.rstrip("s") if content.source.endswith("s") else content.source

        widgets = []
        for item in resolved:
            path = item.browse_path or extract_path_from_action(item.action)
            # content.target is NOT a fallback for type. It says which add-ons to
            # LIST ("video", "audio"), and it already drives target on the next
            # line. Using it as the widget's content type made every plugin
            # add-on claim type "video", which is not a widget type at all: the
            # documented set is movies, tvshows, episodes, musicvideos, sets,
            # albums, artists, songs, pictures, pvr, games, addons, custom. Skins
            # test that value as widgetType=movies|episodes|tvshows, so "video"
            # matched nothing while still being non-empty, which suppressed both
            # inference and the prompt and left the widget effectively untyped.
            widget = Widget(
                name=f"dynamic-{content.source}-{len(widgets)}",
                label=item.label,
                path=path,
                type=item.content_type or "",
                target=self._map_target_to_window(content.target),
                icon=item.icon,
                source=source,
                browse=bool(item.browse_path),
            )
            widgets.append(widget)

        return widgets

    def _resolve_content_to_shortcuts(self, content: Content) -> list[Shortcut]:
        """Resolve a Content reference to a list of Shortcut objects for the picker."""
        provider = ContentProvider(icon_overrides=self._icon_overrides())
        resolved = provider.resolve(content)

        shortcuts = []
        for item in resolved:
            shortcut = Shortcut(
                name=f"dynamic-{content.source}-{len(shortcuts)}",
                label=item.label,
                actions=[item.action] if item.action else [],
                path=item.browse_path,
                browse=item.browse_window,
                type=item.label2,
                icon=item.icon,
                action_play=item.action_play,
                action_party=item.action_party,
                source_media=item.source_media,
            )
            shortcuts.append(shortcut)

        return shortcuts

    def _map_target_to_window(self, target: str) -> str:
        """Map content target to widget target window."""
        from ..constants import TARGET_MAP

        return TARGET_MAP.get(target.lower(), "videos") if target else "videos"

    def _pick_widget_type(self, addon_type: str) -> str | None:
        """Show dialog to pick widget content type.

        Args:
            addon_type: The addon category (video, audio, executable, pictures)

        Returns:
            Selected widget type string, or None if cancelled.
        """
        if addon_type == "pictures":
            return "pictures"

        if addon_type == "video":
            types = [
                ("movies", xbmc.getLocalizedString(342), "DefaultMovies.png"),
                ("tvshows", xbmc.getLocalizedString(20343), "DefaultTVShows.png"),
                ("episodes", xbmc.getLocalizedString(20360), "DefaultTVShows.png"),
                ("musicvideos", xbmc.getLocalizedString(20389), "DefaultMusicVideos.png"),
                ("videos", xbmc.getLocalizedString(3), "DefaultVideo.png"),
            ]
        elif addon_type == "audio":
            types = [
                ("songs", xbmc.getLocalizedString(134), "DefaultMusicSongs.png"),
                ("albums", xbmc.getLocalizedString(132), "DefaultMusicAlbums.png"),
                ("artists", xbmc.getLocalizedString(133), "DefaultMusicArtists.png"),
                ("music", xbmc.getLocalizedString(2), "DefaultAudio.png"),
            ]
        else:
            types = [
                ("programs", xbmc.getLocalizedString(350), "DefaultAddonProgram.png"),
                ("files", xbmc.getLocalizedString(744), "DefaultFile.png"),
            ]

        overrides = self._icon_overrides()
        listitems = []
        for _type_id, label, icon in types:
            listitem = xbmcgui.ListItem(label)
            listitem.setArt({"icon": overrides.get(icon, icon)})
            listitems.append(listitem)

        selected = xbmcgui.Dialog().select(LANGUAGE(32140), listitems, useDetails=True)

        if selected == -1:
            self._cancel_pick()
            return None

        return types[selected][0]

    def _map_widget_type_to_target(self, widget_type: str, default: str) -> str:
        """Map widget type to target window."""
        type_to_target = {
            "movies": "videos",
            "tvshows": "videos",
            "episodes": "videos",
            "musicvideos": "videos",
            "videos": "videos",
            "songs": "music",
            "albums": "music",
            "artists": "music",
            "music": "music",
            "programs": "programs",
            "files": "files",
            "pictures": "pictures",
        }
        return type_to_target.get(widget_type, default)

    def _is_browsable(self, obj) -> bool:
        """Object is opted in for browse-into via `browse` + `path`.

        Works for both Widget (`browse` is bool) and Shortcut (`browse` is window name).
        """
        return bool(obj.browse and obj.path)

    def _infer_widget_type(self, path: str, addon_type: str) -> str:
        """Infer a browsed path's content type, empty when nothing is recognisable.

        Kodi's library paths name their own content: videodb://movies/titles/ is
        movies, musicdb://albums/ is albums. The first recognised segment wins,
        because it is the closest to the root and so the most general correct
        answer: videodb://musicvideos/albums/ is musicvideos, not albums.

        Content is deliberately NOT sampled to decide this. Files.GetDirectory
        reports type "unknown" for library nodes, and an empty or not yet scanned
        library returns nothing at all, so sampling would answer differently on
        two boxes holding the same menu. The path is stable and always present.

        Falls back to the generic type for the target window, which is what a
        plugin:// or file-system listing gets: those have no library type, and a
        generic answer commits cleanly where a prompt would interrupt.
        """
        segment_types = {
            "movies": "movies",
            "sets": "sets",
            "tvshows": "tvshows",
            "episodes": "episodes",
            "musicvideos": "musicvideos",
            "albums": "albums",
            "artists": "artists",
            "songs": "songs",
            "games": "games",
            "pictures": "pictures",
            "addons": "addons",
            "pvr": "pvr",
        }
        # Longest first: musicvideos must not be read as videos, and a node named
        # recentlyaddedmusicvideos must not be read as a movie node.
        token_types = (
            ("musicvideo", "musicvideos"),
            ("tvshow", "tvshows"),
            ("episode", "episodes"),
            ("movie", "movies"),
            ("album", "albums"),
            ("artist", "artists"),
            ("song", "songs"),
            ("game", "games"),
        )
        generic_types = {
            "video": "videos",
            "audio": "music",
            "pictures": "pictures",
            "executable": "programs",
        }

        segments = [s for s in path.lower().replace("://", "/").split("/") if s]
        for segment in segments:
            if segment in segment_types:
                return segment_types[segment]

        # library://video/recentlyaddedmovies/ and friends: a node name with the
        # type embedded rather than standing as its own segment. Segments holding
        # a dot are skipped because those are add-on ids, not node names, and
        # plugin.video.themoviedb.helper is not a movie listing.
        for segment in segments:
            if "." in segment:
                continue
            for token, widget_type in token_types:
                if token in segment:
                    return widget_type

        return generic_types.get(addon_type, "")

    def _browse_widget_path(self, widget: Widget) -> Widget | None:
        """Browse into a widget's path and let user select location.

        Args:
            widget: Widget with browsable path

        Returns:
            New Widget with browsed path, or None if cancelled
        """
        result = self._browse_directory(widget.path, resolve_label(widget.label))
        if result is None:
            return None

        path, label, icon = result

        addon_type = "video"
        if widget.target == "music":
            addon_type = "audio"
        elif widget.target == "programs":
            addon_type = "executable"
        elif widget.target == "pictures":
            addon_type = "pictures"

        # A type the skin declared wins, then one inferred from the browsed path,
        # and only a path that yields neither is worth interrupting the user for.
        #
        # Before this, _pick_widget_type was called unconditionally and its answer
        # overwrote widget.type, so a widget declared exactly as upstream's own
        # documentation shows it, <widget type="movies" browse="true">, still
        # asked which type it was. Cancelling that prompt returned None, and both
        # callers treat None as "go back to the picker", so the whole selection
        # was discarded and the user landed where they started. That is the loop.
        widget_type = widget.type or self._infer_widget_type(path, addon_type)
        if not widget_type:
            # Not reached with today's four targets, because each maps to a
            # generic type and _infer_widget_type always returns one of them.
            # Kept, rather than deleting upstream's prompt, so a target added
            # later that maps to no generic asks instead of silently returning
            # an untyped widget.
            widget_type = self._pick_widget_type(addon_type)
        if not widget_type:
            return None

        widget_target = self._map_widget_type_to_target(widget_type, widget.target or "videos")

        return Widget(
            name=f"browse-{hash(path)}",
            label=label,
            path=path,
            type=widget_type,
            target=widget_target,
            icon=icon or widget.icon,
            source="addon",
        )

    def _pick_from_hierarchy(
        self,
        items: list,
        item_props: dict[str, str],
        *,
        title: str = "",
        leaf_types: tuple = (Shortcut,),
        group_types: tuple = (ShortcutGroup,),
        default_leaf_icon: str = "DefaultShortcut.png",
        default_group_icon: str = "DefaultFolder.png",
        show_none: bool = False,
        current_value: str = "",
        content_resolver: Callable[[Content], list] | None = None,
        create_folder_group: Callable[[str, list], Any] | None = None,
        custom_action: tuple[str, str, Callable[[], Any | None]] | None = None,
        custom_action_first: bool = False,
    ) -> Any | None | Literal[False]:
        """Generic hierarchical picker with back navigation.

        Works with any types that have: name, label, icon, condition, visible.
        Groups additionally have an items list.

        Args:
            items: List of items/groups to pick from
            item_props: Current item properties for condition evaluation
            title: Dialog title
            leaf_types: Tuple of types considered leaf items (selectable)
            group_types: Tuple of types considered groups (navigable)
            default_leaf_icon: Default icon for leaf items
            default_group_icon: Default icon for groups
            show_none: Whether to show "None" option at top level
            current_value: Current item name for preselect
            content_resolver: Optional function to resolve Content to list of items
            create_folder_group: Optional function to create folder group from (label, items)
            custom_action: Optional tuple of (label, icon, callback) for a custom action
                shown in the list. The callback should return an item if
                successful, or None to return to the picker.
            custom_action_first: Render the custom action at the TOP of the list
                instead of the bottom. Only meaningful when custom_action is set.

        Returns:
            Selected leaf item, None if cancelled, False if "None" chosen.
        """
        visible_items = self._filter_picker_items(
            items, item_props, leaf_types, group_types, content_resolver, create_folder_group
        )

        if not visible_items:
            xbmcgui.Dialog().notification(LANGUAGE(32141), LANGUAGE(32064))
            return None

        preselect = -1
        # A custom action pinned to the TOP shifts every real row down by one,
        # exactly as "None" does, so both are folded into one offset.
        custom_first = bool(custom_action) and custom_action_first
        offset = (1 if custom_first else 0) + (1 if show_none else 0)

        for i, vis_item in enumerate(visible_items):
            if hasattr(vis_item, "name") and vis_item.name == current_value:
                preselect = i + offset
                break

        overrides = self._icon_overrides()

        while True:
            listitems = []
            if custom_first:
                action_label, action_icon, _callback = custom_action
                action_item = xbmcgui.ListItem(action_label)
                action_item.setArt({"icon": overrides.get(action_icon, action_icon)})
                listitems.append(action_item)
            if show_none:
                none_item = xbmcgui.ListItem(xbmc.getLocalizedString(231))
                none_item.setArt(
                    {"icon": overrides.get("DefaultAddonNone.png", "DefaultAddonNone.png")}
                )
                listitems.append(none_item)

            for vis_item in visible_items:
                is_placeholder = isinstance(
                    vis_item, (Shortcut, Widget)
                ) and vis_item.name.startswith("content-placeholder-")
                if is_placeholder:
                    label = LANGUAGE(32058)
                else:
                    label = resolve_label(vis_item.label)
                if isinstance(vis_item, group_types):
                    label = f"{label} >"
                    icon = vis_item.icon if vis_item.icon else default_group_icon
                elif (
                    isinstance(vis_item, (Shortcut, Widget))
                    and not is_placeholder
                    and self._is_browsable(vis_item)
                ):
                    label = f"{label} >"
                    icon = vis_item.icon if vis_item.icon else default_leaf_icon
                else:
                    icon = vis_item.icon if vis_item.icon else default_leaf_icon
                listitem = xbmcgui.ListItem(label)
                listitem.setArt({"icon": overrides.get(icon, icon)})
                listitems.append(listitem)

            if custom_action and not custom_first:
                action_label, action_icon, _callback = custom_action
                action_item = xbmcgui.ListItem(action_label)
                action_item.setArt({"icon": overrides.get(action_icon, action_icon)})
                listitems.append(action_item)

            selected = xbmcgui.Dialog().select(
                title or LANGUAGE(32181), listitems, useDetails=True, preselect=preselect
            )

            if selected == -1:
                self._cancel_pick()
                return None

            is_custom_row = custom_action and (
                selected == 0 if custom_first else selected == len(listitems) - 1
            )
            if is_custom_row:
                _label, _icon, callback = custom_action
                result = callback()
                if result is not None:
                    return result
                if self._picker_cancelled:
                    return None
                continue

            if show_none and selected == (1 if custom_first else 0):
                return False

            preselect = selected
            selected_item = visible_items[selected - offset]

            if isinstance(selected_item, Input):
                result = self._handle_input_selection(selected_item)
                if result is not None:
                    return result
                if self._picker_cancelled:
                    return None
                continue

            if isinstance(selected_item, leaf_types):
                is_browsable_shortcut = (
                    isinstance(selected_item, Shortcut)
                    and not selected_item.name.startswith("content-placeholder-")
                    and self._is_browsable(selected_item)
                )
                if is_browsable_shortcut:
                    browse_info = self._get_browse_info_from_shortcut(selected_item)
                    if browse_info:
                        browse_path, target_window = browse_info
                        result = self._browse_path(
                            browse_path,
                            title=resolve_label(selected_item.label),
                            target_window=target_window,
                            source_media=selected_item.source_media,
                        )
                        if result is not None:
                            return result
                        if self._picker_cancelled:
                            return None
                        continue

                if isinstance(selected_item, Widget) and self._is_browsable(selected_item):
                    result = self._browse_widget_path(selected_item)
                    if result is not None:
                        return result
                    if self._picker_cancelled:
                        return None
                    continue

                return selected_item

            result = self._pick_from_hierarchy_group(
                selected_item,
                item_props,
                leaf_types=leaf_types,
                group_types=group_types,
                default_leaf_icon=default_leaf_icon,
                default_group_icon=default_group_icon,
                content_resolver=content_resolver,
                create_folder_group=create_folder_group,
            )

            if result is not None:
                return result
            if self._picker_cancelled:
                return None

    def _pick_from_hierarchy_group(
        self,
        group,
        item_props: dict[str, str],
        *,
        leaf_types: tuple,
        group_types: tuple,
        default_leaf_icon: str,
        default_group_icon: str,
        content_resolver: Callable[[Content], list] | None = None,
        create_folder_group: Callable[[str, list], Any] | None = None,
    ) -> Any | None:
        """Pick from items within a group with back navigation."""
        visible_items = self._filter_picker_items(
            group.items,
            item_props,
            leaf_types,
            group_types,
            content_resolver,
            create_folder_group,
            parent_label=resolve_label(group.label),
        )

        if not visible_items:
            xbmcgui.Dialog().notification(LANGUAGE(32141), LANGUAGE(32142))
            return None

        overrides = self._icon_overrides()
        preselect = -1
        while True:
            listitems = []
            for vis_item in visible_items:
                is_placeholder = isinstance(
                    vis_item, (Shortcut, Widget)
                ) and vis_item.name.startswith("content-placeholder-")
                if is_placeholder:
                    label = LANGUAGE(32058)
                else:
                    label = resolve_label(vis_item.label)
                if isinstance(vis_item, group_types):
                    label = f"{label} >"
                    icon = vis_item.icon if vis_item.icon else default_group_icon
                elif (
                    isinstance(vis_item, (Shortcut, Widget))
                    and not is_placeholder
                    and self._is_browsable(vis_item)
                ):
                    label = f"{label} >"
                    icon = vis_item.icon if vis_item.icon else default_leaf_icon
                else:
                    icon = vis_item.icon if vis_item.icon else default_leaf_icon
                listitem = xbmcgui.ListItem(label)
                listitem.setArt({"icon": overrides.get(icon, icon)})
                listitems.append(listitem)

            title = resolve_label(group.label)
            selected = xbmcgui.Dialog().select(
                title, listitems, useDetails=True, preselect=preselect
            )

            if selected == -1:
                self._cancel_pick()
                return None

            preselect = selected
            selected_item = visible_items[selected]

            if isinstance(selected_item, Input):
                result = self._handle_input_selection(selected_item)
                if result is not None:
                    return result
                if self._picker_cancelled:
                    return None
                continue

            if isinstance(selected_item, leaf_types):
                is_browsable_shortcut = (
                    isinstance(selected_item, Shortcut)
                    and not selected_item.name.startswith("content-placeholder-")
                    and self._is_browsable(selected_item)
                )
                if is_browsable_shortcut:
                    browse_info = self._get_browse_info_from_shortcut(selected_item)
                    if browse_info:
                        browse_path, target_window = browse_info
                        result = self._browse_path(
                            browse_path,
                            title=resolve_label(selected_item.label),
                            target_window=target_window,
                            source_media=selected_item.source_media,
                        )
                        if result is not None:
                            return result
                        if self._picker_cancelled:
                            return None
                        continue

                if isinstance(selected_item, Widget) and self._is_browsable(selected_item):
                    result = self._browse_widget_path(selected_item)
                    if result is not None:
                        return result
                    if self._picker_cancelled:
                        return None
                    continue

                return selected_item

            result = self._pick_from_hierarchy_group(
                selected_item,
                item_props,
                leaf_types=leaf_types,
                group_types=group_types,
                default_leaf_icon=default_leaf_icon,
                default_group_icon=default_group_icon,
                content_resolver=content_resolver,
                create_folder_group=create_folder_group,
            )

            if result is not None:
                return result
            if self._picker_cancelled:
                return None

    def _filter_picker_items(
        self,
        items: list,
        item_props: dict[str, str],
        leaf_types: tuple,
        group_types: tuple,
        content_resolver: Callable[[Content], list] | None = None,
        create_folder_group: Callable[[str, list], Any] | None = None,
        parent_label: str = "",
    ) -> list:
        """Filter and resolve picker items based on conditions and visibility.

        parent_label is the label of the group currently being browsed; it names
        an addons content placeholder when the content element carries no label.
        """
        visible_items = []

        for item in items:
            if isinstance(item, Content):
                if item.condition and not evaluate_condition(item.condition, item_props):
                    continue
                if item.visible and not _check_visible(item.visible):
                    continue
                if content_resolver:
                    resolved = content_resolver(item)
                    placeholder = _browse_placeholder_for_content(
                        item, as_widget=Widget in leaf_types, parent_label=parent_label
                    )
                    if placeholder:
                        overrides = self._icon_overrides()
                        placeholder.icon = overrides.get(placeholder.icon, placeholder.icon)
                        visible_items.append(placeholder)
                    if item.folder and resolved and create_folder_group:
                        folder = create_folder_group(item.folder, resolved)
                        visible_items.append(folder)
                    elif resolved:
                        visible_items.extend(resolved)
            elif isinstance(item, (Input, *leaf_types, *group_types)):
                if not _check_visible(getattr(item, "visible", "")):
                    continue
                condition = getattr(item, "condition", "")
                if condition and not evaluate_condition(condition, item_props):
                    continue
                if isinstance(item, group_types) and getattr(item, "flat", False):
                    expanded = self._filter_picker_items(
                        item.items,
                        item_props,
                        leaf_types,
                        group_types,
                        content_resolver,
                        create_folder_group,
                        parent_label=resolve_label(getattr(item, "label", "")) or parent_label,
                    )
                    visible_items.extend(expanded)
                    continue
                visible_items.append(item)

        return visible_items

    def _handle_input_selection(self, input_item: Input) -> Shortcut | None:
        """Handle selection of an Input item by showing keyboard.

        Args:
            input_item: The Input item that was selected

        Returns:
            Shortcut with entered value, or None if cancelled
        """
        input_type_map = {
            "text": xbmcgui.INPUT_ALPHANUM,
            "numeric": xbmcgui.INPUT_NUMERIC,
            "ipaddress": xbmcgui.INPUT_IPADDRESS,
            "password": xbmcgui.INPUT_PASSWORD,
        }

        keyboard_type = input_type_map.get(input_item.type, xbmcgui.INPUT_ALPHANUM)
        heading = resolve_label(input_item.label)

        result = xbmcgui.Dialog().input(heading, type=keyboard_type)
        if not result:
            self._cancel_pick()
            return None

        if input_item.for_ == "action":
            return Shortcut(
                name=f"custom-input-{hash(result)}",
                label=input_item.label,
                actions=[result],
                icon=input_item.icon,
            )
        if input_item.for_ == "label":
            return Shortcut(
                name=f"custom-input-{hash(result)}",
                label=result,
                actions=["noop"],
                icon=input_item.icon,
            )
        if input_item.for_ == "path":
            return Shortcut(
                name=f"custom-input-{hash(result)}",
                label=input_item.label,
                actions=[f"ActivateWindow(Videos,{result},return)"],
                icon=input_item.icon,
            )

        return None

    def _browse_directory(
        self,
        path: str,
        title: str = "",
    ) -> tuple[str, str, str] | None:
        """Browse into a path and let user select location or navigate deeper.

        Shows directory contents with "Use this location" at top.
        Selecting a directory navigates into it.
        Selecting "Use this location" or a file returns path info.

        Args:
            path: Starting path to browse
            title: Dialog title (defaults to path basename)

        Returns:
            Tuple of (path, label, icon) for selected location, or None if cancelled
        """
        browse_provider = get_browse_provider()
        browse_provider.set_icon_overrides(self._icon_overrides())
        current_path = path
        current_label = title

        overrides = self._icon_overrides()
        folder_icon = overrides.get("DefaultFolder.png", "DefaultFolder.png")

        while True:
            xbmc.executebuiltin("ActivateWindow(busydialognocancel)")
            try:
                items = browse_provider.list_directory(current_path, include_art=True)
                if items is None:
                    xbmcgui.Dialog().notification(LANGUAGE(32149), LANGUAGE(32150))
                    return None

                dialog_title = current_label or LANGUAGE(32151)

                listitems = []
                use_location_item = xbmcgui.ListItem(LANGUAGE(32058))
                use_location_item.setArt({"icon": folder_icon})
                listitems.append(use_location_item)
                for item in items:
                    label = item.label
                    if item.is_directory:
                        label = f"{label} >"
                    listitem = xbmcgui.ListItem(label)
                    listitem.setArt({"icon": item.icon})
                    listitems.append(listitem)
            finally:
                xbmc.executebuiltin("Dialog.Close(busydialognocancel)")

            selected = xbmcgui.Dialog().select(dialog_title, listitems, useDetails=True)

            if selected == -1:
                # Back leaves the picker outright; it does NOT pop one browse
                # level. Every level of this listing draws the same FIRST ROW,
                # "Create menu item to here" at index 0, with no preselect, so
                # popping one level was near enough indistinguishable from
                # nothing happening, and that is how a four-press escape read
                # as a dead end.
                #
                # Be precise about what does and does not change, because the
                # heading DOES change: dialog_title is `current_label or
                # LANGUAGE(32151)` a few lines above, so it tracks the folder
                # being listed. It is the body that repeats. Do not restate this
                # as "the same title bar"; that was written here and in the
                # 3.0.1.2 release note, and it is wrong.
                # See the _picker_cancelled note at the top of this class.
                self._cancel_pick()
                return None

            if selected == 0:
                return (current_path, current_label or LANGUAGE(32182), folder_icon)

            selected_item = items[selected - 1]

            if selected_item.is_directory:
                current_path = selected_item.path
                current_label = selected_item.label
                continue

            return (selected_item.path, selected_item.label, selected_item.icon)

    def _browse_path(
        self,
        path: str,
        title: str = "",
        target_window: str = "videos",
        source_media: str = "",
    ) -> Shortcut | None:
        """Browse into a path and let user select location or navigate deeper.

        Shows directory contents with "Use this location" at top.
        Selecting a directory navigates into it.
        Selecting "Use this location" or a file returns a Shortcut.

        Args:
            path: Starting path to browse
            title: Dialog title (defaults to path basename)
            target_window: Window for ActivateWindow action

        Returns:
            Shortcut for selected location, or None if cancelled
        """
        result = self._browse_directory(path, title)
        if result is None:
            return None

        selected_path, label, icon = result
        return Shortcut(
            name=f"browse-{hash(selected_path)}",
            label=label,
            actions=[f"ActivateWindow({target_window},{selected_path},return)"],
            icon=icon,
            path=selected_path,
            source_media=source_media,
        )

    def _filter_widgets_by_slot(self, items: list, slot: str) -> list:
        """Filter widget items by slot. Widgets with no slot show for all slots.
        Widgets with a specific slot only show when that slot is being edited.
        Recurses into WidgetGroups.
        """
        from ..models.widget import Widget, WidgetGroup

        filtered = []
        for item in items:
            if isinstance(item, Widget):
                if not item.slot or item.slot == slot:
                    filtered.append(item)
            elif isinstance(item, WidgetGroup):
                filtered_children = self._filter_widgets_by_slot(item.items, slot)
                if filtered_children:
                    filtered_group = WidgetGroup(
                        name=item.name,
                        label=item.label,
                        icon=item.icon,
                        condition=item.condition,
                        visible=item.visible,
                        items=filtered_children,
                        flat=item.flat,
                    )
                    filtered.append(filtered_group)
            else:
                filtered.append(item)
        return filtered

    def _get_browse_info_from_shortcut(self, shortcut: Shortcut) -> tuple[str, str] | None:
        """Extract browsable path and target window from a shortcut.

        Returns (path, window) if the shortcut opted in via `browse` + `<path>`, else None.
        """
        if not self._is_browsable(shortcut):
            return None

        from ..constants import WINDOW_MAP

        window = WINDOW_MAP.get(shortcut.browse.lower(), "Videos")
        return (shortcut.path, window)

    def _pick_background(
        self, item_props: dict[str, str], current_value: str = ""
    ) -> Background | None | Literal[False]:
        """Pick a background from groupings.

        Returns:
            Background if selected, None if cancelled, False if "None" chosen.
        """
        if not self.manager:
            return None

        self._begin_pick()

        groupings = self.manager.config.background_groupings
        if not groupings:
            xbmcgui.Dialog().notification(LANGUAGE(32152), LANGUAGE(32153))
            return None

        return self._pick_from_hierarchy(
            groupings,
            item_props,
            title=LANGUAGE(32045),
            leaf_types=(Background,),
            group_types=(BackgroundGroup,),
            default_leaf_icon="DefaultPicture.png",
            default_group_icon="DefaultFolder.png",
            show_none=True,
            current_value=current_value,
        )
