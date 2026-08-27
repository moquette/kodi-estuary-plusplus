#!/usr/bin/env python3
"""Package plugin.video.estuary8.search into an installable, deterministic zip.

The add-on is the Estuary 8 streaming-search result filter. It proxies a
streaming provider's own movie and TV-show search, drops the art-less
placeholder cards, and re-serves the survivors as one poster wall, movies first
then TV shows. See plugin.video.estuary8.search/addon.xml for the summary.

    python3 estuary8/tools/build_search.py            build the zip
    python3 estuary8/tools/build_search.py --check    build twice, assert identical

This is deliberately a sibling of build.py and build_shortcuts.py rather than a
generalisation of either. build.py is the gate that stands between the skin
source and every box, and it carries a hard block that refuses to write an
artifact. Rewriting it into a many-target builder to save a file would put that
block at risk for no gain.

Determinism means the same source always produces the same sha256: entries are
sorted, timestamps pinned to the zip epoch, permissions normalised. That is what
makes "the box is running exactly this build" a checkable claim.
"""

import argparse
import hashlib
import pathlib
import re
import sys
import zipfile

ROOT = pathlib.Path(__file__).resolve().parents[1]
ADDON_ID = "plugin.video.estuary8.search"
SRC = ROOT / ADDON_ID
DIST = ROOT / "dist"

# Never ship these. ruff.toml is a development config Kodi never reads.
# LICENSE.txt DOES ship, because the licence has to travel with the code.
EXCLUDE_NAMES = {".DS_Store", "Thumbs.db", ".gitignore", ".gitkeep", "ruff.toml"}
EXCLUDE_DIRS = {"__pycache__", ".git", ".pytest_cache", ".ruff_cache"}

ZIP_EPOCH = (1980, 1, 1, 0, 0, 0)

# Unix mode bits INCLUDING the file-type bits. An entry written as 0o644 << 16
# declares mode 644 of no known type and Kodi's installer silently refuses to
# extract it, while `unzip -l` still lists the archive as fine. This exact
# mistake has already shipped a skin zip that would not install.
FILE_ATTR = 0o100644 << 16  # S_IFREG | rw-r--r--
DIR_ATTR = (0o040755 << 16) | 0x10  # S_IFDIR | rwxr-xr-x, plus the MS-DOS dir flag


def read_version() -> str:
    text = (SRC / "addon.xml").read_text(encoding="utf-8")
    m = re.search(r'<addon\s+[^>]*?id="([^"]+)"[^>]*?version="([^"]+)"', text, re.DOTALL)
    if not m:
        sys.exit("addon.xml: could not read id and version from the <addon> tag")
    addon_id, version = m.group(1), m.group(2)
    if addon_id != ADDON_ID:
        sys.exit(f"addon.xml declares id {addon_id!r}, expected {ADDON_ID!r}")
    return version


def collect() -> list[pathlib.Path]:
    files = []
    for p in SRC.rglob("*"):
        if not p.is_file():
            continue
        if p.name in EXCLUDE_NAMES or p.suffix == ".pyc":
            continue
        if EXCLUDE_DIRS.intersection(p.relative_to(SRC).parts):
            continue
        files.append(p)
    return sorted(files, key=lambda p: str(p.relative_to(SRC)))


def build(out: pathlib.Path, files: list[pathlib.Path]) -> str:
    out.parent.mkdir(parents=True, exist_ok=True)
    if out.exists():
        out.unlink()

    dirs = set()
    for p in files:
        rel = p.relative_to(SRC)
        for parent in list(rel.parents)[:-1]:
            dirs.add(f"{ADDON_ID}/{parent.as_posix()}/")
    dirs.add(f"{ADDON_ID}/")

    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as z:
        for d in sorted(dirs):
            info = zipfile.ZipInfo(d, date_time=ZIP_EPOCH)
            info.external_attr = DIR_ATTR
            info.compress_type = zipfile.ZIP_STORED
            z.writestr(info, b"")
        for p in files:
            arc = f"{ADDON_ID}/{p.relative_to(SRC).as_posix()}"
            info = zipfile.ZipInfo(arc, date_time=ZIP_EPOCH)
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = FILE_ATTR
            z.writestr(info, p.read_bytes())
    return hashlib.sha256(out.read_bytes()).hexdigest()


def verify(out: pathlib.Path, version: str, count: int) -> None:
    """Fail loudly on the things that produce a silently broken add-on."""
    with zipfile.ZipFile(out) as z:
        infos = z.infolist()
        names = z.namelist()
        bad = z.testzip()
        if bad:
            sys.exit(f"corrupt entry in archive: {bad}")

        payload = [i for i in infos if not i.is_dir()]
        if len(payload) != count:
            sys.exit(f"archive holds {len(payload)} files, expected {count}")

        wrong = [i.filename for i in payload if (i.external_attr >> 16) & 0o170000 != 0o100000]
        if wrong:
            sys.exit(
                f"{len(wrong)} entries lack the S_IFREG file-type bits, e.g. {wrong[0]}. "
                "Kodi will refuse to install this archive."
            )

        roots = {n.split("/", 1)[0] for n in names}
        if roots != {ADDON_ID}:
            sys.exit(f"archive must contain exactly one top-level dir, found {sorted(roots)}")

        for required in (
            f"{ADDON_ID}/addon.xml",
            f"{ADDON_ID}/addon.py",
            f"{ADDON_ID}/LICENSE.txt",
        ):
            if required not in names:
                sys.exit(f"archive is missing {required}")

        addon = z.read(f"{ADDON_ID}/addon.xml").decode("utf-8")
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
        sys.exit(f"add-on source not found at {SRC}")

    version = read_version()
    files = collect()
    out = DIST / f"{ADDON_ID}-{version}.zip"

    digest = build(out, files)
    verify(out, version, len(files))

    print(f"  {out.relative_to(ROOT.parent)}")
    print(f"  {len(files)} files, {out.stat().st_size:,} bytes")
    print(f"  sha256 {digest}")

    if args.check:
        tmp = DIST / f".{ADDON_ID}-{version}.recheck.zip"
        again = build(tmp, files)
        tmp.unlink()
        if again != digest:
            sys.exit(f"NOT DETERMINISTIC: {digest} then {again}")
        print("  determinism: PASS, two builds byte-identical")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
