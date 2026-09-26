#!/usr/bin/env python3
"""The version-bump gate: a push that changes an add-on must bump its version.

For each add-on in this repo, compares HEAD against a base ref. If files under
<id>/ changed but the version in <id>/addon.xml did not increase, the push
fails. Kodi upgrades by version number only: a same-version byte change is
invisible to every box, and since 2026-09-26 the publish job is idempotent by
tag, so it would also publish nothing and go red nowhere.

    tools/check_version_bump.py                     base = origin/main
    tools/check_version_bump.py --base <sha|ref>    CI: github.event.before

On a push to main, origin/main already IS the pushed HEAD, so CI passes the
range start instead (the hub's _tools/check_versions.py does the same with
CHECK_VERSIONS_BASE_REF). A base that does not exist (fresh clone, first push,
the all-zero sha of a branch creation) skips with a notice: an unverifiable
gate is reported as skipped, never as green.

Exit codes: 0 ok or skipped, 1 a change lacks a bump, 2 the check could not run.
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys

from check_unreleased_changes import ADDONS, read_version, repo_root

ZERO_SHA = "0" * 40


def git(*args: str, cwd: str | None = None) -> tuple[int, str]:
    proc = subprocess.run(
        ["git", *args], cwd=cwd or repo_root(), capture_output=True, text=True
    )
    return proc.returncode, proc.stdout.strip()


def parse_version(version: str) -> tuple[int, ...]:
    """Dotted numeric only. Anything else is a ValueError, and the gate fails
    rather than guessing how Kodi would compare it."""
    try:
        return tuple(int(part) for part in version.split("."))
    except ValueError as exc:
        raise ValueError(f"{version!r} is not a dotted numeric version") from exc


def base_exists(base: str, cwd: str | None = None) -> bool:
    if not base or base == ZERO_SHA:
        return False
    code, _ = git("rev-parse", "--verify", "--quiet", f"{base}^{{commit}}", cwd=cwd)
    return code == 0


def changed_files(base: str, addon: str, cwd: str | None = None) -> list[str]:
    code, out = git("diff", "--name-only", base, "HEAD", "--", addon, cwd=cwd)
    if code != 0:
        raise RuntimeError(f"git diff {base}..HEAD -- {addon} failed")
    return [line for line in out.splitlines() if line.strip()]


def base_version(base: str, addon: str, cwd: str | None = None) -> str | None:
    """The add-on's version at the base ref, or None when it did not exist
    there (a new add-on needs no bump)."""
    code, out = git("show", f"{base}:{addon}/addon.xml", cwd=cwd)
    if code != 0:
        return None
    return read_version(out)


def decide(addon: str, changed: list[str], old: str | None, new: str | None):
    """Pure decision: (ok, message)."""
    if not changed:
        return True, f"{addon}: unchanged"
    if old is None:
        return True, f"{addon}: new add-on, no baseline to bump from"
    if not new:
        return False, f"{addon}: {addon}/addon.xml has no version"
    try:
        bumped = parse_version(new) > parse_version(old)
    except ValueError as exc:
        return False, f"{addon}: {exc}"
    if bumped:
        return True, f"{addon}: {old} -> {new} (bumped, {len(changed)} file(s) changed)"
    return (
        False,
        f"{addon}: {len(changed)} file(s) changed but the version is still {old} "
        f"(bump {addon}/addon.xml; Kodi upgrades by version number only)",
    )


def check(base: str, addons=ADDONS, cwd: str | None = None):
    """(ok, lines) across all add-ons. ok is True when skipped."""
    root = cwd or repo_root()
    if not base_exists(base, root):
        return True, [f"no base {base!r} to compare against: skipped"]
    ok, lines = True, []
    for addon in addons:
        changed = changed_files(base, addon, root)
        old = base_version(base, addon, root)
        with open(os.path.join(root, addon, "addon.xml"), encoding="utf-8") as fh:
            new = read_version(fh.read())
        good, message = decide(addon, changed, old, new)
        ok = ok and good
        lines.append(("OK" if good else "FAIL") + ": " + message)
    return ok, lines


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--base", default="origin/main", help="ref to diff against")
    args = parser.parse_args(argv)
    try:
        ok, lines = check(args.base)
    except RuntimeError as exc:
        print(f"version-bump gate: FATAL: {exc}", file=sys.stderr)
        return 2
    print(f"version-bump gate (against {args.base}):")
    for line in lines:
        print(f"  {line}")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
