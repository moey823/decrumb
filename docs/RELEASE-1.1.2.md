# Decrumb 1.1.2 release record

**1.1.2**, build **9**, was published September 25, 2026:
[Decrumb 1.1.2](https://github.com/moey823/decrumb/releases/tag/v1.1.2).
Tag `v1.1.2` records source `d88d022570931fdedc62c5f62ebf58f50b3a0223`.
Mac/Pi artifacts and the tested Umbrel image are published. Downloaded-artifact
acceptance passed, and the verified stable Mac update feed now offers build 9.

## Changes

- Process incoming disappearing messages with the same cleaning rules as other
  incoming links. Generated notes use the Note to Self timer and configured
  cleanup policy; they do not inherit the source chat's timer.
- Accept authenticated self-to-self phone commands with a valid disappearing
  timer. Authentication, freshness, replay protection, view-once/spoiler exclusions
  and Note-to-Self-only delivery remain intact.
- Show the actual bundled cleaning defaults, domain rules, exceptions and limits
  in Mac **Settings → Cleaning rules → View domains and rules**.
- Embed [`update-notes/1.1.2-9.txt`](update-notes/1.1.2-9.txt) in the signed updater
  feed. Packaging requires notes matching the app's version/build.

## Completed evidence

- Offline Python suite: 279 passed, 4 platform skips (283 total). Development
  build and native Mac status tests passed.
- Development and production packaged synthetic smoke passed, including incoming
  disappearing X-link cleaning and authenticated phone commands.
- All ten signed Sparkle scenarios passed: install, paused, quit, automatic,
  drafts, pairing, crash, cancel, bad-feed and bad-archive.
- Release source passed [Mac/Linux CI](https://github.com/moey823/decrumb/actions/runs/36154172238)
  and [native Windows CI](https://github.com/moey823/decrumb/actions/runs/36154175687).
- [Container CI](https://github.com/moey823/decrumb/actions/runs/36153723444) tested
  and published ARM64 and AMD64 from source
  `b03d5a4701ab0b5e62a521ebca2513254a5f678e`. The tested image is pinned at
  `sha256:bd41c8c9b61a9e5f0171e4d2a3af0fbddc5fecaa5c4b67225f46dafe0e7b54ce`;
  both architectures were anonymously verified. See [UMBREL.md](UMBREL.md)
  for exact image provenance.

## Mac packaging

The Developer ID signed app and DMG received Apple's **Accepted** notarization
results. Both tickets were stapled, and both Gatekeeper assessments passed.
App submission: `28e27995-f05d-4926-958a-498e967b8870`.
DMG submission: `e25f8dbf-87ae-48a2-9c63-f696af193389`.

The production receipt is `build/Decrumb-1.1.2-9-arm64-release.json`; it records
notarization, artifact hashes and source-material provenance. The corresponding
source archive includes the release materials identified by manifest SHA-256
`099483024bfc3132e7455a303957a6233ff47aad32a82e4c2e4fd65dce057ba2`.
Packaging evidence: `build/package.log`.

Published primary artifacts (checksums accompany the downloads):

| Artifact | Bytes | SHA-256 |
| --- | ---: | --- |
| `Decrumb-1.1.2-9-arm64.dmg` | 67,495,078 | `fd673eb2d59d10ad3fdf39f8b418c820aa5de38b343fcaf707d17e63085a91df` |
| `Decrumb-1.1.2-9-arm64-sources.zip` | 462,586,208 | `689810da07c8bcbba7770c9867838dede8201f2cb5bc0b3c575ef8a72e889591` |
| `Decrumb-1.1.2-9-arm64-update.zip` | 62,303,319 | `013ed283e7a04d4b80fc681413d29d2507db9dcbcc218cdf7feebcc85da29921` |
| `Decrumb-1.1.2-9-arm64-appcast.xml` | 1,944 | `14831e3d629a1950afcbb9a53c6586f739fdf59e09bc35e4e46b93132c6275dc` |
| `Decrumb-1.1.2-9-arm64-release.json` | 1,401 | `0c1dafea9fbb90c60c7ea803fec70b06140e1eaf1b110eaf45227c9aa021f762` |
| `Decrumb-1.1.2-9-linux-arm64.tar.gz` | 554,641 | `0060d555b764199222aa10887bce3e90e585e5af0d5ea615f1dc99693beb74e1` |

## Publication and hosted acceptance

The release was published at `2026-09-25T15:40:31Z`. All eleven public GitHub
assets match the local artifact sizes and GitHub-computed SHA-256 digests,
including the corresponding-source ZIP. Evidence:
`build/github-v1.1.2-verified.json`. The tag and published assets are immutable.

Downloaded artifact checksums match the published files. App/DMG signatures,
stapled tickets and Gatekeeper assessments passed. Sparkle's official verifier
accepted the downloaded archive and signed feed, including the expected embedded
notes; bundled rules and version 1.1.2/build 9 were verified. Records:
`build/hosted-v1.1.2/verified.json` and
`build/hosted-v1.1.2/signatures-verified.json`.

All six packaged smoke groups passed using the exact downloaded app copied with
`ditto` from the verified DMG into isolated `installed/Decrumb.app`. The unchanged
`tools/smoke_app.py` exercised bootstrap/preview, pairing cancellation,
disappearing-message X-link delivery, note removal, phone commands and native
Signal CLI loading with isolated empty state. Log:
`build/hosted-installed-smoke.log`.

Two earlier direct-from-mounted-DMG smoke attempts exceeded the harness's existing
20-second subprocess limit at different commands (bootstrap, then clear-diagnostics)
while the host reported load 49.8 on eight logical CPUs. The same smoke passed
from the installed copy without changing assertions or time limits. Source and
release artifacts were unchanged; normal app bootstrap has no 20-second harness
timeout. Direct-from-mounted smoke completion is not claimed.

Mkships commit `d42de5659f52a51dc7c542774c98154aaa5f1482` deployed the signed
feed and updated download, release, privacy and support pages. GitHub Pages
reported a successful build without errors. All five canonical live files match
the expected bytes; the downloaded live feed also passed Sparkle's official
signature verifier. Evidence: `build/website-v1.1.2-verified.json`.

The live feed is byte-identical to the signed release artifact (SHA-256
`14831e3d629a1950afcbb9a53c6586f739fdf59e09bc35e4e46b93132c6275dc`). It advertises
1.1.2/build 9 with embedded notes and the immutable update archive URL below.
Mac **Check for Updates** now offers this release.

The update archive's immutable publication path is
`https://github.com/moey823/decrumb/releases/download/v1.1.2/Decrumb-1.1.2-9-arm64-update.zip`.
The stable feed remains `https://mkships.app/decrumb/appcast.xml`. Existing tags
and release assets remain unchanged.

Release tests used synthetic fixtures and isolated state. Existing accounts
and runtime data stay outside the app bundle. Automated acceptance does not claim
new live Signal or physical-device validation. Windows remains an unsigned
source-build preview.
