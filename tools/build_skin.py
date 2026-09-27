#!/usr/bin/env python3
"""Build a Kodi-installable, byte-reproducible zip for a skin in this repo.

Why this exists: the first skin.estuary.plusplus zip was hand-made, which left the
served bytes with no provenance and no way to prove they equal the committed
source. This script builds from the git working tree, pins every timestamp, and
can build twice and byte-compare, so "the repo serves exactly this commit" is a
measurement rather than a claim.

    python3 tools/build_skin.py skin.estuary.plusplus            # build into dist/
    python3 tools/build_skin.py skin.estuary.plusplus --check    # build twice, byte-compare
    python3 tools/build_skin.py skin.estuary.plusplus --verify-clean

--verify-clean additionally asserts the skin dir has no uncommitted change, so a
release zip can never carry an edit that is not in git.
"""

from __future__ import annotations

import argparse
import hashlib
import pathlib
import re
import subprocess
import sys
import zipfile

ROOT = pathlib.Path(__file__).resolve().parent.parent

# Everything a macOS checkout leaves behind that must never reach a box.
EXCLUDE_NAMES = {".DS_Store", "Thumbs.db"}
EXCLUDE_PREFIXES = ("._",)
EXCLUDE_DIRS = {"__MACOSX", "__pycache__", ".git", ".ruff_cache", ".pytest_cache"}

# The 1980-01-01 zip epoch. Zip cannot store anything earlier, and pinning it is
# what makes two builds of the same source byte-identical.
ZIP_EPOCH = (1980, 1, 1, 0, 0, 0)

# Unix mode bits INCLUDING the file-type bits. Omitting S_IFREG is not cosmetic:
# an entry written as 0o644 << 16 declares mode 644 of no known type and Kodi's
# installer refuses to extract it, while `unzip -l` still lists the archive
# cleanly. That failure mode has shipped an uninstallable skin zip before.
FILE_ATTR = 0o100644 << 16
DIR_ATTR = (0o040755 << 16) | 0x10


def read_addon(src: pathlib.Path) -> tuple[str, str]:
    text = (src / "addon.xml").read_text(encoding="utf-8")
    match = re.search(
        r'<addon\s+[^>]*?id="([^"]+)"[^>]*?version="([^"]+)"', text, re.DOTALL
    )
    if not match:
        sys.exit(f"{src}/addon.xml: could not read id and version from the <addon> tag")
    return match.group(1), match.group(2)


def collect(src: pathlib.Path) -> list[pathlib.Path]:
    files = []
    for path in src.rglob("*"):
        if not path.is_file():
            continue
        rel = path.relative_to(src)
        if path.name in EXCLUDE_NAMES or path.name.startswith(EXCLUDE_PREFIXES):
            continue
        if EXCLUDE_DIRS.intersection(rel.parts):
            continue
        files.append(path)
    # Sorting is what makes the archive reproducible across filesystems.
    return sorted(files, key=lambda p: str(p.relative_to(src)))


def build(
    out: pathlib.Path, src: pathlib.Path, addon_id: str, files: list[pathlib.Path]
) -> str:
    out.parent.mkdir(parents=True, exist_ok=True)
    if out.exists():
        out.unlink()

    dirs = {f"{addon_id}/"}
    for path in files:
        rel = path.relative_to(src)
        for parent in list(rel.parents)[:-1]:
            dirs.add(f"{addon_id}/{parent.as_posix()}/")

    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
        for name in sorted(dirs):
            info = zipfile.ZipInfo(name, date_time=ZIP_EPOCH)
            info.external_attr = DIR_ATTR
            info.compress_type = zipfile.ZIP_STORED
            archive.writestr(info, b"")
        for path in files:
            # Kodi expects the add-on id as the single top-level directory.
            arc = f"{addon_id}/{path.relative_to(src).as_posix()}"
            info = zipfile.ZipInfo(arc, date_time=ZIP_EPOCH)
            info.external_attr = FILE_ATTR
            info.compress_type = zipfile.ZIP_DEFLATED
            archive.writestr(info, path.read_bytes())
    return hashlib.sha256(out.read_bytes()).hexdigest()


def verify(out: pathlib.Path, addon_id: str, version: str, count: int) -> None:
    """Fail loudly on the things that produce a silently broken skin."""
    with zipfile.ZipFile(out) as archive:
        corrupt = archive.testzip()
        if corrupt:
            sys.exit(f"corrupt entry in archive: {corrupt}")
        names = archive.namelist()
        payload = [i for i in archive.infolist() if not i.is_dir()]
        if len(payload) != count:
            sys.exit(f"archive holds {len(payload)} files, expected {count}")
        wrong = [
            i.filename
            for i in payload
            if (i.external_attr >> 16) & 0o170000 != 0o100000
        ]
        if wrong:
            sys.exit(
                f"{len(wrong)} entries lack the S_IFREG file-type bits, e.g. "
                f"{wrong[0]}. Kodi will refuse to install this archive."
            )
        roots = {n.split("/", 1)[0] for n in names}
        if roots != {addon_id}:
            sys.exit(f"archive needs exactly one top-level dir, found {sorted(roots)}")
        if names[0] != f"{addon_id}/":
            sys.exit(f"first archive entry must be {addon_id}/, found {names[0]}")
        required = [f"{addon_id}/addon.xml"]
        if f"{addon_id}/addon.xml" in names:
            inner = archive.read(f"{addon_id}/addon.xml").decode("utf-8")
            # xml/Home.xml is the cheapest proof that a SKIN archive carries its
            # payload rather than just its metadata, and it has caught a
            # truncated build before. It is meaningless for the service add-on
            # this repo also ships, so the check follows the extension point
            # rather than the tool's name.
            if "xbmc.gui.skin" in inner:
                required.append(f"{addon_id}/xml/Home.xml")
            for path in required:
                if path not in names:
                    sys.exit(f"archive is missing {path}")
            if f'version="{version}"' not in inner:
                sys.exit(f"addon.xml in the archive does not declare version {version}")
        else:
            sys.exit(f"archive is missing {required[0]}")


def git_dirty(rel: str) -> list[str]:
    out = subprocess.run(
        ["git", "-C", str(ROOT), "status", "--porcelain", "--", rel],
        capture_output=True,
        text=True,
        check=True,
    ).stdout
    return [line for line in out.splitlines() if line.strip()]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("skin", help="the skin directory, e.g. skin.estuary.plusplus")
    parser.add_argument("--out", default="dist", help="output dir (default: dist)")
    parser.add_argument(
        "--check",
        action="store_true",
        help="build twice and assert the two archives are byte-identical",
    )
    parser.add_argument(
        "--verify-clean",
        action="store_true",
        help="refuse to build when the skin dir has uncommitted changes",
    )
    args = parser.parse_args()

    src = (ROOT / args.skin).resolve()
    if not (src / "addon.xml").is_file():
        return int(bool(sys.stderr.write(f"no addon.xml under {src}\n"))) or 2

    if args.verify_clean:
        dirty = [d for d in git_dirty(args.skin) if not d.endswith(".DS_Store")]
        if dirty:
            sys.exit(
                "skin dir has uncommitted changes, refusing to build:\n"
                + "\n".join(dirty)
            )

    addon_id, version = read_addon(src)
    if addon_id != src.name:
        sys.exit(f"addon.xml declares id {addon_id!r} but the dir is {src.name!r}")

    files = collect(src)
    out = ROOT / args.out / f"{addon_id}-{version}.zip"
    digest = build(out, src, addon_id, files)
    verify(out, addon_id, version, len(files))

    if args.check:
        again = ROOT / args.out / f"{addon_id}-{version}.recheck.zip"
        digest2 = build(again, src, addon_id, files)
        again.unlink()
        if digest != digest2:
            sys.exit(f"NOT reproducible: {digest} != {digest2}")
        print("reproducible: two builds are byte-identical")

    print(f"{out.relative_to(ROOT)}  {len(files)} files  {out.stat().st_size} bytes")
    print(f"sha256 {digest}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
