#!/usr/bin/env python3
"""Assert that Estuary 8 cannot install or run on Kodi 21.

Estuary 8 targets Kodi 22. The guard that enforces that is two lines of
`addon.xml`, and it works, but it works for a reason that is not visible in the
file. This replays Kodi's own dependency predicate so the guard has a test
instead of a belief.

    python3 estuary8/tools/check_kodi_floor.py
    python3 estuary8/tools/check_kodi_floor.py --bundle /Applications/Kodi.app

Why a bare `version=` is already a hard minimum
-----------------------------------------------
`addon.xml` says only `<import addon="xbmc.gui" version="5.18.0"/>`, with no
`minversion`. That reads like "targets 5.18.0", not "refuses anything older",
and Kodi's own comparison looks like it agrees:

    // AddonInfo.cpp
    bool CAddonInfo::MeetsVersion(const CAddonVersion& versionMin,
                                  const CAddonVersion& version) const
    {
      return !(versionMin > m_version || version < m_minversion);
    }

`m_version` is the version the running Kodi's `xbmc.gui` declares (5.17.0 on
Kodi 21) and `m_minversion` is its `<backwards-compatibility abi="...">`
(5.17.0 on both 21 and 22). Read literally with versionMin unset, neither term
fires and Kodi 21 would be compatible.

It is not, and the reason is the DependencyInfo constructor:

    // AddonInfo.h
    DependencyInfo(std::string id, const CAddonVersion& versionMin,
                   const CAddonVersion& version, bool optional)
      : id(std::move(id)),
        versionMin(versionMin.empty() ? version : versionMin),   // <-- here
        version(version), optional(optional) {}

An absent `minversion` parses to CAddonVersion("") which is "0.0.0", which is
`empty()`, so versionMin silently becomes `version`. That single ternary is the
whole guard. Nothing in `addon.xml` records it, which is what this file is for.

Verified on hardware, not inferred. Probe add-ons declaring exactly one magic
import were offered to a real Kodi 21.3 in an isolated profile:

    probe.gui517    <import addon="xbmc.gui" version="5.17.0"/>       enabled
    probe.gui518    <import addon="xbmc.gui" version="5.18.0"/>       REFUSED
    probe.py302     <import addon="xbmc.python" version="3.0.2"/>     REFUSED
    probe.none      no magic imports                                  enabled

See notes/kodi22-hardfail.md for the run, the log lines and the screenshots.

What this file does NOT do
--------------------------
It does not add a second guard. Kodi already refuses at three independent
points and says so on screen every time. A skin-side startup check would be
strictly weaker: it could only run after Kodi had already decided to load the
skin, which on Kodi 21 never happens.
"""

from __future__ import annotations

import argparse
import re
import sys
import tempfile
import xml.etree.ElementTree as ET
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ADDON_XML = ROOT / "skin.estuary8" / "addon.xml"

# The two Kodi bundles this was measured against, so the check still means
# something on a machine that has neither installed. Values read from
# <bundle>/Contents/Resources/Kodi/addons/<id>/addon.xml on 2026-07-28.
#
#   name: (must_load, {addon_id: (version, backwards_compatibility_abi)})
#
# must_load is the expected verdict. Kodi 21 MUST fail; Kodi 22 MUST pass. A
# machine-local bundle, when present, overrides these numbers, so this table
# going stale cannot mask a real change.
REFERENCE = {
    "Kodi 21.3 (Omega)": (
        False,
        {"xbmc.gui": ("5.17.0", "5.17.0"), "xbmc.python": ("3.0.1", "3.0.0")},
    ),
    "Kodi 22.0-BETA1 (Piers)": (
        True,
        {"xbmc.gui": ("5.18.0", "5.17.0"), "xbmc.python": ("3.0.2", "3.0.0")},
    ),
}

# Bundles to look for on this machine, so each leg above can be MEASURED rather
# than replayed from the table. Both legs matter: the Kodi 22 bundle proves the
# skin still loads, and the Kodi 21 bundle is the NEGATIVE rig that proves the
# floor still refuses. A leg with no bundle prints "(recorded)" and is only as
# good as the numbers above it.
#
# The Kodi 21 entries are not optional garnish. Until 2026-08-01 this list held
# only the two 22 paths, so the Kodi 21 leg silently fell back to "(recorded)"
# even on a machine with a real 21.3 installed, and the table it fell back to
# was the very thing the bundle was supposed to check. Order is irrelevant: the
# match is by xbmc.gui version, not by position.
LOCAL_BUNDLES = (
    Path("/Applications/Kodi.app"),  # 22.0.beta1 here; ~/Applications/Kodi22.app symlinks to it
    Path("~/Applications/Kodi22.app"),
    Path("/Applications/Kodi21.app"),  # 21.3, the negative rig
    Path("~/Applications/Kodi21.app"),
)

# Kodi only enforces dependency versions for ids in these namespaces:
#   CAddonMgr::IsCompatible -> StringUtils::StartsWith(id, "xbmc.") || "kodi."
# Everything else is left to the repository, so only these can gate a version.
MAGIC_PREFIXES = ("xbmc.", "kodi.")

FAILURES: list[str] = []


def check(label: str, ok: bool, detail: str = "") -> None:
    print(f"  {'PASS' if ok else 'FAIL'}  {label}")
    if not ok:
        FAILURES.append(label)
        for line in detail.splitlines():
            print(f"          {line}")


# ---------------------------------------------------------------------------
# Version comparison
# ---------------------------------------------------------------------------
# Kodi uses Debian-style versions: epoch, upstream, revision, with each dotted
# component compared numerically rather than lexically, and '~' sorting before
# everything including the empty string.
#
# Implementing all of that would be a second, unreviewed copy of
# CAddonVersion::CompareComponent. Every version this check handles is a plain
# dotted numeric, so it compares those exactly and REFUSES anything else rather
# than guessing. A wrong comparison here would silently pass a skin that Kodi
# would reject, which is the one outcome this file exists to prevent.
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
    # 1.0 < 1.0.0 in Debian ordering, and plain tuple comparison already gives
    # that, because the shorter tuple is a prefix and sorts first.
    return (a > b) - (a < b)


def meets_version(
    dep_version_min: str, dep_version: str, provided: str, provided_abi: str, where: str
) -> bool:
    """CAddonInfo::MeetsVersion, including the DependencyInfo minversion fallback."""
    # DependencyInfo: versionMin(versionMin.empty() ? version : versionMin)
    # CAddonVersion("") is "0.0.0" and CAddonVersion::empty() is true for it.
    if not dep_version_min or dep_version_min == "0.0.0":
        dep_version_min = dep_version
    vmin = parse(dep_version_min, where)
    ver = parse(dep_version, where)
    m_version = parse(provided, where)
    m_minversion = parse(provided_abi, where)
    # return !(versionMin > m_version || version < m_minversion);
    return not (cmp_version(vmin, m_version) > 0 or cmp_version(ver, m_minversion) < 0)


# ---------------------------------------------------------------------------
# Inputs
# ---------------------------------------------------------------------------
def skin_dependencies(addon_xml: Path | None = None) -> list[tuple[str, str, str, bool]]:
    """(id, minversion, version, optional) for every <import> in the skin."""
    root = ET.parse(addon_xml or ADDON_XML).getroot()
    deps = []
    for imp in root.findall("./requires/import"):
        addon = imp.get("addon")
        if not addon:
            continue
        optional = (imp.get("optional") or "false").strip().lower() in ("true", "1")
        deps.append((addon, imp.get("minversion") or "", imp.get("version") or "", optional))
    return deps


def read_bundle(bundle: Path) -> dict[str, tuple[str, str]]:
    """Read the xbmc.* add-ons a Kodi application bundle actually ships."""
    base = bundle / "Contents" / "Resources" / "Kodi" / "addons"
    if not base.is_dir():
        base = bundle / "addons"
    provided = {}
    for wanted in ("xbmc.gui", "xbmc.python"):
        p = base / wanted / "addon.xml"
        if not p.is_file():
            continue
        r = ET.parse(p).getroot()
        bc = r.find("backwards-compatibility")
        # No <backwards-compatibility> means m_minversion keeps its default,
        # CAddonVersion() == "0.0.0", which never blocks anything.
        provided[wanted] = (
            r.get("version") or "0.0.0",
            (bc.get("abi") if bc is not None else "0.0.0"),
        )
    return provided


def bundle_label(bundle: Path) -> str:
    plist = bundle / "Contents" / "Info.plist"
    if plist.is_file():
        m = re.search(
            r"<key>CFBundleShortVersionString</key>\s*<string>([^<]+)</string>",
            plist.read_text(encoding="utf-8", errors="replace"),
        )
        if m:
            return f"{bundle.name} ({m.group(1)})"
    return bundle.name


# ---------------------------------------------------------------------------
# Checks
# ---------------------------------------------------------------------------
def verdict(deps, provided: dict[str, tuple[str, str]], where: str) -> tuple[bool, str]:
    """Replay CAddonMgr::IsCompatible. Returns (compatible, reason)."""
    for addon, vmin, ver, optional in deps:
        if optional or not addon.startswith(MAGIC_PREFIXES):
            continue
        if addon not in provided:
            # !haveDependency -> return false
            return False, f"{addon} is not provided at all"
        got, abi = provided[addon]
        if not meets_version(vmin, ver, got, abi, where):
            return False, (
                f"{addon}: skin wants {ver}, this Kodi provides {got} "
                f"(abi floor {abi}) -> MeetsVersion false"
            )
    return True, "every magic dependency satisfied"


def run(addon_xml: Path, extra_bundles: list[str]) -> int:
    """Run every check against one addon.xml. Returns the count of failures."""
    before = len(FAILURES)

    print("=" * 74)
    print("Estuary 8 Kodi version floor")
    print(f"  {addon_xml}")
    print("=" * 74)

    deps = skin_dependencies(addon_xml)
    magic = {
        a: (vmin, ver) for a, vmin, ver, opt in deps if a.startswith(MAGIC_PREFIXES) and not opt
    }

    print("\ndeclared magic dependencies (the only ones Kodi version-gates)")
    for addon, (vmin, ver) in sorted(magic.items()):
        shown = f"minversion={vmin} version={ver}" if vmin else f"version={ver}"
        print(f"    {addon:<14} {shown}")

    print("\nthe floor is declared")
    # xbmc.gui 5.18.0 is the deliberate Kodi 22 floor. xbmc.python 3.0.2 comes
    # from Skin Shortcuts 3.0.1 and independently excludes 21, which is why
    # Kodi's install error names xbmc.python rather than xbmc.gui:
    # CheckDependencies returns on the first dependency that fails, and
    # xbmc.python is declared first.
    for addon, floor in (("xbmc.gui", "5.18.0"), ("xbmc.python", "3.0.2")):
        got = magic.get(addon)
        if got is None:
            check(f"{addon} is imported", False, f"{addon} is missing from <requires>")
            continue
        vmin, ver = got
        effective = vmin or ver
        ok = effective and cmp_version(parse(effective, addon), parse(floor, addon)) >= 0
        check(
            f"{addon} floor is at least {floor}",
            bool(ok),
            f"effective minimum is {effective or '(none)'}, which is below {floor}. "
            "Lowering this re-admits Kodi 21.",
        )

    print("\nreplay of CAddonMgr::IsCompatible per Kodi version")
    seen = []
    for bundle in extra_bundles:
        p = Path(bundle).expanduser()
        provided = read_bundle(p)
        if not provided:
            check(f"{p}", False, "no xbmc.gui/xbmc.python found inside this bundle")
            continue
        seen.append((bundle_label(p), None, provided))

    for name, (must_load, provided) in REFERENCE.items():
        # A bundle on this machine wins over the recorded numbers.
        local = None
        for cand in LOCAL_BUNDLES:
            cand = cand.expanduser()
            if not cand.is_dir():
                continue
            got = read_bundle(cand)
            if got and got.get("xbmc.gui", ("",))[0] == provided["xbmc.gui"][0]:
                local = (cand, got)
                break
        source = "measured" if local else "recorded"
        use = local[1] if local else provided
        compatible, reason = verdict(deps, use, name)
        label = f"{name}: {'loads' if compatible else 'refused'} ({source})"
        check(
            label
            if compatible == must_load
            else f"{label}  EXPECTED {'loads' if must_load else 'refused'}",
            compatible == must_load,
            reason,
        )
        if compatible != must_load:
            continue
        print(f"          {reason}")

    for label, _, provided in seen:
        compatible, reason = verdict(deps, provided, label)
        print(f"  INFO  {label}: {'loads' if compatible else 'refused'}")
        print(f"          {reason}")

    return len(FAILURES) - before


# ---------------------------------------------------------------------------
# Self-test
# ---------------------------------------------------------------------------
# A guard that has never been shown to fail is not a guard, it is a decoration.
# Each case below is a plausible future edit that would quietly re-admit Kodi
# 21, and each must be rejected. The "unchanged" case must be accepted, because
# a checker that fails on everything is equally useless.
SELF_TEST_CASES = [
    (
        "unchanged",
        [("xbmc.python", 'version="3.0.2"'), ("xbmc.gui", 'version="5.18.0"')],
        True,
    ),
    (
        "xbmc.gui lowered to Estuary 7's 5.17.0 floor",
        [("xbmc.python", 'version="3.0.2"'), ("xbmc.gui", 'version="5.17.0"')],
        False,
    ),
    (
        "xbmc.python lowered to the 3.0.1 Kodi 21 ships",
        [("xbmc.python", 'version="3.0.1"'), ("xbmc.gui", 'version="5.18.0"')],
        False,
    ),
    (
        "minversion added BELOW version, defeating the ternary fallback",
        [
            ("xbmc.python", 'minversion="3.0.0" version="3.0.2"'),
            ("xbmc.gui", 'minversion="5.17.0" version="5.18.0"'),
        ],
        False,
    ),
    (
        "xbmc.gui import dropped entirely",
        [("xbmc.python", 'version="3.0.2"')],
        False,
    ),
    (
        "xbmc.gui marked optional, which Kodi skips",
        [
            ("xbmc.python", 'version="3.0.2"'),
            ("xbmc.gui", 'version="5.18.0" optional="true"'),
        ],
        False,
    ),
]


def self_test() -> int:
    global FAILURES
    bad = 0
    with tempfile.TemporaryDirectory() as td:
        for name, imports, should_pass in SELF_TEST_CASES:
            body = "\n".join(f'\t\t<import addon="{a}" {attrs}/>' for a, attrs in imports)
            xml = (
                '<?xml version="1.0" encoding="UTF-8"?>\n'
                '<addon id="skin.estuary8" version="0.1.0" name="Estuary 8" provider-name="t">\n'
                f"\t<requires>\n{body}\n\t</requires>\n</addon>\n"
            )
            p = Path(td) / "addon.xml"
            p.write_text(xml, encoding="utf-8")

            saved, FAILURES = FAILURES, []
            failures = run(p, [])
            FAILURES = saved

            passed = failures == 0
            ok = passed == should_pass
            bad += 0 if ok else 1
            want = "accepted" if should_pass else "REJECTED"
            got = "accepted" if passed else "rejected"
            print(
                f"\n>>> self-test: {name}\n    want {want}, got {got}: {'OK' if ok else 'BROKEN'}\n"
            )
    return bad


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument(
        "--bundle",
        action="append",
        default=[],
        help="extra Kodi .app bundle to check; repeatable",
    )
    ap.add_argument(
        "--self-test",
        action="store_true",
        help="prove the checker rejects the edits that would re-admit Kodi 21",
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

    run(ADDON_XML, args.bundle)

    print()
    if FAILURES:
        print(f"FAIL: {len(FAILURES)} check(s) failed")
        for f in FAILURES:
            print(f"  - {f}")
        return 1
    print("OK: Kodi 21 cannot install or run this skin; Kodi 22 can.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
