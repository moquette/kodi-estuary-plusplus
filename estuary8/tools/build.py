#!/usr/bin/env python3
"""Package skin.estuary8 into an installable, deterministic zip.

Deliberately small. Estuary 8 owns its source, so there is nothing to fetch,
patch or rebrand at build time. This packages, stamps and verifies. That is all
a build needs to be.

    python3 estuary8/tools/build.py            build dist/skin.estuary8-<v>.zip
    python3 estuary8/tools/build.py --check    build twice, assert byte-identical

Deterministic means the same source always produces the same sha256: entries are
sorted, timestamps are pinned to the zip epoch (1980-01-01), permissions are
normalised, and no extra metadata is written. That is what makes it possible to
say "the box is running exactly this build" and be believed.
"""

import argparse
import hashlib
import pathlib
import re
import subprocess
import sys
import zipfile

ROOT = pathlib.Path(__file__).resolve().parents[1]
SRC = ROOT / "skin.estuary8"
DIST = ROOT / "dist"
SKIN_ID = "skin.estuary8"

# THE SKIN SHORTCUTS 3.x HARD BLOCK. Estuary 8 is script.skinshortcuts 3.x ONLY,
# and this is the gate that stops a 2.x reference ever becoming an artifact: no
# zip is written unless the floor check passes, so there is nothing to install,
# nothing to scp and nothing to push. Owner directive 2026-07-29, verbatim: "IT
# MAY NOT BE PUSHED TO MINI WITH ANY REFERENCE TO 2.X".
#
# Run as a subprocess rather than imported. An import would have to sit below
# ROOT (E402, which the linter rejects), and a subprocess also means the guard's
# own file:line output reaches the terminal unedited instead of being summarised
# by this file, which is the difference between a fixable failure and a mystery.
SKINSHORTCUTS_GUARD = pathlib.Path(__file__).resolve().parent / "check_skinshortcuts_floor.py"


def gate_skinshortcuts() -> None:
    if not SKINSHORTCUTS_GUARD.is_file():
        sys.exit(
            f"build refused: the Skin Shortcuts floor guard is missing at "
            f"{SKINSHORTCUTS_GUARD}. Deleting the guard is not a way past it."
        )
    result = subprocess.run([sys.executable, str(SKINSHORTCUTS_GUARD)], check=False)
    if result.returncode != 0:
        sys.exit(
            "build REFUSED: Skin Shortcuts 2.x is referenced (see above). "
            "Estuary 8 is 3.x only. Fix the skin, never the dependency."
        )


# Never ship these. Kodi does not need them and a stray .DS_Store changes the sha.
EXCLUDE_NAMES = {".DS_Store", "Thumbs.db", ".gitignore", ".gitkeep"}
EXCLUDE_DIRS = {"__pycache__", ".git", ".pytest_cache", ".ruff_cache"}

ZIP_EPOCH = (1980, 1, 1, 0, 0, 0)


def read_version() -> str:
    text = (SRC / "addon.xml").read_text(encoding="utf-8")
    m = re.search(r'<addon\s+[^>]*?id="([^"]+)"[^>]*?version="([^"]+)"', text, re.DOTALL)
    if not m:
        sys.exit("addon.xml: could not read id and version from the <addon> tag")
    addon_id, version = m.group(1), m.group(2)
    if addon_id != SKIN_ID:
        sys.exit(f"addon.xml declares id {addon_id!r}, expected {SKIN_ID!r}")
    return version


def collect() -> list[pathlib.Path]:
    files = []
    for p in SRC.rglob("*"):
        if not p.is_file():
            continue
        if p.name in EXCLUDE_NAMES:
            continue
        if EXCLUDE_DIRS.intersection(p.relative_to(SRC).parts):
            continue
        files.append(p)
    # Sorting is what makes the archive reproducible across filesystems.
    return sorted(files, key=lambda p: str(p.relative_to(SRC)))


# Unix mode bits, INCLUDING the file-type bits. Omitting S_IFREG and S_IFDIR is
# not cosmetic: an entry written as `0o644 << 16` declares mode 644 of no known
# type, and Kodi's installer will not extract it. Every zip Kodi accepts carries
# 0x81a40000 on files. This exact mistake shipped a skin zip that would not
# install, and the archive looked fine to `unzip -l`, so it cost real time.
FILE_ATTR = 0o100644 << 16  # S_IFREG | rw-r--r--
DIR_ATTR = (0o040755 << 16) | 0x10  # S_IFDIR | rwxr-xr-x, plus the MS-DOS dir flag


def build(out: pathlib.Path, files: list[pathlib.Path]) -> str:
    out.parent.mkdir(parents=True, exist_ok=True)
    if out.exists():
        out.unlink()

    # Explicit directory entries. Some archives Kodi accepts omit them, but the
    # ones it definitely accepts include them, and they cost almost nothing.
    dirs = set()
    for p in files:
        rel = p.relative_to(SRC)
        for parent in list(rel.parents)[:-1]:
            dirs.add(f"{SKIN_ID}/{parent.as_posix()}/")
    dirs.add(f"{SKIN_ID}/")

    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as z:
        for d in sorted(dirs):
            info = zipfile.ZipInfo(d, date_time=ZIP_EPOCH)
            info.external_attr = DIR_ATTR
            info.compress_type = zipfile.ZIP_STORED
            z.writestr(info, b"")
        for p in files:
            # Kodi expects the add-on id as the top-level directory in the zip.
            arc = f"{SKIN_ID}/{p.relative_to(SRC).as_posix()}"
            info = zipfile.ZipInfo(arc, date_time=ZIP_EPOCH)
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = FILE_ATTR
            z.writestr(info, p.read_bytes())
    return hashlib.sha256(out.read_bytes()).hexdigest()


def verify(out: pathlib.Path, version: str, count: int) -> None:
    """Fail loudly on the things that produce a silently broken skin."""
    with zipfile.ZipFile(out) as z:
        infos = z.infolist()
        names = z.namelist()
        bad = z.testzip()
        if bad:
            sys.exit(f"corrupt entry in archive: {bad}")

        payload = [i for i in infos if not i.is_dir()]
        if len(payload) != count:
            sys.exit(f"archive holds {len(payload)} files, expected {count}")

        # THE CHECK THAT MATTERS. An entry whose external_attr omits the Unix
        # file-type bits declares a mode of no known type, and Kodi's installer
        # will not extract it. The archive still lists cleanly with `unzip -l`,
        # so this fails silently and looks like a broken skin rather than a
        # broken zip. Every add-on zip Kodi accepts carries 0x81a40000 on files.
        wrong = [i.filename for i in payload if (i.external_attr >> 16) & 0o170000 != 0o100000]
        if wrong:
            sys.exit(
                f"{len(wrong)} entries lack the S_IFREG file-type bits, "
                f"e.g. {wrong[0]} has external_attr {payload[0].external_attr:#010x}. "
                "Kodi will refuse to install this archive."
            )

        roots = {n.split("/", 1)[0] for n in names}
        if roots != {SKIN_ID}:
            sys.exit(f"archive must contain exactly one top-level dir, found {sorted(roots)}")
        for required in (f"{SKIN_ID}/addon.xml", f"{SKIN_ID}/xml/Home.xml"):
            if required not in names:
                sys.exit(f"archive is missing {required}")
        addon = z.read(f"{SKIN_ID}/addon.xml").decode("utf-8")
        if f'version="{version}"' not in addon:
            sys.exit(f"addon.xml in the archive does not declare version {version}")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument(
        "--check",
        action="store_true",
        help="build twice and assert the two archives are byte-identical",
    )
    args = ap.parse_args()

    if not SRC.is_dir():
        sys.exit(f"skin source not found at {SRC}")

    # FIRST, before the version is even read and long before anything is written
    # to dist/. A refused build must leave no artifact behind at all, because an
    # artifact is the thing that gets scp'd to the mini three days later by
    # someone who was not here for the refusal.
    gate_skinshortcuts()

    version = read_version()
    files = collect()
    out = DIST / f"{SKIN_ID}-{version}.zip"

    digest = build(out, files)
    verify(out, version, len(files))

    print(f"  {out.relative_to(ROOT.parent)}")
    print(f"  {len(files)} files, {out.stat().st_size:,} bytes")
    print(f"  sha256 {digest}")

    if args.check:
        tmp = DIST / f".{SKIN_ID}-{version}.recheck.zip"
        again = build(tmp, files)
        tmp.unlink()
        if again != digest:
            sys.exit(f"NOT DETERMINISTIC: {digest} then {again}")
        print("  determinism: PASS, two builds byte-identical")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
