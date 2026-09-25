# Decrumb 1.1.3 release record

**1.1.3**, build **10**, was published September 25, 2026:
[Decrumb 1.1.3](https://github.com/moey823/decrumb/releases/tag/v1.1.3).
Tag `v1.1.3` records source `c3c11117b325a9d034173009dba774b18f4f350b`.
Mac/Pi artifacts and the tested Umbrel image are published. Downloaded-artifact
acceptance passed, and the verified stable Mac update feed now offers build 10.

## Changes

- Keep update ownership with the native Mac app across short-lived helper
  launches, so failed preparation and claimed transitions can be retried.
- Bound recovery-service operations and preserve their ownership metadata when
  the outcome is uncertain. Show an actionable error instead of waiting forever.
- Bring blocked-install explanations into view, with **Install and Relaunch**
  retry and a route back to unsaved settings.
- Make **Quit Decrumb** stop and verify the worker before exiting. Preserve
  queued links even when `discard_on_pause` is enabled, as well as sent-note
  records, the linked account, settings and stored Start at login preference.
- Add **Hide Decrumb** for leaving cleaning active while hiding the windows.
  Reopening the app resumes cleaning. A pending update is checkpointed on Quit
  without arming a watchdog that would reopen the app; the transition remains
  until a later launch reconciles installation.
- Keep Pi, Umbrel and Windows cleaning behavior unchanged under the shared
  1.1.3/build 10 version.

## Completed evidence

- Offline Python suite: 309 passed, 4 platform skips (313 total). Development
  build and native Mac status tests passed. Evidence: `build/quit-tests.log`.
- All six production packaged synthetic smoke groups passed: bootstrap/preview,
  pairing cancellation, disappearing-message X-link delivery and deduplication,
  self-only note removal, authenticated phone commands, and real bundled Signal
  CLI loading with isolated empty state. Evidence: `build/release-1.1.3-smoke.log`.
- All fourteen signed Sparkle scenarios passed: install, paused, quit, automatic,
  drafts, pairing, crash, prepare-failure, standard-install,
  standard-prepare-failure, standard-quit-pending, cancel, bad-feed and bad-archive.
  Standard scenarios exercised the real updater buttons. Quit with a ready
  update completed replacement without relaunch, kept cleaning stopped and
  preserved synthetic account, queue and receipt bytes. The production
  coordinator/backend used a synthetic worker service. Evidence:
  `build/sparkle-full-acceptance.log`.
- Frozen source passed [Mac/Linux CI](https://github.com/moey823/decrumb/actions/runs/36164691420)
  and [native Windows CI](https://github.com/moey823/decrumb/actions/runs/36164691301).
  All four platform jobs succeeded. Evidence: `build/final-1.1.3-ci.json`.
- [Container CI](https://github.com/moey823/decrumb/actions/runs/36164404884)
  tested and published ARM64 and AMD64 from source
  `7ef5e4ae6b50b6839e18a4d08ba622f63857e81a`. The tested image is pinned at
  `sha256:e0bad5861cb0c57c54dcbe0f3210971329d4235ded08a6ab7f62e93be16bf3c9`.
  Anonymous index, child-manifest and configuration downloads verified digests,
  architecture, version 1.1.3 and the exact source labels. Evidence:
  `build/container-1.1.3-ci.json` and `build/container-1.1.3-verification.json`.
  See [UMBREL.md](UMBREL.md) for image provenance.

## Mac packaging

The Developer ID signed app and DMG received Apple's **Accepted** notarization
results. Both tickets were stapled, and both Gatekeeper assessments passed.
App submission: `6438c408-98b2-4d9a-9687-095050fa0d79`.
DMG submission: `4a537bb0-8c89-4c58-8a13-57420be776bb`.

The production receipt is `build/Decrumb-1.1.3-10-arm64-release.json`; it records
notarization, artifact hashes and source-material provenance. The corresponding
source archive includes materials identified by manifest SHA-256
`d9a0e038e528662c4a3db3fb79854d6b595393ccc1ce845ac6856efed5c0ac4f`.
Packaging evidence: `build/release-1.1.3-package.log`.
The signed feed embeds [`update-notes/1.1.3-10.txt`](update-notes/1.1.3-10.txt).

Published primary artifacts (checksums accompany the downloads):

| Artifact | Bytes | SHA-256 |
| --- | ---: | --- |
| `Decrumb-1.1.3-10-arm64.dmg` | 67,416,499 | `3034358ab3aaded206540e098fdd66339f385624778e162258556e82742f0394` |
| `Decrumb-1.1.3-10-arm64-sources.zip` | 462,616,508 | `e1db831eee9b1b9ae42b9d81e03e573386f119e8cdcbac6ed5d82def06e4c797` |
| `Decrumb-1.1.3-10-arm64-update.zip` | 62,334,871 | `0676b3c301ea2c097a46c7fc4bc704f4789f5c1982682a8cbdf52b9073b9d039` |
| `Decrumb-1.1.3-10-arm64-appcast.xml` | 1,964 | `b5ed64d2940c18c6b697c79b490367820de4eba090dc1de881dcd10c004aa19b` |
| `Decrumb-1.1.3-10-arm64-release.json` | 1,406 | `503741501615284b05335fe94a6fe52501cfbcbb3e0b754a2d7e84b0173330a7` |
| `Decrumb-1.1.3-10-linux-arm64.tar.gz` | 567,012 | `5387f8447834e35a55d8b14d13a0422b57163054373acea151035e69909b2f9c` |

## Publication and hosted acceptance

The release was published at `2026-09-25T17:14:32Z`. The tag and public assets
are immutable.

All eleven public GitHub asset sizes and GitHub-computed SHA-256 digests match
the local artifacts, including the corresponding-source ZIP. Evidence:
`build/github-v1.1.3-verified.json`.

The exact public downloads passed checksum verification. The downloaded app
and DMG passed Gatekeeper and stapled-ticket checks; Sparkle's official verifier
accepted the update archive and signed feed, including the expected embedded
notes. All six packaged synthetic smoke groups passed using an isolated
installed copy of the downloaded app. The version and build were verified as
1.1.3/build 10. Evidence: `build/hosted-v1.1.3/verified.json` and
`build/hosted-113-verification.log`.

Mkships commit `b6d9063b9b16779f62f7296d3b07b7fedfa2fc3d` deployed the signed
feed and updated download, release, privacy and support pages. GitHub Pages
reported a successful build without errors. All five canonical live files match
the expected bytes; the live feed also passed Sparkle's official signature
verifier. Evidence: `build/website-v1.1.3-verified.json`.

The live feed is byte-identical to the signed release artifact (SHA-256
`b5ed64d2940c18c6b697c79b490367820de4eba090dc1de881dcd10c004aa19b`). It advertises
1.1.3/build 10 with embedded notes and the immutable update archive URL below.
Mac **Check for Updates** now offers this release.

The update archive's immutable publication path is
`https://github.com/moey823/decrumb/releases/download/v1.1.3/Decrumb-1.1.3-10-arm64-update.zip`.
The stable feed remains `https://mkships.app/decrumb/appcast.xml`. Existing tags
and release assets remain unchanged.

Release tests used synthetic fixtures and isolated state. Existing accounts
and runtime data stay outside the app bundle. Automated acceptance does not claim
new live Signal or physical-device validation. Windows remains an unsigned
source-build preview.
