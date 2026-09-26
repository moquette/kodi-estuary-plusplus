#!/usr/bin/env python3
"""Generate a synthetic Kodi video library for widget development.

Why synthetic rather than the owner's real media: the widgets under development
(POV rows, Trending, Popular, In Progress, Next Episodes, ratings top-right,
watched checkmark bottom-left) need ROWS, ART, RATINGS, WATCHED FLAGS and
RESUME POINTS. Real media gives the first two and nothing else without hours of
playback. This gives all six, deterministically, in about ten seconds.

The owner's backed-up databases were checked first (2026-07-27, on the
estuary-8 bench this tooling was rescued from) and were EMPTY (0 movies,
0 tvshows, 0 episodes in both MyVideos131 and MyVideos147), so restoring them
would not have helped. That backup directory is not kept in this repo.

Writes only into bench/media/. Nothing here touches userdata.
Run bench/seed-library.sh, which also registers the sources and scans.
"""

import colorsys
import hashlib
import os
import random
import shutil
import sys

from PIL import Image, ImageDraw, ImageFont

ROOT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "media")
MOVIES = os.path.join(ROOT, "movies")
TVSHOWS = os.path.join(ROOT, "tvshows")

# Hue range deliberately excludes red and orange (0-60 and 330-360). The owner's
# standing rule is that red is never a design choice here, and generated
# placeholder art is a design choice.
HUE_LO, HUE_HI = 0.30, 0.82

FONTS = [
    "/System/Library/Fonts/Supplemental/Futura.ttc",
    "/System/Library/Fonts/Helvetica.ttc",
    "/System/Library/Fonts/SFNS.ttf",
]

GENRES = [
    "Drama",
    "Science Fiction",
    "Thriller",
    "Comedy",
    "Documentary",
    "Action",
    "Mystery",
    "Animation",
]
STUDIOS = [
    "Northlight Pictures",
    "Harbour & Vine",
    "Cold Signal",
    "Meridian",
    "Blue Aperture",
    "Tidewater Films",
]
MPAA = ["G", "PG", "PG-13", "R", "TV-14", "TV-MA"]

MOVIE_TITLES = [
    "The Quiet Meridian",
    "Salt and Static",
    "Nine Fathoms Down",
    "A Cartography of Small Rooms",
    "The Lantern Problem",
    "Winterlight",
    "Every Third Tuesday",
    "The Understudy",
    "Glasshouse",
    "Signal Decay",
    "The Long Approach",
    "Paper Anniversary",
    "The Vanishing Point",
    "Comfort of Strangers",
    "Low Tide, High Water",
    "The Archivist",
    "Sixteen Hours to Reykjavik",
    "The Weight of Rain",
    "Nobody's Cartographer",
    "The Kelp Forest",
    "Aftermarket",
    "The Semaphore Line",
    "A Year of Wednesdays",
    "The Blue Hour",
]

SHOW_TITLES = [
    "Harbour Watch",
    "The Meridian Files",
    "Slow Orbit",
    "Cold Open",
    "The Understory",
    "Nightshift Cartography",
]


def font(size):
    for path in FONTS:
        try:
            return ImageFont.truetype(path, size)
        except Exception:
            continue
    return ImageFont.load_default()


def hue_for(seed):
    h = int(hashlib.sha256(seed.encode()).hexdigest()[:8], 16)
    return HUE_LO + (h % 1000) / 1000.0 * (HUE_HI - HUE_LO)


def rgb(h, s, v):
    r, g, b = colorsys.hsv_to_rgb(h, s, v)
    return int(r * 255), int(g * 255), int(b * 255)


def wrap(draw, text, fnt, maxw):
    words, lines, cur = text.split(), [], ""
    for w in words:
        trial = (cur + " " + w).strip()
        if draw.textlength(trial, font=fnt) <= maxw or not cur:
            cur = trial
        else:
            lines.append(cur)
            cur = w
    if cur:
        lines.append(cur)
    return lines


def make_art(path, w, h, title, subtitle, seed, transparent=False):
    """Vertical-gradient placeholder with the title drawn on it, so a widget
    tile is identifiable at a glance instead of being an anonymous colour."""
    hue = hue_for(seed)
    if transparent:
        img = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    else:
        img = Image.new("RGB", (w, h))
        d = ImageDraw.Draw(img)
        top = rgb(hue, 0.55, 0.62)
        bot = rgb(hue, 0.70, 0.20)
        for y in range(h):
            t = y / max(1, h - 1)
            d.line(
                [(0, y), (w, y)],
                fill=tuple(int(top[i] + (bot[i] - top[i]) * t) for i in range(3)),
            )
    d = ImageDraw.Draw(img)
    fnt = font(max(14, int(w / 12)))
    small = font(max(11, int(w / 26)))
    lines = wrap(d, title, fnt, w * 0.84)
    lh = int(fnt.size * 1.18)
    y = int(h * 0.5) - (len(lines) * lh) // 2
    for ln in lines:
        tw = d.textlength(ln, font=fnt)
        d.text(((w - tw) / 2 + 2, y + 2), ln, font=fnt, fill=(0, 0, 0, 160))
        d.text(((w - tw) / 2, y), ln, font=fnt, fill=(245, 245, 245))
        y += lh
    if subtitle:
        tw = d.textlength(subtitle, font=small)
        d.text(
            ((w - tw) / 2, y + int(lh * 0.25)),
            subtitle,
            font=small,
            fill=(220, 220, 220),
        )
    os.makedirs(os.path.dirname(path), exist_ok=True)
    if path.lower().endswith(".png"):
        img.save(path)
    else:
        img.convert("RGB").save(path, quality=88)


def fake_video(path, kb=8):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "wb") as f:
        f.write(b"\x1a\x45\xdf\xa3" + os.urandom(kb * 1024 - 4))


def streamdetails(minutes):
    return f"""  <fileinfo>
    <streamdetails>
      <video>
        <codec>h264</codec>
        <aspect>1.778</aspect>
        <width>1920</width>
        <height>1080</height>
        <durationinseconds>{minutes * 60}</durationinseconds>
      </video>
      <audio><codec>eac3</codec><language>eng</language><channels>6</channels></audio>
      <subtitle><language>eng</language></subtitle>
    </streamdetails>
  </fileinfo>"""


def esc(s):
    return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def main():
    rnd = random.Random(20260727)
    if os.path.isdir(ROOT):
        shutil.rmtree(ROOT)
    os.makedirs(MOVIES, exist_ok=True)
    os.makedirs(TVSHOWS, exist_ok=True)

    plan = {"movies": [], "episodes": []}

    # ---- movies -----------------------------------------------------------
    for i, title in enumerate(MOVIE_TITLES):
        year = rnd.choice(range(1998, 2026))
        base = f"{title} ({year})"
        folder = os.path.join(MOVIES, base)
        stem = os.path.join(folder, base)
        minutes = rnd.choice([88, 94, 101, 107, 112, 118, 124, 131, 142])
        rating = round(rnd.uniform(5.4, 9.3), 1)
        genres = rnd.sample(GENRES, rnd.choice([1, 2, 3]))
        tmdb = 900000 + i

        fake_video(stem + ".mkv")
        make_art(stem + "-poster.jpg", 500, 750, title, str(year), base)
        make_art(
            stem + "-fanart.jpg",
            1280,
            720,
            title,
            f"{year} | {minutes} min",
            base + "f",
        )
        make_art(stem + "-landscape.jpg", 1000, 562, title, "", base + "l")
        make_art(stem + "-clearlogo.png", 800, 310, title, "", base, transparent=True)

        g = "\n".join(f"  <genre>{esc(x)}</genre>" for x in genres)
        nfo = f"""<?xml version="1.0" encoding="UTF-8" standalone="yes" ?>
<movie>
  <title>{esc(title)}</title>
  <originaltitle>{esc(title)}</originaltitle>
  <sorttitle>{esc(title)}</sorttitle>
  <year>{year}</year>
  <premiered>{year}-{rnd.randint(1, 12):02d}-{rnd.randint(1, 28):02d}</premiered>
  <runtime>{minutes}</runtime>
  <mpaa>{rnd.choice(MPAA)}</mpaa>
  <plot>{esc(title)} is synthetic bench content generated for Estuary POV widget development. It exists so a widget row has something to draw and so ratings, watched state and resume points can be judged against real library rows.</plot>
  <outline>Synthetic bench content for widget development.</outline>
  <tagline>Bench fixture, not real media.</tagline>
  <ratings>
    <rating name="themoviedb" max="10" default="true"><value>{rating}</value><votes>{rnd.randint(120, 48000)}</votes></rating>
    <rating name="imdb" max="10"><value>{max(1.0, round(rating - 0.4, 1))}</value><votes>{rnd.randint(500, 90000)}</votes></rating>
  </ratings>
  <userrating>{rnd.randint(4, 10)}</userrating>
  <uniqueid type="tmdb" default="true">{tmdb}</uniqueid>
{g}
  <studio>{esc(rnd.choice(STUDIOS))}</studio>
  <country>United States</country>
  <director>{esc(rnd.choice(["A. Rowe", "M. Castellan", "J. Okafor", "P. Lindqvist", "R. Amari"]))}</director>
{streamdetails(minutes)}
</movie>
"""
        with open(stem + ".nfo", "w") as f:
            f.write(nfo)

        # 8 watched, 8 in progress, 8 untouched. Deterministic by index so the
        # same title is always in the same state across reseeds.
        state = "new"
        if i % 3 == 0:
            state = "watched"
        elif i % 3 == 1:
            state = "inprogress"
        plan["movies"].append(
            {
                "title": title,
                "year": year,
                "state": state,
                "total": minutes * 60,
                "position": int(minutes * 60 * rnd.uniform(0.18, 0.72)),
            }
        )

    # ---- tv shows ---------------------------------------------------------
    for si, show in enumerate(SHOW_TITLES):
        year = rnd.choice(range(2012, 2025))
        sfolder = os.path.join(TVSHOWS, show)
        os.makedirs(sfolder, exist_ok=True)
        rating = round(rnd.uniform(6.2, 9.4), 1)
        genres = rnd.sample(GENRES, 2)
        make_art(os.path.join(sfolder, "poster.jpg"), 500, 750, show, str(year), show)
        make_art(os.path.join(sfolder, "fanart.jpg"), 1280, 720, show, "", show + "f")
        make_art(os.path.join(sfolder, "banner.jpg"), 1000, 185, show, "", show + "b")
        make_art(
            os.path.join(sfolder, "landscape.jpg"), 1000, 562, show, "", show + "l"
        )
        make_art(
            os.path.join(sfolder, "clearlogo.png"),
            800,
            310,
            show,
            "",
            show,
            transparent=True,
        )

        g = "\n".join(f"  <genre>{esc(x)}</genre>" for x in genres)
        with open(os.path.join(sfolder, "tvshow.nfo"), "w") as f:
            f.write(f"""<?xml version="1.0" encoding="UTF-8" standalone="yes" ?>
<tvshow>
  <title>{esc(show)}</title>
  <originaltitle>{esc(show)}</originaltitle>
  <sorttitle>{esc(show)}</sorttitle>
  <year>{year}</year>
  <premiered>{year}-{rnd.randint(1, 12):02d}-{rnd.randint(1, 28):02d}</premiered>
  <status>Continuing</status>
  <plot>{esc(show)} is synthetic bench content generated for Estuary POV widget development.</plot>
  <ratings>
    <rating name="themoviedb" max="10" default="true"><value>{rating}</value><votes>{rnd.randint(200, 22000)}</votes></rating>
  </ratings>
  <userrating>{rnd.randint(5, 10)}</userrating>
  <uniqueid type="tmdb" default="true">{800000 + si}</uniqueid>
{g}
  <studio>{esc(rnd.choice(STUDIOS))}</studio>
  <mpaa>{rnd.choice(["TV-14", "TV-MA", "TV-PG"])}</mpaa>
</tvshow>
""")

        for season in (1, 2):
            seasondir = os.path.join(sfolder, f"Season {season:02d}")
            os.makedirs(seasondir, exist_ok=True)
            make_art(
                os.path.join(sfolder, f"season{season:02d}-poster.jpg"),
                500,
                750,
                show,
                f"Season {season}",
                show + str(season),
            )
            for ep in range(1, 6):
                code = f"S{season:02d}E{ep:02d}"
                estem = os.path.join(seasondir, f"{show} - {code}")
                minutes = rnd.choice([42, 46, 51, 58])
                fake_video(estem + ".mkv", kb=6)
                make_art(
                    estem + "-thumb.jpg", 960, 540, f"{show}", f"{code}", show + code
                )
                erating = round(rnd.uniform(6.0, 9.6), 1)
                with open(estem + ".nfo", "w") as f:
                    f.write(f"""<?xml version="1.0" encoding="UTF-8" standalone="yes" ?>
<episodedetails>
  <title>{esc(show)} {code}</title>
  <showtitle>{esc(show)}</showtitle>
  <season>{season}</season>
  <episode>{ep}</episode>
  <plot>Synthetic bench episode {code} of {esc(show)}, generated for widget development.</plot>
  <aired>{year + season - 1}-{((ep * 2) % 12) + 1:02d}-{(ep * 3 % 27) + 1:02d}</aired>
  <runtime>{minutes}</runtime>
  <ratings>
    <rating name="themoviedb" max="10" default="true"><value>{erating}</value><votes>{rnd.randint(20, 3000)}</votes></rating>
  </ratings>
  <userrating>{rnd.randint(4, 10)}</userrating>
  <uniqueid type="tmdb" default="true">{700000 + si * 100 + season * 10 + ep}</uniqueid>
{streamdetails(minutes)}
</episodedetails>
""")
                # Show 0,1: fully watched S01 -> drives "Next Episodes".
                # Show 2,3: S01 watched except the last two -> drives both
                #           "Next Episodes" and "In Progress TV".
                # Show 4:   one episode mid-playback -> drives "In Progress".
                # Show 5:   untouched -> drives "Recently Added" / unwatched.
                state = "new"
                if si in (0, 1) and season == 1 or si in (2, 3) and season == 1 and ep <= 3:
                    state = "watched"
                elif si == 4 and season == 1 and ep in (1, 2):
                    state = "inprogress"
                elif si == 5 and season == 1 and ep == 1:
                    state = "inprogress"
                plan["episodes"].append(
                    {
                        "show": show,
                        "season": season,
                        "episode": ep,
                        "state": state,
                        "total": minutes * 60,
                        "position": int(minutes * 60 * rnd.uniform(0.2, 0.75)),
                    }
                )

    import json

    with open(os.path.join(os.path.dirname(ROOT), "seed-plan.json"), "w") as f:
        json.dump(plan, f, indent=1)

    nmov = len(plan["movies"])
    nep = len(plan["episodes"])
    print(f"generated {nmov} movies, {len(SHOW_TITLES)} shows, {nep} episodes")
    print(
        f"  watched movies:     {sum(1 for m in plan['movies'] if m['state'] == 'watched')}"
    )
    print(
        f"  in-progress movies: {sum(1 for m in plan['movies'] if m['state'] == 'inprogress')}"
    )
    print(
        f"  watched episodes:   {sum(1 for e in plan['episodes'] if e['state'] == 'watched')}"
    )
    print(
        f"  in-progress eps:    {sum(1 for e in plan['episodes'] if e['state'] == 'inprogress')}"
    )
    print(f"root: {ROOT}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
