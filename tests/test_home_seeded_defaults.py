"""The first run defaults Home.xml seeds, and the cross-file couplings they rest on.

Every one of these is a one-shot write guarded by
String.IsEmpty(Skin.String(pov_menu_defaults)), so it lands on a profile that has
never run this skin and never again. That guard is the whole safety property: the
owner's six boxes are stamped, and a regression here would rearrange all of them
on the next update with nothing in the log to say what happened. There is no way
to notice that from a code review of Home.xml alone, so it is pinned here.

TWO OF THE FOUR SETTINGS ARE INVERTED KEYS, and that is the fragile part. Setting
hide_mediaflags is what makes "Show media flags" read OFF, because control 705's
<selected> negates it. A well meaning tidy-up of SkinSettings.xml that removed the
negation would silently flip both defaults to the opposite of what the owner asked
for, while every test that only reads Home.xml carried on passing. So the
inversion itself is asserted, in the file that defines it.
"""

import pathlib
import re

ROOT = pathlib.Path(__file__).resolve().parent.parent
XML = ROOT / "skin.estuary.pov" / "xml"

GUARD = "String.IsEmpty(Skin.String(pov_menu_defaults))"
STAMP = "Skin.SetString(pov_menu_defaults,1)"

HOME = (XML / "Home.xml").read_text(encoding="utf-8")
SKIN_SETTINGS = (XML / "SkinSettings.xml").read_text(encoding="utf-8")
VARIABLES = (XML / "Variables.xml").read_text(encoding="utf-8")

# Only the <onload> tags, in document order, as (condition, action) pairs.
ONLOADS = re.findall(
    r'<onload(?:\s+condition="([^"]*)")?\s*>([^<]*)</onload>',
    HOME.split("<controls>", 1)[0],
)

ACTIONS = [action for _, action in ONLOADS]

# The seven switched off in 1.2.5. Unchanged in 1.2.7 and listed in full rather
# than counted, so adding an eighth is a deliberate edit to this file.
MENU_OFF = (
    "HomeMenuNoMusicButton",
    "HomeMenuNoMusicVideoButton",
    "HomeMenuNoRadioButton",
    "HomeMenuNoPicturesButton",
    "HomeMenuNoVideosButton",
    "HomeMenuNoGamesButton",
    "HomeMenuNoFavButton",
)

# The five that stay on. Seeding any of these would switch a visible menu item
# OFF, which is the opposite of the shipped behaviour.
MENU_ON = (
    "HomeMenuNoMovieButton",
    "HomeMenuNoTVShowButton",
    "HomeMenuNoTVButton",
    "HomeMenuNoProgramsButton",
    "HomeMenuNoWeatherButton",
)


# --------------------------------------------------------------------------- #
# The guard, which is what protects every already stamped box
# --------------------------------------------------------------------------- #
def test_every_seeded_default_is_behind_the_first_run_guard():
    unguarded = [action for condition, action in ONLOADS if condition != GUARD]
    assert unguarded == [], (
        "an unguarded <onload> in Home.xml runs on EVERY home load, on every box, "
        "and would overwrite a setting its owner chose: " + repr(unguarded)
    )


def test_the_stamp_is_written_last():
    """Order is load bearing. Stamping first strands a half applied profile.

    If a load is cut short part way through the block, the guard is still empty
    and the whole set is reapplied on the next Home load. That retry only exists
    while the stamp is the final action.
    """
    assert ACTIONS[-1] == STAMP, (
        "Skin.SetString(pov_menu_defaults,1) must be the LAST onload, found "
        + repr(ACTIONS[-1])
    )
    assert ACTIONS.count(STAMP) == 1, "the stamp must be written exactly once"


# --------------------------------------------------------------------------- #
# The four settings added in 1.2.7
# --------------------------------------------------------------------------- #
def test_media_flags_start_off():
    assert "Skin.SetBool(hide_mediaflags)" in ACTIONS


def test_setting_hide_mediaflags_is_what_switches_the_row_off():
    """The coupling that makes the default mean what the owner asked for.

    Control 705 renders its state as !Skin.HasSetting(hide_mediaflags), so the
    key reads BACKWARDS: setting it is what makes "Show media flags" display OFF.
    Remove the negation and the default silently becomes ON.
    """
    assert "<selected>!Skin.HasSetting(hide_mediaflags)</selected>" in SKIN_SETTINGS, (
        "control 705's selected state must stay negated, or Home.xml's "
        "Skin.SetBool(hide_mediaflags) starts meaning the opposite of OFF"
    )


def test_fanart_backgrounds_start_off():
    assert "Skin.SetBool(no_fanart)" in ACTIONS


def test_setting_no_fanart_is_what_switches_the_row_off():
    """Control 605, inverted exactly like 705. Same trap, same assertion."""
    assert "<selected>!Skin.HasSetting(no_fanart)</selected>" in SKIN_SETTINGS, (
        "control 605's selected state must stay negated, or Home.xml's "
        "Skin.SetBool(no_fanart) starts meaning the opposite of OFF"
    )


def test_ratings_start_on_rating_rather_than_none():
    assert "Skin.SetBool(circle_rating)" in ACTIONS


def test_the_other_two_rating_keys_are_left_unset():
    """Control 706 is a three way choice sharing one label.

    RatingSettingLabel2Var tests circle_rating first, so setting a second key
    would not change the label, but it WOULD light the corresponding rating
    control in the library views while the settings row claimed something else.
    Only one of the three may be seeded.
    """
    for key in ("circle_userrating", "circle_bothrating", "circle_none"):
        assert "Skin.SetBool(%s)" % key not in ACTIONS, (
            "seeding %s alongside circle_rating makes the settings row and the "
            "views disagree" % key
        )


def test_the_rating_row_reads_rating_when_only_circle_rating_is_set():
    """$LOCALIZE[563] is "Rating"; the fallback 16018 is "None".

    Pinned as an ordered list because the variable is first-match-wins: moving
    the circle_rating line below circle_userrating would leave the row reading
    "None" on a fresh box with the default applied.
    """
    block = VARIABLES.split('<variable name="RatingSettingLabel2Var">', 1)[1]
    block = block.split("</variable>", 1)[0]
    values = re.findall(r'<value(?:\s+condition="([^"]*)")?>([^<]*)</value>', block)
    assert values[0] == ("Skin.HasSetting(circle_rating)", "$LOCALIZE[563]"), (
        "circle_rating must be the FIRST branch and must resolve to 563 Rating, "
        "found " + repr(values[0])
    )
    assert values[-1] == ("", "$LOCALIZE[16018]"), (
        "the fallback must stay 16018 None, found " + repr(values[-1])
    )


def test_home_rows_start_at_ten():
    assert "Skin.SetString(home_items,10)" in ACTIONS


def test_the_seeded_row_size_survives_the_skin_settings_repair():
    """SkinSettings.xml:11 rewrites home_items to 15 when it is out of range.

    That line only runs when the settings window opens, which is why the seed
    lives in Home.xml at all: a fresh box that never opens skin settings would
    otherwise keep an empty value and control 709 would be a dead button. The two
    must not fight, so the seeded value has to be one the repair accepts.
    """
    repair = [
        condition
        for condition, action in re.findall(
            r'<onload\s+condition="([^"]*)"\s*>([^<]*)</onload>', SKIN_SETTINGS
        )
        if "Skin.SetString(home_items" in action
    ]
    assert repair, "the home_items repair onload has gone from SkinSettings.xml"
    # The condition is a conjunction of negated equalities, so the numbers it
    # names are precisely the values it leaves alone.
    accepted = re.findall(r"!String\.IsEqual\(Skin\.String\(home_items\),(\d+)\)", repair[0])
    assert "10" in accepted, (
        "the repair would rewrite the seeded 10 to 15 the first time anybody "
        "opened skin settings; it leaves alone only " + repr(accepted)
    )


# --------------------------------------------------------------------------- #
# The 1.2.5 menu, which 1.2.7 must leave exactly as it is
# --------------------------------------------------------------------------- #
def test_the_seven_hidden_menu_items_are_unchanged():
    seeded = [
        re.match(r"Skin\.SetBool\((HomeMenuNo\w+)\)", action).group(1)
        for action in ACTIONS
        if action.startswith("Skin.SetBool(HomeMenuNo")
    ]
    assert seeded == list(MENU_OFF), (
        "the shipped five item menu is defined by exactly these seven being "
        "switched off, in this order; found " + repr(seeded)
    )


def test_the_five_visible_menu_items_are_never_seeded():
    for key in MENU_ON:
        assert "Skin.SetBool(%s)" % key not in ACTIONS, (
            "%s must stay unset, or a menu item the skin ships with disappears" % key
        )


def test_nothing_else_has_crept_into_the_first_run_block():
    """A whitelist, so a new default is a deliberate edit to this test.

    Anything seeded here lands on every future install and can never be undone
    for the boxes that already took it, so the set is enumerated rather than
    pattern matched.
    """
    expected = (
        ["Skin.SetBool(%s)" % key for key in MENU_OFF]
        + [
            "Skin.SetBool(hide_mediaflags)",
            "Skin.SetBool(circle_rating)",
            "Skin.SetBool(no_fanart)",
            "Skin.SetString(home_items,10)",
            STAMP,
        ]
    )
    assert ACTIONS == expected, (
        "Home.xml's first run block changed. If that is deliberate, update this "
        "list and say so in the changelog.\nfound:    %r\nexpected: %r"
        % (ACTIONS, expected)
    )
