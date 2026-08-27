#!/usr/bin/env python3
"""Generate the rounded-corner artwork masks and the rounded rating overlay.

Output, all loose PNGs under skin.estuary8/media/ (nothing here goes into
Textures.xbt, and nothing here is third-party art):

    media/masks/poster.png            rounded-rect alpha mask, 1 : 1.44
    media/masks/thumb.png             rounded-rect alpha mask, 1.767 : 1
    media/overlays/overlay-bg-round.png   the watched-marker wash, corner cut

Why loose files work: CGUITextureManager::HasTexture asks every bundle first
and only then falls back to GetTexturePath, so a loose file is reachable
exactly when its name is NOT in Textures.xbt. Neither `masks/` nor
`overlays/overlay-bg-round.png` is in the bundle, so all three resolve.

--------------------------------------------------------------------------
The two numbers everything else is derived from
--------------------------------------------------------------------------

    corner radius = 8.5% of the artwork's SHORT side
    rating wash   = 40% of the artwork's SHORT side, square

8.5% is FENtastic's number, measured off its own masks rather than guessed:
media/masks/poster.png there is 236x324 with a 21px circular corner (8.9% of
236) and poster-50.png is 618x850 with 61px (9.9%). Ours sits just under both.

A `diffuse` mask is stretched onto the control's DRAWN rect (CGUITexture
CalculateSize, the scaleDiffuse branch), so its corner is circular on screen
only when the mask's aspect matches that rect's. That is why there are two
masks and not one, and why each is authored at 2x the skin units it is drawn
at, so the arc stays smooth where 1 skin unit is 2 physical pixels.

The 40% wash follows from wanting ONE rounded rating texture rather than one
per artwork size. The texture bakes its own rounding at

    21.25% of its own size  =  8.5% / 40%

so `size = 0.4 * the artwork's short side` makes the wash's rounded corner sit
exactly on the artwork's rounded corner at every call site, with no arithmetic
in the XML (which cannot do arithmetic anyway). Change `size` at a call site
and that stops being true.

--------------------------------------------------------------------------
The gradient is the skin's own, not a copy of anyone else's
--------------------------------------------------------------------------

media/Textures.xbt carries overlays/overlay-bg.png, 64x64, RGB (0,0,0) at
every pixel with the whole image in the alpha channel. Its alpha is a pure
function of the Manhattan distance from the BOTTOM-LEFT corner: measured over
all 4096 pixels, every pixel at a given d has an identical value. GRADIENT
below is that function, d = 0..62, lifted verbatim; past d=62 it is zero.

overlay-bg-round.png is therefore authored BOTTOM-LEFT peaked too, and with
its bottom-left corner cut. Both textures are drawn through the same

    <texture flipx="true" flipy="true">

which CGUIControlFactory::GetTexture turns into orientation 2 and
CGUITexture::OrientateTexture implements as a 180 degree rotation, putting the
peak at the top right. Square artwork uses the stock texture unchanged, so
there is no second copy of the gradient to drift.
"""

from __future__ import annotations

import argparse
import struct
import zlib
from pathlib import Path

SKIN = Path(__file__).resolve().parent.parent / "skin.estuary8"

# alpha of overlays/overlay-bg.png as a function of the Manhattan distance from
# its peak corner, in units of 1/63 of the image's side. Extracted from the
# bundled texture; it is exact, not a fit.
# fmt: off
GRADIENT = [
    190, 188, 186, 184, 182, 180, 178, 175, 172, 170, 167, 164, 161, 158, 155,
    152, 149, 145, 142, 139, 136, 132, 128, 124, 121, 118, 114, 110, 106, 103,
    99, 95, 91, 88, 84, 80, 76, 73, 69, 65, 61, 58, 55, 51, 48, 44, 41, 38, 35,
    32, 29, 26, 23, 20, 18, 16, 13, 10, 8, 7, 4, 3, 1, 0,
]
# fmt: on

RADIUS_FRACTION = 0.085  # of the artwork's short side
WASH_FRACTION = 0.40  # of the artwork's short side
CORNER_RADIUS_FRACTION = RADIUS_FRACTION / WASH_FRACTION  # 0.2125, of the wash

# Supersampling per axis inside the arc boxes only, so this is cheap: 64
# samples a pixel over roughly 4 x radius^2 pixels. At 4 the corner banded
# visibly in the alpha ramp of the rating wash, where coverage and gradient
# multiply; 8 is smooth.
SS = 8


def write_png(path: Path, width: int, height: int, rows: list[bytearray]) -> None:
    """8-bit RGBA, non-interlaced, deterministic."""
    raw = bytearray()
    for row in rows:
        raw.append(0)  # filter type 0 (None): keeps the writer trivially verifiable
        raw += row

    def chunk(tag: bytes, data: bytes) -> bytes:
        return (
            struct.pack(">I", len(data))
            + tag
            + data
            + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF)
        )

    png = b"\x89PNG\r\n\x1a\n"
    png += chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 6, 0, 0, 0))
    png += chunk(b"IDAT", zlib.compress(bytes(raw), 9))
    png += chunk(b"IEND", b"")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(png)


def rounded_coverage(width: int, height: int, radius: float, corners: str) -> list[list[float]]:
    """Coverage in 0..1 for a rectangle with `corners` rounded at `radius`.

    `corners` is any of 'tl', 'tr', 'bl', 'br' concatenated.
    """
    arcs = []
    if "tl" in corners:
        arcs.append((radius, radius, -1, -1))
    if "tr" in corners:
        arcs.append((width - radius, radius, 1, -1))
    if "bl" in corners:
        arcs.append((radius, height - radius, -1, 1))
    if "br" in corners:
        arcs.append((width - radius, height - radius, 1, 1))

    out = []
    step = 1.0 / SS
    for y in range(height):
        row = []
        for x in range(width):
            # a pixel wholly clear of every arc box needs no sampling
            inside_any_box = False
            for cx, cy, sx, sy in arcs:
                if (sx < 0 and x + 1 <= cx or sx > 0 and x >= cx) and (
                    sy < 0 and y + 1 <= cy or sy > 0 and y >= cy
                ):
                    inside_any_box = True
                    break
            if not inside_any_box:
                row.append(1.0)
                continue
            hits = 0
            for j in range(SS):
                py = y + (j + 0.5) * step
                for i in range(SS):
                    px = x + (i + 0.5) * step
                    ok = True
                    for cx, cy, sx, sy in arcs:
                        dx = px - cx
                        dy = py - cy
                        if (dx * sx > 0) and (dy * sy > 0) and dx * dx + dy * dy > radius * radius:
                            ok = False
                            break
                    if ok:
                        hits += 1
            row.append(hits / (SS * SS))
        out.append(row)
    return out


def make_frame(path: Path, width: int, height: int, radius: float, thickness: float) -> None:
    """A rounded-rect RING: the outer rect minus the same rect inset by `thickness`.

    This is the only shape that lets a border outline follow the artwork's
    rounding WITHOUT reordering the markup. The border control is drawn ON TOP
    of the poster, so it cannot become a filled plate; an alpha mask can only
    subtract, and subtracting a filled rounded rect from a 2px square outline
    erases the outline's corners instead of rounding them. A ring mask over
    colors/white.png reproduces the outline exactly, rounded.
    """
    t = thickness
    outer = rounded_coverage(width, height, radius, "tl tr bl br")
    inner = rounded_coverage(int(width - 2 * t), int(height - 2 * t), radius - t, "tl tr bl br")
    rows = []
    ti = int(t)
    for y in range(height):
        row = bytearray()
        for x in range(width):
            a = outer[y][x]
            iy, ix = y - ti, x - ti
            if 0 <= iy < len(inner) and 0 <= ix < len(inner[0]):
                a *= 1.0 - inner[iy][ix]
            row += bytes((255, 255, 255, int(round(a * 255))))
        rows.append(row)
    write_png(path, width, height, rows)
    print(
        f"{path.relative_to(SKIN)}  {width}x{height}  ring radius {radius:g}px "
        f"({radius / 2:g} skin units)  thickness {t:g}px"
    )


def make_mask(path: Path, width: int, height: int, radius: float, corners: str) -> None:
    """A white rounded rectangle in the alpha channel."""
    cov = rounded_coverage(width, height, radius, corners)
    rows = []
    for y in range(height):
        row = bytearray()
        for x in range(width):
            a = int(round(cov[y][x] * 255))
            row += bytes((255, 255, 255, a))
        rows.append(row)
    write_png(path, width, height, rows)
    print(
        f"{path.relative_to(SKIN)}  {width}x{height}  radius {radius:g} "
        f"({radius / 2:g} skin units)  corners: {corners}"
    )


def make_overlay_bg_round(path: Path, size: int) -> None:
    """overlay-bg's wash, peaking bottom-left, with that corner cut away.

    Bottom-left, not top-right, because the call sites draw it through
    flipx+flipy exactly as they draw the stock overlay-bg.png.
    """
    radius = CORNER_RADIUS_FRACTION * size
    cov = rounded_coverage(size, size, radius, "bl")
    last = size - 1
    rows = []
    for y in range(size):
        row = bytearray()
        for x in range(size):
            # d in the 64px source's units: 0 at the peak corner, 63 at the
            # anti-diagonal through the other two corners.
            d = (x + (last - y)) / last * 63.0
            i = int(d)
            if i >= len(GRADIENT) - 1:
                a = 0.0
            else:
                a = GRADIENT[i] + (GRADIENT[i + 1] - GRADIENT[i]) * (d - i)
            a *= cov[y][x]
            row += bytes((0, 0, 0, int(round(a))))
        rows.append(row)
    write_png(path, size, size, rows)
    print(
        f"{path.relative_to(SKIN)}  {size}x{size}  bottom-left radius {radius:g}px "
        f"({CORNER_RADIUS_FRACTION:.4%} of size)"
    )


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--check", action="store_true", help="fail if any file would change")
    args = ap.parse_args()

    # Every file is authored at 2x the skin units it is drawn at, and the four
    # masks come in two concentric PAIRS. A focus plate sits 6 (or 4) units
    # outside the artwork on every side, so its radius has to be the artwork's
    # PLUS that inset or the cyan ring comes out thicker at the corners than
    # along the flats: measured at 9.2px against 6.8px on the bench when both
    # shared one mask, which is visible at 5x zoom.
    #
    #   poster / poster-focus              InfoWallMovieLayout, WidgetListPosterInfo
    #     artwork 250x360, radius 21.25     the shared item layout behind Home's
    #     plate   262x372, radius 27.25     poster widgets, View_500, View_54 and
    #                                       the View_51 strip
    #   poster-large / poster-large-focus  View_51_Poster, the big focused poster
    #     artwork 476x716, radius 40.46
    #     plate   484x724, radius 44.46
    #
    # BAND is the 250x50 episode-count fade that sits ON the poster's bottom
    # edge. It has to carry the POSTER's radius, not 8.5% of its own short
    # side, or it pokes out of the two bottom corners.
    #
    # BORDER is the show_borders outline. It is a RING, and its 3.46px is the
    # thickness the texture it replaces actually rendered: dialogs/
    # border-movielayout.png is a 2px outline authored at 294 wide and drawn at
    # 254 units, so 2 * 254/294 = 1.73 units, which is 3.46 at 2x.
    small = RADIUS_FRACTION * 500
    large = RADIUS_FRACTION * 952
    targets = {
        SKIN / "media/masks/poster.png": ("mask", 500, 720, small, "tl tr bl br"),
        SKIN / "media/masks/poster-focus.png": ("mask", 524, 744, small + 12, "tl tr bl br"),
        SKIN / "media/masks/poster-large.png": ("mask", 952, 1432, large, "tl tr bl br"),
        SKIN / "media/masks/poster-large-focus.png": ("mask", 968, 1448, large + 8, "tl tr bl br"),
        SKIN / "media/masks/poster-band.png": ("mask", 500, 100, small, "bl br"),
        SKIN / "media/masks/poster-border.png": ("frame", 508, 728, small + 4, 3.46),
        SKIN / "media/overlays/overlay-bg-round.png": ("corner", 256),
    }

    before = {p: (p.read_bytes() if p.exists() else None) for p in targets}
    for path, spec in targets.items():
        if spec[0] == "mask":
            make_mask(path, spec[1], spec[2], spec[3], spec[4])
        elif spec[0] == "frame":
            make_frame(path, spec[1], spec[2], spec[3], spec[4])
        else:
            make_overlay_bg_round(path, spec[1])

    if args.check:
        changed = [p for p in targets if before[p] != p.read_bytes()]
        for p in changed:
            if before[p] is None:
                p.unlink()
            else:
                p.write_bytes(before[p])
        if changed:
            print("CHANGED: " + ", ".join(str(p.relative_to(SKIN)) for p in changed))
            return 1
        print(f"check: all {len(targets)} files match what this script generates")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
