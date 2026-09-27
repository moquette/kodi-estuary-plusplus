#!/usr/bin/env python3
"""Catch source that changed at an ALREADY-RELEASED version, per add-on.

Ported from ezmpp/tools/check_unreleased_changes.py on 2026-09-26, the day this
repo's CI started publishing GitHub releases. The hole it closes: the publish
job is idempotent by tag. If the tag for an add-on's current version already
exists it prints "nothing to publish" and exits 0. So a real fix committed
without bumping addon.xml builds fine, passes every test, publishes nothing,
reaches zero boxes, and NOTHING GOES RED ANYWHERE.

Two add-ons share this repo, so each has its own tag namespace:

    skin.estuary.plusplus-v<version>
    service.tvos.pythonfix-v<version>

A repository has one releases/latest, which is why the hub resolves each of
these by listing the releases and matching the namespace rather than asking
for "latest".

What this does NOT do is force a bump on every commit. Batching several commits
into one release is normal, and a gate that fought it would just get bypassed,
so the default is a LOUD WARNING, not a failure. tools/check_version_bump.py is
the hard gate, and it asks a narrower question: did THIS push change an add-on
without bumping it.

    tools/check_unreleased_changes.py            warn, always exit 0
    tools/check_unreleased_changes.py --strict   exit 1 if there are unreleased changes

Three states per add-on:

  tag missing   the current version is unreleased, the next push publishes it. OK.
  tag, no diff  genuine idempotent no-op, nothing has changed since release. OK.
  tag + diff    source moved at a released version. Bump before this can ship.

Exit codes: 0 ok (or warning), 1 unreleased changes under --strict, 2 the check
could not run (which is never treated as a pass).
"""

from __future__ import annotations

import argparse
import os
import re
import subprocess
import sys

ADDONS = ("skin.estuary.plusplus", "service.tvos.pythonfix")


def repo_root() -> str:
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def git(*args: str, cwd: str | None = None) -> tuple[int, str]:
    """Run git, returning (exit_code, stdout). Never raises on a non-zero exit."""
    proc = subprocess.run(
        ["git", *args],
        cwd=cwd or repo_root(),
        capture_output=True,
        text=True,
    )
    return proc.returncode, proc.stdout.strip()


def release_tag(addon: str, version: str) -> str:
    """The per-add-on tag namespace. The hub's static_catalog.py matches
    exactly this shape (``<id>-v<version>``); change both or neither."""
    return f"{addon}-v{version}"


def read_version(text: str) -> str | None:
    """The version attribute of the <addon> element, wherever the tag sits."""
    match = re.search(r"<addon\s[^>]*?version=\"([^\"]+)\"", text, re.DOTALL)
    return match.group(1) if match else None


def read_addon_version(addon: str, root: str | None = None) -> str | None:
    path = os.path.join(root or repo_root(), addon, "addon.xml")
    with open(path, encoding="utf-8") as fh:
        return read_version(fh.read())


def tag_exists(tag: str, cwd: str | None = None) -> bool:
    code, out = git("tag", "--list", tag, cwd=cwd)
    return code == 0 and out != ""


def changed_since(tag: str, addon: str, cwd: str | None = None) -> list[str] | None:
    """Files under the add-on dir that differ between `tag` and HEAD, or None
    when git cannot diff (unreachable tag, shallow clone)."""
    code, out = git("diff", "--name-only", tag, "HEAD", "--", addon, cwd=cwd)
    if code != 0:
        return None
    return [line for line in out.splitlines() if line.strip()]


def classify(addon: str, version: str, has_tag: bool, changed: list[str]):
    """Pure decision, so the states are testable without a git repo.

    Returns (state, message) where state is one of: unreleased, clean, dirty.
    """
    tag = release_tag(addon, version)
    if not has_tag:
        return (
            "unreleased",
            f"{addon} {version} has no {tag} tag yet: the next push to main "
            f"publishes it.",
        )
    if not changed:
        return (
            "clean",
            f"{addon} {version} is released and source is unchanged since {tag}.",
        )
    listed = "\n".join(f"      {f}" for f in changed[:20])
    more = f"\n      ... and {len(changed) - 20} more" if len(changed) > 20 else ""
    return (
        "dirty",
        f"{len(changed)} file(s) under {addon}/ changed since {tag}, but the\n"
        f"    version is still {version}. Kodi upgrades by version number only, so\n"
        f"    these changes reach NO box until addon.xml is bumped, and the publish\n"
        f"    job will report success while doing nothing.\n{listed}{more}",
    )


def check_addon(addon: str, cwd: str | None = None) -> tuple[str, str]:
    """(state, message) for one add-on, from the real git state. State
    ``fatal`` means the check could not run."""
    version = read_addon_version(addon, cwd)
    if not version:
        return "fatal", f"no version found in {addon}/addon.xml"
    tag = release_tag(addon, version)
    has_tag = tag_exists(tag, cwd)
    changed = changed_since(tag, addon, cwd) if has_tag else []
    if changed is None:
        # The tag exists but is not reachable, usually a shallow clone. Refuse
        # to call that a pass: an unverifiable gate is not a green one.
        return (
            "fatal",
            f"cannot diff against {tag}. Fetch tags and full history "
            f"(actions/checkout needs fetch-depth: 0).",
        )
    return classify(addon, version, has_tag, changed)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--strict",
        action="store_true",
        help="exit 1 on unreleased changes instead of warning",
    )
    parser.add_argument(
        "addons",
        nargs="*",
        default=list(ADDONS),
        help="add-on ids to check (default: all of them)",
    )
    args = parser.parse_args(argv)

    rc = 0
    for addon in args.addons:
        state, message = check_addon(addon)
        if state == "fatal":
            print(f"check-unreleased: FATAL: {message}", file=sys.stderr)
            return 2
        if state == "dirty":
            label = "FAIL" if args.strict else "WARNING"
            print(f"check-unreleased: {label}: {message}")
            if args.strict:
                rc = 1
            continue
        print(f"check-unreleased: OK: {message}")
    return rc


if __name__ == "__main__":
    sys.exit(main())
