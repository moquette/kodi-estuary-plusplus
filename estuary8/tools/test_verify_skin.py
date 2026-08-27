#!/usr/bin/env python3
"""Self-test for verify_skin.py.

A verification harness that has never been shown to fail is not a harness, it
is a decoration. This reproduces the exact defect that motivated verify_skin.py
and asserts that it is caught.

The defect: a regex meant to delete one image control used a filler pattern
that a </control> line satisfies, so it ran past its own closing tag and took
sibling controls with it. It removed the category list id 9000 and scrollbar 60
from SkinSettings.xml and the hit-catcher button 6131 from Includes_MediaMenu.xml,
and it left Includes.xml:47 referencing 6131. Every XML well-formedness check
passed, because deleting a whole balanced control leaves valid XML.

Run:
    python3 estuary8/tools/test_verify_skin.py
"""

from __future__ import annotations

import io
import re
import shutil
import subprocess
import sys
import tarfile
import tempfile
import xml.parsers.expat
from pathlib import Path

HERE = Path(__file__).resolve().parent
VERIFY = HERE / "verify_skin.py"
BASELINE = "cd28cb9"
PREFIX = "estuary8/skin.estuary8"

FAILURES: list[str] = []


def check(label: str, ok: bool, detail: str = "") -> None:
    print(f"  {'PASS' if ok else 'FAIL'}  {label}")
    if not ok:
        FAILURES.append(f"{label}: {detail}")
        if detail:
            for line in detail.splitlines()[:12]:
                print(f"        {line}")


def repo_root() -> Path:
    out = subprocess.run(
        ["git", "rev-parse", "--show-toplevel"],
        cwd=HERE,
        capture_output=True,
        check=True,
    )
    return Path(out.stdout.decode().strip())


def extract_baseline(repo: Path, dest: Path) -> None:
    blob = subprocess.run(
        ["git", "archive", BASELINE, "--", PREFIX],
        cwd=repo,
        capture_output=True,
        check=True,
    ).stdout
    with tarfile.open(fileobj=io.BytesIO(blob)) as tar:
        tar.extractall(dest, filter="data")


def run_verify(skin: Path) -> tuple[int, str]:
    out = subprocess.run(
        [sys.executable, str(VERIFY), "--skin", str(skin), "--baseline", BASELINE, "--max", "60"],
        cwd=HERE,
        capture_output=True,
        check=False,
    )
    return out.returncode, out.stdout.decode() + out.stderr.decode()


def element_spans(path: Path) -> list[tuple[int, int, str, dict]]:
    """(start_line, end_line, tag, attrs) for every element, so a cut can be
    made on real element boundaries rather than guessed line numbers."""
    spans: list[tuple[int, int, str, dict]] = []
    stack: list[tuple[str, dict, int]] = []
    parser = xml.parsers.expat.ParserCreate()

    def start(name, attrs):
        stack.append((name, attrs, parser.CurrentLineNumber))

    def end(_name):
        name, attrs, line = stack.pop()
        spans.append((line, parser.CurrentLineNumber, name, attrs))

    parser.StartElementHandler = start
    parser.EndElementHandler = end
    parser.Parse(path.read_bytes(), True)
    return sorted(spans)


def is_well_formed(path: Path) -> bool:
    data = re.sub(
        rb"&(?!(?:[A-Za-z][A-Za-z0-9]*|#[0-9]+|#x[0-9A-Fa-f]+);)",
        b"&amp;",
        path.read_bytes(),
    )
    try:
        xml.parsers.expat.ParserCreate().Parse(data, True)
        return True
    except xml.parsers.expat.ExpatError:
        return False


def cut_siblings(path: Path, first_line: int, count: int) -> int:
    """Delete `count` consecutive balanced siblings starting at `first_line`.

    This is what the buggy regex effectively did: it consumed past its own
    closing tag into the next sibling, and the next, and stopped somewhere that
    still happened to balance.
    """
    spans = element_spans(path)
    top = [s for s in spans if s[0] >= first_line]
    chosen, cursor = [], first_line
    for start, end, _tag, _attrs in top:
        if start == cursor:
            chosen.append((start, end))
            cursor = end + 1
            if len(chosen) == count:
                break
    if not chosen:
        raise SystemExit(f"no element starts at {path}:{first_line}")
    lo, hi = chosen[0][0], chosen[-1][1]
    lines = path.read_text(encoding="utf-8").splitlines(keepends=True)
    removed = hi - lo + 1
    path.write_text("".join(lines[: lo - 1] + lines[hi:]), encoding="utf-8")
    return removed


def find_line(path: Path, needle: str) -> int:
    for i, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if needle in line:
            return i
    raise SystemExit(f"{needle!r} not found in {path}")


def anchor(path: Path, needle: str, opener: str) -> int:
    """Line of the nearest `opener` at or above the line holding `needle`.

    Anchoring by search rather than by arithmetic offset, so the test keeps
    working when the file above the fault site changes.
    """
    lines = path.read_text(encoding="utf-8").splitlines()
    start = find_line(path, needle)
    for i in range(start - 1, -1, -1):
        if opener in lines[i]:
            return i + 1
    raise SystemExit(f"no {opener!r} above {needle!r} in {path}")


def main() -> int:
    repo = repo_root()
    with tempfile.TemporaryDirectory(prefix="verify-skin-selftest-") as tmp:
        root = Path(tmp)
        pristine = root / "pristine"
        extract_baseline(repo, pristine)
        skin = pristine / PREFIX

        print("\ncase 1: baseline against itself must be clean")
        code, out = run_verify(skin)
        check("exit code 0", code == 0, out[-2500:])
        check("says PASS", "PASS: no structural regression" in out, out[-800:])
        check("no FATAL", "FATAL: 0" in out, out[:400])

        print("\ncase 2: the historical greedy-regex deletion must be caught")
        faulty = root / "faulty"
        shutil.copytree(pristine, faulty, symlinks=True)
        fskin = faulty / PREFIX

        settings = fskin / "xml" / "SkinSettings.xml"
        menu = fskin / "xml" / "Includes_MediaMenu.xml"
        n1 = cut_siblings(settings, anchor(settings, 'id="9000"', '<control type="group">'), 5)
        n2 = cut_siblings(menu, anchor(menu, "colors/black.png", '<control type="image">'), 4)
        print(f"  injected: SkinSettings.xml -{n1} lines, Includes_MediaMenu.xml -{n2} lines")

        check("SkinSettings.xml is still WELL FORMED", is_well_formed(settings))
        check("Includes_MediaMenu.xml is still WELL FORMED", is_well_formed(menu))
        check("id 9000 really is gone", 'id="9000"' not in settings.read_text(encoding="utf-8"))
        check("id 6131 really is gone", 'id="6131"' not in menu.read_text(encoding="utf-8"))

        code, out = run_verify(fskin)
        check("exit code 1", code == 1, out[-2500:])
        check("says FAIL", "FAIL: structural regressions found" in out)
        for want, label in (
            ("control census", "control census fires"),
            ("SkinSettings.xml:", "names SkinSettings.xml with a line"),
            ("id=9000", "names the vanished list id 9000"),
            ("id=6131", "names the vanished button id 6131"),
            ("FOCUSABLE", "flags them as focusable"),
            ("6131 referenced", "flags the dangling reference to 6131"),
            ("xml/Includes.xml:47", "points at Includes.xml:47, the stale reference"),
            ("scrollbar x1", "reports the lost control type breakdown"),
        ):
            check(label, want in out, f"missing {want!r} in output")

        print("\ncase 3: a lone <style> removal must NOT be reported as a control loss")
        quiet = root / "quiet"
        shutil.copytree(pristine, quiet, symlinks=True)
        font = quiet / PREFIX / "xml" / "Font.xml"
        font.write_text(
            font.read_text(encoding="utf-8").replace("<style>bold</style>", "", 1),
            encoding="utf-8",
        )
        code, out = run_verify(quiet / PREFIX)
        check("no control census regression", "control census: 3 file" not in out)
        check("font table change is reported as INFO", "id(s) redefined" in out, out[-1500:])

    print("\n" + "=" * 60)
    if FAILURES:
        print(f"{len(FAILURES)} self-test failure(s):")
        for f in FAILURES:
            print(f"  - {f.splitlines()[0]}")
        return 1
    print("all self-tests passed")
    return 0


if __name__ == "__main__":
    sys.exit(main())
