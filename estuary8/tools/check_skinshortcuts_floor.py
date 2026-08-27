#!/usr/bin/env python3
"""Assert that Estuary 8 cannot reference, resolve or ship Skin Shortcuts 2.x.

Estuary 8 is Kodi 22 "Piers" and `script.skinshortcuts` **3.x ONLY**. Skin
Shortcuts 2.x is the legacy line Estuary 7 runs, and the two skins live in the
same working tree, so reaching for the wrong one is a one-character mistake with
no symptom until a menu save silently does the wrong thing.

    python3 estuary8/tools/check_skinshortcuts_floor.py
    python3 estuary8/tools/check_skinshortcuts_floor.py --quiet
    python3 estuary8/tools/check_skinshortcuts_floor.py --self-test

Owner directive, 2026-07-29, verbatim: "FOR ESTUARY 8 WE NEED A HARD FUCKING
BLOCK. ON 2.X", "MAKE IT MANDATORY", "ESTUARY 8 CAN NOT AND MUST NOT PASS
LINTING... FORMATTING... ANYTHING WITHOUT SHORTCUTS 3.X", "FORMATTING MAY NOT
PASS IF SHORTCUTS 2.X IS REFERENCED. IT MAY NOT BE PUSHED TO MINI WITH ANY
REFERENCE TO 2.X".

Why the guard exists as code and not as a note
----------------------------------------------
MEASURED 2026-07-29: `script.skinshortcuts` 2.0.3 had been unpacked into THREE
separate session scratchpads under
`/private/tmp/claude-501/-Users-moquette-Code-moquette-kodi/*/scratchpad/ss203`,
two of them from other sessions. Nothing in the tree stopped a 2.x reference
landing in the skin, so the only thing standing between the legacy version and
the shipped artifact was whoever happened to be reading. This replaces that with
an exit code.

The five things this refuses
----------------------------
1. `skin.estuary8/addon.xml` not declaring `script.estuary8.shortcuts` at 3.0.0
   or above. A missing import fails, an import below 3.0.0 fails, and
   `optional="true"` fails because an optional dependency is one Kodi is free to
   skip entirely.
2. A `minversion` attribute on that import. See the trap below; this is the one
   that looks like a tidy-up and re-admits 2.x silently.
3. `skin.estuary8/addon.xml` declaring `script.skinshortcuts` AT ALL, at any
   version, alone or beside the fork. See "why the external is now a failure"
   below. The pinning rules in (1) and (2) are still applied to it when it is
   present, so the report says both that it must not be there and what is wrong
   with how it was pinned.
4. ANY reference to a 2.x Skin Shortcuts version anywhere in the shipped skin
   tree (`skin.estuary8/**`): version strings, vendored directory names, zip
   filenames, and prose inside shipped files. Prose counts on purpose. A comment
   reading "2.0.3 did X" is precisely the breadcrumb that sent three sessions off
   to unpack 2.0.3.
5. A `script.skinshortcuts` directory anywhere under the repo whose own
   `addon.xml` declares a version below 3.0.0, i.e. a vendored or staged legacy
   copy.

Why the external add-on is now a FAILURE and not an alternative
---------------------------------------------------------------
Until 2026-07-31 this file accepted EITHER `script.estuary8.shortcuts` or
`script.skinshortcuts` as the declared provider, on identical pinning rules. The
disjunction itself was the hole: re-adding
`<import addon="script.skinshortcuts"/>` to the skin tomorrow would have PASSED,
because the guard only ever asserted that *a* shortcuts add-on was declared.

MEASURED 2026-07-31, and this is not hypothetical. A real install on the Fire TV
stick ts1 pulled the external add-on down from a repository and the install
failed; the owner had to find and uninstall it by hand. A stale Kodi tree on that
same box still carries `skin.estuary8` 0.1.16, whose `addon.xml` names
`script.skinshortcuts` twice, beside a cached
`addons/packages/script.skinshortcuts-3.0.1.zip` of 628,918 bytes that Kodi
fetched to satisfy it. The skin's own `addon.xml` records the same episode from
the other side: it "briefly also imported the external script.skinshortcuts,
purely because the floor guard asserted through that id, which installed two
add-ons that looked identical in the add-on browser".

So the guard was not merely permissive, it was the REASON the import was added.
Estuary 8 ships its own fork under its own id and that fork is the only provider
it may resolve. The external one is now refused outright.

Note what this does NOT refuse: naming `script.skinshortcuts` in a COMMENT inside
`addon.xml`. The shipped file does exactly that, to explain why the import is
gone, and a guard that failed on its own explanation would be deleted within a
day. The assertion keys on the parsed `<import>` element, which is the only thing
Kodi acts on; a self-test case pins that distinction.

The `minversion` trap, which applies here identically to the Kodi floor
--------------------------------------------------------------------
Kodi's `DependencyInfo` constructor is

    versionMin(versionMin.empty() ? version : versionMin)

so with NO `minversion` the declared `version` IS the hard minimum. Add a
`minversion` and `version` degrades to an upper bound, and 2.x is admitted with
no error, no warning and no visible diff beyond one attribute. This is the same
mechanism `check_kodi_floor.py` documents and proves on real hardware
(`notes/kodi22-hardfail.md`); it is not re-derived here, it is reused.

How the 2.x scan avoids being either useless or unusable
-------------------------------------------------------
A bare grep for `2.0.3` across the skin would hit unrelated version numbers, and
a grep for "skinshortcuts" would hit 17 legitimate files. So the scan pairs the
two: it finds every Skin Shortcuts mention and looks for a 2.x version token
inside a symmetric 120-character window around it, which crosses newlines so a
wrapped `<import>` cannot hide.

The window is 120 characters because that was measured, not chosen. Against the
real shipped tree (229 text files) it returns exactly one hit. Two nearby lines
are measured NOT to trip it and both are in the self-test as must-pass cases, so
a future tightening that breaks them fails loudly:

    xml/script-skinshortcuts.xml:332  <label>$ADDON[script.skinshortcuts 32044] 2</label>
    shortcuts/properties.xml:117      property="widget.2" ... $ADDON[script.skinshortcuts 32...

A bare `2` therefore only counts when it is ADJACENT to the mention ("Skin
Shortcuts 2", "skinshortcuts v2"), never when it merely sits nearby.

What this does NOT scan
-----------------------
Compiled `media/*.xbt` bundles and other binaries. They hold textures, not
version strings, and the sources that build them are scanned. If a 2.x reference
is ever compiled into a bundle, this will not see it.
"""

from __future__ import annotations

import argparse
import os
import re
import sys
import tempfile
import xml.etree.ElementTree as ET
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]  # estuary8/estuary8
REPO = Path(__file__).resolve().parents[2]  # estuary8
SKIN = ROOT / "skin.estuary8"
ADDON_XML = SKIN / "addon.xml"

# The EXTERNAL add-on. Estuary 8 must not import it: see "why the external is
# now a FAILURE" in the module docstring. It is still floored and pin-checked
# when present, so the report never says only "remove this" when the way it was
# pinned is also wrong.
DEP_ID = "script.skinshortcuts"
# OURS: a fork of the 3.x line under its own add-on id, and the ONLY provider
# the skin may declare. This does NOT relax anything else in this file: every
# content, path and prose scan below is unchanged, so a legacy reference still
# fails lint, format, build, push and bench exactly as before.
FORK_ID = "script.estuary8.shortcuts"
FLOOR = "3.0.0"

# Every way this project has spelled it: script.skinshortcuts, skinshortcuts,
# Skin Shortcuts, SkinShortcuts, skin-shortcuts, skin_shortcuts.
MENTION = re.compile(r"s(?:cript\.)?kin[\s._-]?shortcuts", re.IGNORECASE)

# A dotted 2.x version token, one to four components, so 2.0, 2.0.3 and 2.0.3.1
# all count. The lookbehind stops it matching inside a longer number, so "12.0"
# and the "2" of "3.2.0" and "widget.2" are not hits.
#
# The trailing lookahead is `(?!\.?\d)` and NOT `(?![\w.])`, which is the
# stricter form the first draft used. That draft silently missed the filename
# `script.skinshortcuts-2.0.3.zip`, because the `.` of `.zip` tripped the `[\w.]`
# lookahead and the whole token was discarded. The self-test caught it; a
# reviewer reading the regex would not have. So: refuse only when what follows is
# another version component.
DOTTED_2X = re.compile(r"(?<![\w.])2(?:\.\d+){1,3}(?!\.?\d)|(?<![\w.])2\.x\b", re.IGNORECASE)

# A bare 2 counts ONLY where it directly follows the mention. Anchored at the
# start of the text after the mention, so "skinshortcuts 32044] 2" cannot match.
#
# The trailing lookahead is TWO assertions, not one, and the split matters.
# It was `(?![\w.])`, which lumped "another version component" together with
# "a full stop" and so silently missed the single most natural way to write the
# thing this guard exists to catch: a sentence ENDING in it, "Behaves the way
# Skin Shortcuts 2." Found by QA 2026-07-30. `(?!\.?\d)` still refuses to fire
# when a version component follows, because DOTTED_2X owns that case and would
# otherwise report the same hit twice; `(?!\w)` still refuses on "2nd". A
# sentence period now falls between the two and counts. Both new shapes are in
# the self-test below, and both were MEASURED to be missed by the old form.
ADJACENT_2 = re.compile(r"\A[\s._-]*(?:v|ver|version)?\s*2(?!\.?\d)(?!\w)", re.IGNORECASE)

# The legacy shorthand, measured to appear zero times in the shipped tree today.
SS2 = re.compile(r"\bSS\s?2(?![\w.])")

WINDOW = 120

BINARY_SUFFIXES = {
    ".png",
    ".jpg",
    ".jpeg",
    ".gif",
    ".webp",
    ".ico",
    ".bmp",
    ".xbt",
    ".ttf",
    ".otf",
    ".woff",
    ".woff2",
    ".zip",
    ".gz",
    ".mp3",
    ".wav",
    ".ogg",
    ".mp4",
    ".db",
    ".so",
    ".dylib",
    ".pyc",
}

PRUNE_DIRS = {".git", "__pycache__", ".ruff_cache", ".pytest_cache", "node_modules"}

FAILURES: list[str] = []
LINES: list[str] = []


def emit(line: str = "") -> None:
    LINES.append(line)


def check(label: str, ok: bool, detail: str = "") -> None:
    emit(f"  {'PASS' if ok else 'FAIL'}  {label}")
    if not ok:
        FAILURES.append(label)
        for line in detail.splitlines():
            emit(f"          {line}")


# ---------------------------------------------------------------------------
# Version comparison
# ---------------------------------------------------------------------------
# Same discipline as check_kodi_floor.py, for the same reason: Kodi compares
# Debian-style versions, reimplementing all of that here would be a second
# unreviewed copy of CAddonVersion::CompareComponent, and a wrong comparison
# would silently pass a skin that resolves 2.x. So this handles plain dotted
# numerics exactly and REFUSES anything else rather than guessing.
SIMPLE = re.compile(r"\d+(\.\d+)*\Z")


def parse(version: str, where: str) -> tuple[int, ...]:
    if not SIMPLE.match(version):
        sys.exit(
            f"{where}: version {version!r} is not a plain dotted numeric.\n"
            "This checker deliberately refuses to guess at Debian epochs, "
            "revisions or '~' pre-release ordering. Port "
            "CAddonVersion::CompareComponent faithfully before allowing it."
        )
    return tuple(int(p) for p in version.split("."))


def cmp_version(a: tuple[int, ...], b: tuple[int, ...]) -> int:
    return (a > b) - (a < b)


# ---------------------------------------------------------------------------
# Inputs
# ---------------------------------------------------------------------------
def find_import(addon_xml: Path, dep_id: str = DEP_ID) -> tuple[dict[str, str] | None, int]:
    """The <import> attributes for dep_id, plus the line it is declared on.

    ElementTree exposes no source line, and a failure that cannot name
    file:line is a failure someone has to go hunting for, so the line number
    comes from a raw scan of the same text.
    """
    text = addon_xml.read_text(encoding="utf-8", errors="replace")
    root = ET.fromstring(text)
    found = None
    for imp in root.findall("./requires/import"):
        if imp.get("addon") == dep_id:
            found = dict(imp.attrib)
            break
    line = 0
    for i, raw in enumerate(text.splitlines(), 1):
        if dep_id in raw and "<import" in raw:
            line = i
            break
    return found, line


def scannable(base: Path) -> list[Path]:
    """Every file under base, pruned of caches, for path and content scanning."""
    out = []
    for dirpath, dirnames, filenames in os.walk(base):
        dirnames[:] = [d for d in dirnames if d not in PRUNE_DIRS]
        for fn in filenames:
            if fn in (".DS_Store", "Thumbs.db"):
                continue
            out.append(Path(dirpath) / fn)
    return sorted(out)


def hits_in(text: str) -> list[tuple[int, str, str]]:
    """(line, token, context) for every 2.x Skin Shortcuts reference in text."""
    hits = []
    for m in MENTION.finditer(text):
        lo = max(0, m.start() - WINDOW)
        hi = min(len(text), m.end() + WINDOW)
        window = text[lo:hi]
        tail = text[m.end() : m.end() + 24]

        found: list[tuple[int, str]] = []
        for v in DOTTED_2X.finditer(window):
            found.append((lo + v.start(), v.group()))
        a = ADJACENT_2.match(tail)
        if a:
            found.append((m.end(), a.group().strip()))
        for s in SS2.finditer(window):
            found.append((lo + s.start(), s.group()))

        for pos, token in found:
            line = text.count("\n", 0, pos) + 1
            context = text.splitlines()[line - 1].strip() if text else ""
            hits.append((line, token, context[:110]))
    # One report per (line, token). A mention can be inside two windows.
    seen = set()
    uniq = []
    for h in hits:
        key = (h[0], h[1])
        if key in seen:
            continue
        seen.add(key)
        uniq.append(h)
    return sorted(uniq)


def path_hit(rel: str) -> str | None:
    """A 2.x token in a PATH, which catches a vendored dir or a zip filename."""
    for _line, token, _ctx in hits_in(rel):
        return token
    return None


# ---------------------------------------------------------------------------
# Checks
# ---------------------------------------------------------------------------
def check_one_import(dep_id: str, attrs: dict[str, str], where: str, floor: str = FLOOR) -> None:
    """The pinning rules, applied identically to whichever provider is declared.

    THE FLOOR APPLIES TO BOTH PROVIDERS, and there is deliberately no way to
    exempt one. This used to take floor=None for the fork, because the fork was
    numbered on a line of its own starting at 1.0.0 and a 3.x floor would have
    rejected it. Owner directive 2026-07-30 renumbered the fork to carry the
    version of the build it was forked from, so it declares a genuine 3.x
    version and the exemption is not just unnecessary, it is a hole: an
    exemption argument is exactly the thing a future edit reaches for to make a
    failing build pass. The parameter keeps a default rather than a None branch
    so that "which provider is exempt" is not a question this file can answer.
    """
    version = (attrs.get("version") or "").strip()
    if not version:
        check(
            f"{dep_id} declares a version",
            False,
            f"{where}: the import carries no version attribute at all, so nothing pins it.",
        )
    else:
        ok = cmp_version(parse(version, where), parse(floor, where)) >= 0
        check(
            f"{dep_id} floor is at least {floor} (declared {version})",
            ok,
            f"{where}: version {version} is below {floor}. Estuary 8 is Skin "
            "Shortcuts 3.x ONLY; the legacy line is Estuary 7's and must never "
            "be resolvable here.",
        )

    minversion = (attrs.get("minversion") or "").strip()
    check(
        f"{dep_id} import carries NO minversion",
        not minversion,
        f'{where}: minversion="{minversion}" is present.\n'
        "Kodi's DependencyInfo constructor is "
        "versionMin(versionMin.empty() ? version : versionMin), so with no "
        "minversion the declared version IS the hard minimum. Supplying one "
        "turns version into an upper bound and re-admits the legacy line "
        "silently. Delete the attribute; do not 'fix' it by raising it.",
    )

    optional = (attrs.get("optional") or "false").strip().lower() in ("true", "1")
    check(
        f"{dep_id} import is NOT optional",
        not optional,
        f'{where}: optional="true" is present. Kodi skips optional '
        "dependencies entirely, so the floor stops being enforced at all.",
    )


def check_declaration(addon_xml: Path) -> None:
    """A shortcuts provider must be declared and pinned, and it must be OURS.

    FORK_ID is ours, a fork of the 3.x line carried under its own add-on id, and
    it is what the skin ships. It is floored at 3.x, carries no minversion and is
    never optional: see check_one_import.

    DEP_ID, the external add-on, is PROHIBITED as a declared dependency, and that
    is an assertion of its own rather than a side effect of the floor. Until
    2026-07-31 either id satisfied this function, so re-adding
    <import addon="script.skinshortcuts" version="3.0.1"/> to the shipped skin
    tomorrow would have passed every check in this file: correctly pinned, above
    the floor, no minversion, not optional. Pinning is not the point. The point
    is that Kodi must never resolve this skin's menu system from the official
    library, where the id is someone else's to version. The floor checks still
    run on it when it is present, deliberately, so the failure report names every
    way the line is wrong at once instead of one per fix.

    Declaring NEITHER is still a failure. The skin's whole menu system is Skin
    Shortcuts; dropping the import does not make the dependency optional, it
    makes it unpinned, and an unpinned dependency is one a repository is free to
    resolve to the legacy line.
    """
    if not addon_xml.is_file():
        check("a shortcuts provider import is declared", False, f"{addon_xml} does not exist")
        return

    fork_attrs, fork_line = find_import(addon_xml, FORK_ID)
    dep_attrs, dep_line = find_import(addon_xml, DEP_ID)

    if fork_attrs is None and dep_attrs is None:
        check(
            "a shortcuts provider import is declared",
            False,
            f'{addon_xml}: neither <import addon="{FORK_ID}"/> nor '
            f'<import addon="{DEP_ID}"/> is in <requires>.\n'
            "One of them must be, and must be pinned.",
        )
        return

    dep_where = f"{addon_xml}:{dep_line}" if dep_line else str(addon_xml)
    check(
        f"{DEP_ID} is NOT declared as a dependency",
        dep_attrs is None,
        f'{dep_where}: <import addon="{DEP_ID}"/> is in <requires>.\n'
        f"Estuary 8 depends on {FORK_ID}, which is ours and ships beside the "
        "skin. The external add-on must not be declared even when it is pinned "
        "correctly and above the floor: Kodi would resolve it from the official "
        "library, at whatever version that library serves, and this skin's menu "
        "system would then be built by code no one here controls.\n"
        f"Replace the line with the {FORK_ID} import; do not add both.",
    )

    if fork_attrs is not None:
        where = f"{addon_xml}:{fork_line}" if fork_line else str(addon_xml)
        check(f"{FORK_ID} import is declared ({where})", True)
        check_one_import(FORK_ID, fork_attrs, where, floor=FLOOR)

    if dep_attrs is not None:
        # Still floored, still pin-checked, and the "is declared" line is kept
        # verbatim from before the prohibition existed so nothing this file used
        # to assert has been dropped. The prohibition above has already failed
        # the run; these keep the report complete rather than drip-feeding one
        # defect per attempt.
        check(f"{DEP_ID} import is declared ({dep_where})", True)
        check_one_import(DEP_ID, dep_attrs, dep_where, floor=FLOOR)


def check_shipped_tree(skin: Path) -> None:
    if not skin.is_dir():
        check("shipped skin tree is free of 2.x references", False, f"{skin} does not exist")
        return

    offenders: list[str] = []
    files = scannable(skin)
    for p in files:
        rel = p.relative_to(skin).as_posix()

        token = path_hit(rel)
        if token:
            offenders.append(f"{skin.name}/{rel}  PATH names {token}")

        if p.suffix.lower() in BINARY_SUFFIXES:
            continue
        try:
            text = p.read_text(encoding="utf-8", errors="replace")
        except OSError as exc:  # unreadable is a finding, not a pass
            offenders.append(f"{skin.name}/{rel}  could not be read: {exc}")
            continue
        for line, tok, context in hits_in(text):
            offenders.append(f"{skin.name}/{rel}:{line}  {tok}  | {context}")

    header = (
        "A Skin Shortcuts 2.x reference is in the shipped tree. Version "
        "strings, vendored directories, zip filenames and PROSE all count: "
        "a comment naming the legacy version is what sends the next agent to "
        "unpack it."
    )
    check(
        f"shipped skin tree is free of 2.x references ({len(files)} files)",
        not offenders,
        "\n".join([header, *offenders]),
    )


def check_no_vendored_2x(search_root: Path) -> None:
    stale: list[str] = []
    checked = 0
    for dirpath, dirnames, _filenames in os.walk(search_root):
        dirnames[:] = [d for d in dirnames if d not in PRUNE_DIRS]
        for d in list(dirnames):
            if not d.startswith(DEP_ID):
                continue
            xml = Path(dirpath) / d / "addon.xml"
            if not xml.is_file():
                continue
            checked += 1
            text = xml.read_text(encoding="utf-8", errors="replace")
            m = re.search(r'<addon\s+[^>]*?version="([^"]+)"', text, re.DOTALL)
            if not m:
                stale.append(f"{xml}: no version on the <addon> tag")
                continue
            version = m.group(1)
            if cmp_version(parse(version, str(xml)), parse(FLOOR, str(xml))) < 0:
                stale.append(f"{xml}: declares {version}, below {FLOOR}")
    header = (
        f"A legacy {DEP_ID} copy is staged under {search_root}. It is an "
        "EXTERNAL dependency: Kodi resolves it from the official library, "
        "and this tree must not carry, patch or stage a 2.x build of it."
    )
    check(
        f"no vendored {DEP_ID} below {FLOOR} ({checked} copy/copies found)",
        not stale,
        "\n".join([header, *stale]),
    )


def run(addon_xml: Path, skin: Path, search_root: Path) -> int:
    """Every check, against one set of inputs. Returns the count of failures."""
    before = len(FAILURES)

    emit("=" * 74)
    emit(f"Estuary 8 Skin Shortcuts floor: {DEP_ID} >= {FLOOR}, 2.x forbidden")
    emit(f"  {addon_xml}")
    emit("=" * 74)
    emit()

    check_declaration(addon_xml)
    check_shipped_tree(skin)
    check_no_vendored_2x(search_root)

    return len(FAILURES) - before


# ---------------------------------------------------------------------------
# Self-test
# ---------------------------------------------------------------------------
# A guard that has never been shown to fail is not a guard, it is a decoration.
# Each case is an independent, plausible way of re-admitting 2.x, and each must
# be rejected on its own. The accepted cases matter just as much: a checker that
# fails on everything is equally useless, and two of them are real lines lifted
# out of the shipped tree, so a future tightening that starts flagging ordinary
# markup fails here instead of on the owner's next build.
CLEAN_IMPORT = '<import addon="script.skinshortcuts" version="3.0.1"/>'
FORK_IMPORT = '<import addon="script.estuary8.shortcuts" version="3.0.1"/>'

# Real lines from the shipped tree. MEASURED not to be 2.x references.
REAL_NEAR_MISSES = (
    "<label>$ADDON[script.skinshortcuts 32044] 2</label>\n"
    '<button id="1476" property="widget.2" type="widget" '
    'title="$ADDON[script.skinshortcuts 32014]"/>\n'
    "Skin Shortcuts 3.0.1 has no custom= action-only picker.\n"
    "items.py:266-288 mutates the action alone, see manager.py:143-151.\n"
)

SELF_TEST_CASES: list[tuple[str, str, str, dict[str, str], bool]] = [
    (
        # The baseline is the FORK, because that is what the skin ships. It used
        # to be CLEAN_IMPORT, which stopped being a valid "unchanged" shape on
        # 2026-07-31 when declaring the external add-on became a failure in its
        # own right. This case exists to prove the guard does NOT flag ordinary
        # markup, so its import has to be one the guard accepts.
        "unchanged, including real near-miss lines from the shipped tree",
        FORK_IMPORT,
        REAL_NEAR_MISSES,
        {},
        True,
    ),
    (
        # Was accepted until 2026-07-31. Correctly pinned, above the floor, no
        # minversion, not optional: every pin check passes and it is STILL
        # rejected, because the id itself is the defect. This is the exact
        # "someone re-adds the external import tomorrow" case.
        "the external add-on declared alone at the 3.0.0 boundary",
        '<import addon="script.skinshortcuts" version="3.0.0"/>',
        "",
        {},
        False,
    ),
    (
        "the external add-on declared alone, correctly pinned at 3.0.1",
        CLEAN_IMPORT,
        "",
        {},
        False,
    ),
    (
        "import version lowered to 2.0.3",
        '<import addon="script.skinshortcuts" version="2.0.3"/>',
        "",
        {},
        False,
    ),
    (
        "import version lowered to 2.9.9, still 2.x",
        '<import addon="script.skinshortcuts" version="2.9.9"/>',
        "",
        {},
        False,
    ),
    (
        "minversion added, defeating the DependencyInfo ternary",
        '<import addon="script.skinshortcuts" minversion="2.0.3" version="3.0.1"/>',
        "",
        {},
        False,
    ),
    (
        "import dropped entirely, leaving the version unpinned",
        "",
        "",
        {},
        False,
    ),
    (
        "import marked optional, which Kodi skips",
        '<import addon="script.skinshortcuts" version="3.0.1" optional="true"/>',
        "",
        {},
        False,
    ),
    (
        "version attribute removed from the import",
        '<import addon="script.skinshortcuts"/>',
        "",
        {},
        False,
    ),
    # The fork, script.estuary8.shortcuts, satisfies the dependency assertion in
    # the external add-on's place. Every way of breaking the pin has to be caught
    # on the fork's import too, or moving to it would quietly buy back the exact
    # holes this guard was built to close.
    (
        "fork import alone, which is the shape the skin ships",
        FORK_IMPORT,
        "",
        {},
        True,
    ),
    (
        # Also accepted until 2026-07-31, and the more insidious of the two
        # shapes: the fork is right there and correct, so the run looks healthy,
        # while Kodi is still handed a second provider to resolve from the
        # official library.
        "both providers declared, both correctly pinned",
        f"{FORK_IMPORT}\n\t\t{CLEAN_IMPORT}",
        "",
        {},
        False,
    ),
    (
        "the external declared optional beside a clean fork, which is still a hit",
        f'{FORK_IMPORT}\n\t\t<import addon="script.skinshortcuts" version="3.0.1" optional="true"/>',
        "",
        {},
        False,
    ),
    (
        "the external declared unpinned beside a clean fork",
        f'{FORK_IMPORT}\n\t\t<import addon="script.skinshortcuts"/>',
        "",
        {},
        False,
    ),
    (
        "fork declared but the external one is 2.x, which still fails",
        f'{FORK_IMPORT}\n\t\t<import addon="script.skinshortcuts" version="2.0.3"/>',
        "",
        {},
        False,
    ),
    (
        "fork import with no version, leaving it unpinned",
        '<import addon="script.estuary8.shortcuts"/>',
        "",
        {},
        False,
    ),
    (
        # The case the floor exemption used to let through. Until 2026-07-30 the
        # fork was checked with floor=None, so ANY version satisfied it and this
        # exact line was accepted. It is the reason the exemption is gone.
        "fork import below the floor, which the old exemption accepted",
        '<import addon="script.estuary8.shortcuts" version="2.0.3"/>',
        "",
        {},
        False,
    ),
    (
        "fork import at exactly 3.0.0, the boundary, on the fork's own id",
        '<import addon="script.estuary8.shortcuts" version="3.0.0"/>',
        "",
        {},
        True,
    ),
    (
        "fork import carrying a minversion, the same ternary trap",
        '<import addon="script.estuary8.shortcuts" minversion="3.0.0" version="3.0.1"/>',
        "",
        {},
        False,
    ),
    (
        "fork import marked optional, which Kodi skips entirely",
        '<import addon="script.estuary8.shortcuts" version="3.0.1" optional="true"/>',
        "",
        {},
        False,
    ),
    (
        # This is the real shape of the one hit the guard found on the shipped
        # tree when it was first run: xml/script-skinshortcuts.xml:174.
        "2.x named in a shipped XML comment",
        FORK_IMPORT,
        (
            "<!-- Skin Shortcuts 3.0.1 has no custom= equivalent of 2.0.3's\n"
            "     action-only picker, so this cannot be narrowed from the skin. -->\n"
        ),
        {},
        False,
    ),
    (
        # A bare version number with no Skin Shortcuts context nearby is NOT a
        # Skin Shortcuts reference. The skin is full of unrelated version
        # numbers, and a checker that failed on all of them would be turned off
        # within a day. The scan therefore pairs a mention with a token, and
        # this case is what stops a future "just grep for 2.0.3" simplification.
        "an unrelated 2.x version number, with no Skin Shortcuts mention nearby",
        FORK_IMPORT,
        "<!-- weather.multi 2.0.3 is the add-on this row was measured against -->\n",
        {},
        True,
    ),
    (
        "2.x named in shipped prose without dots, 'Skin Shortcuts 2'",
        FORK_IMPORT,
        "Behaves the way Skin Shortcuts 2 did.\n",
        {},
        False,
    ),
    (
        # MEASURED to be MISSED by the pre-2026-07-30 lookahead. Ending the
        # sentence there is the most natural way to write it, so this was the
        # widest hole in the guard.
        "prose ending in it, 'Skin Shortcuts 2.'",
        FORK_IMPORT,
        "Restores the behaviour of Skin Shortcuts 2.\n",
        {},
        False,
    ),
    (
        # The same hole via the abbreviated spelling.
        "prose ending in it, abbreviated, 'skinshortcuts v2.'",
        FORK_IMPORT,
        "Matches skinshortcuts v2.\n",
        {},
        False,
    ),
    (
        # The other side of that lookahead, and the reason it stayed two
        # assertions rather than becoming a bare (?!\d): an ordinal must not
        # trip it, or ordinary prose starts failing the build.
        "an ordinal after the mention, 'skinshortcuts 2nd'",
        FORK_IMPORT,
        "This is the skinshortcuts 2nd generation layout, unrelated.\n",
        {},
        True,
    ),
    (
        "2.x import wrapped across two lines",
        '<import addon="script.skinshortcuts"\n\t\t        version="2.0.3"/>',
        "",
        {},
        False,
    ),
    (
        "vendored legacy directory inside the shipped tree",
        FORK_IMPORT,
        "",
        {"script.skinshortcuts-2.0.3/addon.xml": '<addon id="script.skinshortcuts"/>'},
        False,
    ),
    (
        "legacy zip filename inside the shipped tree",
        FORK_IMPORT,
        "",
        {"script.skinshortcuts-2.0.3.zip": "not really a zip"},
        False,
    ),
    (
        "staged legacy copy elsewhere in the repo",
        FORK_IMPORT,
        "",
        {"../script.skinshortcuts/addon.xml": '<addon id="script.skinshortcuts" version="2.0.3"/>'},
        False,
    ),
]


def self_test() -> int:
    global FAILURES, LINES
    bad = 0
    for name, imp, prose, extra, should_pass in SELF_TEST_CASES:
        with tempfile.TemporaryDirectory() as td:
            search_root = Path(td)
            skin = search_root / "skin.estuary8"
            skin.mkdir()
            body = f"\t\t{imp}\n" if imp else ""
            (skin / "addon.xml").write_text(
                '<?xml version="1.0" encoding="UTF-8"?>\n'
                '<addon id="skin.estuary8" version="0.1.0" name="Estuary 8" provider-name="t">\n'
                "\t<requires>\n"
                '\t\t<import addon="xbmc.python" version="3.0.2"/>\n'
                '\t\t<import addon="xbmc.gui" version="5.18.0"/>\n'
                f"{body}"
                "\t</requires>\n</addon>\n",
                encoding="utf-8",
            )
            (skin / "xml").mkdir()
            (skin / "xml" / "Home.xml").write_text(prose or "<window/>\n", encoding="utf-8")
            for rel, content in extra.items():
                p = (skin / rel).resolve()
                p.parent.mkdir(parents=True, exist_ok=True)
                p.write_text(content, encoding="utf-8")

            saved_f, FAILURES = FAILURES, []
            saved_l, LINES = LINES, []
            failures = run(skin / "addon.xml", skin, search_root)
            detail = LINES
            FAILURES, LINES = saved_f, saved_l

        passed = failures == 0
        ok = passed == should_pass
        bad += 0 if ok else 1
        want = "accepted" if should_pass else "REJECTED"
        got = "accepted" if passed else "rejected"
        print(f">>> self-test: {name}")
        print(f"    want {want}, got {got}: {'OK' if ok else 'BROKEN'}")
        if not ok:
            print("\n".join(f"    {line}" for line in detail))
        print()
    return bad


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument(
        "--quiet",
        action="store_true",
        help="print nothing unless a check fails; for use inside other gates",
    )
    ap.add_argument(
        "--self-test",
        action="store_true",
        help="prove the checker rejects every way of re-admitting Skin Shortcuts 2.x",
    )
    args = ap.parse_args()

    if args.self_test:
        bad = self_test()
        print("=" * 74)
        if bad:
            print(f"FAIL: the checker mis-judged {bad} self-test case(s)")
            return 1
        print(f"OK: all {len(SELF_TEST_CASES)} self-test cases judged correctly")
        return 0

    run(ADDON_XML, SKIN, REPO)

    emit()
    if FAILURES:
        emit(f"FAIL: {len(FAILURES)} check(s) failed")
        for f in FAILURES:
            emit(f"  - {f}")
        emit("")
        emit("Estuary 8 is Skin Shortcuts 3.x ONLY. Fix the SKIN, never the")
        emit("dependency: script.skinshortcuts is external and must not be")
        emit("patched, forked, vendored or version-bumped here.")
        print("\n".join(LINES))
        return 1

    if not args.quiet:
        emit(f"OK: {DEP_ID} is pinned at >= {FLOOR} and no 2.x reference exists.")
        print("\n".join(LINES))
    return 0


if __name__ == "__main__":
    sys.exit(main())
