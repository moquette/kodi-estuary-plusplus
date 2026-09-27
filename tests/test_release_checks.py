"""tools/check_unreleased_changes.py and tools/check_version_bump.py.

Both exist because the publish job in .github/workflows/tests.yml is idempotent
by tag: a fix committed without a version bump builds, tests green, publishes
nothing and goes red nowhere. The first WARNS (source moved at an already
released version, per add-on, per tag namespace); the second FAILS a push that
changed an add-on without bumping it. The pure decisions are tested directly;
the git plumbing is tested against a throwaway repository.
"""

from __future__ import annotations

import pathlib
import subprocess
import sys

import pytest
from conftest import ROOT

sys.path.insert(0, str(ROOT / "tools"))

import check_unreleased_changes as unreleased  # noqa: E402
import check_version_bump as bump  # noqa: E402

ADDON_XML = '<?xml version="1.0"?>\n<addon id="{id}" version="{v}" name="x">\n</addon>\n'


# --------------------------------------------------------------------------- #
# the tag namespace, the shared contract with the hub
# --------------------------------------------------------------------------- #
def test_release_tag_is_namespaced_per_addon():
    """Two add-ons share this repo and a repo has ONE releases/latest, so
    each add-on tags its own namespace. The hub's static_catalog.py matches
    exactly ``<id>-v<version>``: change both or neither."""
    assert unreleased.release_tag("skin.estuary.plusplus", "1.4.3") == (
        "skin.estuary.plusplus-v1.4.3"
    )
    assert unreleased.release_tag("service.tvos.pythonfix", "1.1.0") == (
        "service.tvos.pythonfix-v1.1.0"
    )
    assert unreleased.ADDONS == ("skin.estuary.plusplus", "service.tvos.pythonfix")


def test_every_addon_dir_in_the_repo_is_covered():
    """An add-on the checks do not know about ships with no gate at all."""
    dirs = {p.parent.name for p in ROOT.glob("*/addon.xml")}
    assert dirs == set(unreleased.ADDONS)


def test_read_version_finds_the_addon_tag_wherever_it_sits():
    assert unreleased.read_version(ADDON_XML.format(id="a", v="1.2.3")) == "1.2.3"
    multiline = '<addon\n  id="a"\n  version="2.0.0"\n  name="x">\n<x version="9"/>'
    assert unreleased.read_version(multiline) == "2.0.0"
    assert unreleased.read_version("<addons/>") is None


def test_the_real_addon_versions_are_readable():
    for addon in unreleased.ADDONS:
        assert unreleased.read_addon_version(addon)


# --------------------------------------------------------------------------- #
# unreleased-changes: the three states
# --------------------------------------------------------------------------- #
def test_unreleased_when_the_tag_does_not_exist():
    state, msg = unreleased.classify("skin.estuary.plusplus", "1.4.3", False, [])
    assert state == "unreleased"
    assert "skin.estuary.plusplus-v1.4.3" in msg


def test_clean_when_tagged_and_nothing_moved():
    state, _ = unreleased.classify("skin.estuary.plusplus", "1.4.3", True, [])
    assert state == "clean"


def test_dirty_when_tagged_and_source_moved():
    state, msg = unreleased.classify(
        "skin.estuary.plusplus", "1.4.3", True, ["skin.estuary.plusplus/xml/Home.xml"]
    )
    assert state == "dirty"
    assert "xml/Home.xml" in msg and "NO box" in msg


# --------------------------------------------------------------------------- #
# version-bump: the pure decision
# --------------------------------------------------------------------------- #
def test_unchanged_addon_needs_no_bump():
    assert bump.decide("a", [], "1.0.0", "1.0.0")[0]


def test_changed_addon_with_a_bump_passes():
    ok, msg = bump.decide("a", ["a/x"], "1.0.0", "1.0.1")
    assert ok and "1.0.0 -> 1.0.1" in msg


def test_changed_addon_without_a_bump_fails():
    ok, msg = bump.decide("a", ["a/x"], "1.0.0", "1.0.0")
    assert not ok and "still 1.0.0" in msg


def test_a_lower_version_is_not_a_bump():
    assert not bump.decide("a", ["a/x"], "1.4.2", "1.4.1")[0]
    assert bump.decide("a", ["a/x"], "1.9.0", "1.10.0")[0], "numeric, not text"


def test_new_addon_has_no_baseline_to_bump_from():
    assert bump.decide("a", ["a/addon.xml"], None, "1.0.0")[0]


def test_non_numeric_version_fails_rather_than_guessing():
    ok, msg = bump.decide("a", ["a/x"], "1.0.0", "1.0.0-rc1")
    assert not ok and "dotted numeric" in msg


# --------------------------------------------------------------------------- #
# the git plumbing, against a throwaway repository
# --------------------------------------------------------------------------- #
def _git(repo: pathlib.Path, *args: str) -> str:
    return subprocess.run(
        ["git", "-C", str(repo), *args], capture_output=True, text=True, check=True
    ).stdout.strip()


@pytest.fixture
def repo(tmp_path):
    """One commit per add-on at 1.0.0, tagged in its namespace."""
    r = tmp_path / "r"
    r.mkdir()
    _git(r, "init", "-q", "-b", "main")
    _git(r, "config", "user.email", "t@example.invalid")
    _git(r, "config", "user.name", "t")
    for addon in unreleased.ADDONS:
        (r / addon).mkdir()
        (r / addon / "addon.xml").write_text(ADDON_XML.format(id=addon, v="1.0.0"))
        (r / addon / "payload").write_text("one\n")
    _git(r, "add", ".")
    _git(r, "commit", "-q", "-m", "initial")
    for addon in unreleased.ADDONS:
        _git(r, "tag", unreleased.release_tag(addon, "1.0.0"))
    return r


def test_unreleased_check_reads_the_repo(repo):
    skin = unreleased.ADDONS[0]
    assert unreleased.check_addon(skin, str(repo))[0] == "clean"
    (repo / skin / "payload").write_text("two\n")
    _git(repo, "commit", "-q", "-am", "edit at a released version")
    state, msg = unreleased.check_addon(skin, str(repo))
    assert state == "dirty" and f"{skin}/payload" in msg
    # the other add-on is untouched by the skin's edit
    assert unreleased.check_addon(unreleased.ADDONS[1], str(repo))[0] == "clean"
    (repo / skin / "addon.xml").write_text(ADDON_XML.format(id=skin, v="1.0.1"))
    _git(repo, "commit", "-q", "-am", "bump")
    assert unreleased.check_addon(skin, str(repo))[0] == "unreleased"


def test_version_bump_gate_reads_the_repo(repo):
    base = _git(repo, "rev-parse", "HEAD")
    skin, svc = unreleased.ADDONS
    ok, lines = bump.check(base, cwd=str(repo))
    assert ok and all(line.startswith("OK") for line in lines)
    (repo / skin / "payload").write_text("two\n")
    _git(repo, "commit", "-q", "-am", "edit without a bump")
    ok, lines = bump.check(base, cwd=str(repo))
    assert not ok
    assert any(line.startswith("FAIL") and skin in line for line in lines)
    assert any(line.startswith("OK") and svc in line for line in lines)
    (repo / skin / "addon.xml").write_text(ADDON_XML.format(id=skin, v="1.0.1"))
    _git(repo, "commit", "-q", "-am", "bump")
    ok, lines = bump.check(base, cwd=str(repo))
    assert ok and any("1.0.0 -> 1.0.1" in line for line in lines)


def test_version_bump_gate_skips_without_a_base(repo):
    for base in ("", bump.ZERO_SHA, "no-such-ref"):
        ok, lines = bump.check(base, cwd=str(repo))
        assert ok and "skipped" in lines[0]


def test_workflow_wires_the_gates_and_the_publish_job():
    """Source-level pins on tests.yml so a refactor cannot silently drop
    the publish job, the tag namespace or the hub dispatch."""
    text = (ROOT / ".github" / "workflows" / "tests.yml").read_text()
    assert "check_unreleased_changes.py" in text
    assert "check_version_bump.py" in text
    assert "publish:" in text and "needs: tests" in text
    assert 'TAG="${ADDON}-v${VERSION}"' in text
    assert "gh release create" in text
    assert "T7B_DISPATCH_TOKEN" in text
    assert "event_type=ezmpp-release" in text, "the hub's repository_dispatch type"
    assert "fetch-depth: 0" in text, "the checks diff against tags and history"
    publish = text.split("\n  publish:\n")[1]
    commands = [
        line for line in publish.splitlines() if not line.lstrip().startswith("#")
    ]
    builds = [line for line in commands if "build_skin.py" in line]
    assert builds == ['            python3 tools/build_skin.py "$ADDON"'], (
        "the publish job builds PLAIN: --check builds into temp dirs and "
        "leaves nothing in dist/"
    )
