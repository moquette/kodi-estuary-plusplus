# Releasing from this repo

## 1. What a release is

A release is a version bump pushed to `main`. Nothing else is required: CI
(`.github/workflows/tests.yml`) builds the add-on with `tools/build_skin.py`,
publishes a GitHub release carrying the zip, verifies the published asset's
sha256 against the build, and dispatches the hub. The hub
(`tony7bones/tony7bones.github.io`, local checkout `../repo`) resolves the
newest release of each add-on it serves this way at build time and takes
`addon.xml` and art out of the zip, so no copy of the skin is committed there.
Releasing here IS publishing there. Owner rule: THERE MUST BE NO MIRROR
VERSION TO BE WRONG.

## 2. Tag namespaces

Two add-ons share this repo and a repository has exactly one
`releases/latest`, so each add-on tags its own namespace:

- `skin.estuary.pov-v<version>`
- `service.tvos.pythonfix-v<version>`

The asset is `<id>-<version>.zip`. The hub's `_tools/static_catalog.py`
matches exactly this shape (its `_RELEASE_ASSET_RE`, the `{id}-v{version}` tag
segment) and lists the repo's releases to find the newest in a namespace.
Change the shape in both places or in neither. `tools/check_unreleased_changes.py`
owns the shape on this side (`release_tag`).

## 3. The two checks in CI

- `tools/check_unreleased_changes.py` WARNS when files under `<id>/` moved
  since that add-on's last release tag while the version stayed put. The
  publish job is idempotent by tag, so that state publishes nothing and goes
  red nowhere; the warning is what makes it visible. `../bin/check-all` prints
  the same warnings as notices.
- `tools/check_version_bump.py` FAILS a push (or pull request) that changed
  files under `<id>/` without raising the version in `<id>/addon.xml`. Kodi
  upgrades by version number only. Locally it diffs against `origin/main`; CI
  passes the pushed range's start.

Both are tested in `tests/test_release_checks.py`, which also pins the
workflow's load-bearing lines.

## 4. Which add-ons the hub resolves this way

Both, since 2026-09-26. Bump, push, done.

- `skin.estuary.pov`: 1.4.3 was the first CI-built release the hub served.
- `service.tvos.pythonfix`: switched later the same day (hub commit `fe283c3`);
  its release asset `service.tvos.pythonfix-1.1.0.zip` is byte-identical to the
  copy the hub used to commit under `repo/addons/hosted/service.tvos.pythonfix/`,
  so 1.1.0 stayed and that directory is deleted. Nothing is copied into the hub
  for either add-on any more; a committed copy there is a bug.

## 5. Burned numbers

Two different publish paths must never share a version. 1.4.2 was the last
skin version copied into the hub by hand; 1.4.3 is the first from CI, and
carries no other change. 1.2.6 was burned the same way earlier.

## 6. The hub dispatch

The publish job dispatches `repository_dispatch` type `ezmpp-release` at the
hub (the name is historical, from the first sibling repo to do this) with the
repository secret `T7B_DISPATCH_TOKEN` (set on this repo 2026-09-26). Without
the secret that step fails on its own, with `continue-on-error`, and prints one
line naming the secret; the hub's daily cron is the backstop and picks the
release up within 24 hours.
A manual run of the workflow on `main` (`gh workflow run tests.yml --ref main
-R moquette/kodi-estuary-pov`) publishes nothing new but always re-sends the
dispatch, which is how a missed notification is repaired without burning a
version number.

## 7. Visibility

The hub reads the release through the GitHub API and downloads the asset
through its API URL, so it works on a public repo without a token and on a
private repo with a token that can read it. This repo is PUBLIC since
2026-09-26 (it was private for a few hours that morning, during which the
hub's own `GITHUB_TOKEN` could not read it and the skin served stale at
1.4.2). The hub's `pages.yml` still reads an optional `T7B_SOURCE_READ_TOKEN`
secret first; it is an escape hatch for a private source repo, not a
requirement. Keep this repo public, or store that token on the hub before
making it private again.
