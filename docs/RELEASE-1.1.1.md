# Decrumb 1.1.1 release record

**1.1.1**, build **8**, adds X/Twitter `s`/`t` share-parameter cleanup and the
running version/build in `/decrumb status`. Tag `v1.1.1` points to immutable source
commit `3b955b92eabe77ffb1809099484b432a23cdf53f`. This record adds post-build
evidence; it does not change the completed artifacts or corresponding sources.
Published September 25, 2026: [Decrumb 1.1.1](https://github.com/moey823/decrumb/releases/tag/v1.1.1).
Mac/Pi assets, the Umbrel image and the signed Mac update feed are available.

## Completed evidence

- Shared release metadata and platform versions are 1.1.1/build 8.
- Offline Python suite: 272 passed, 4 skipped (276 total). Mac status tests passed.
- Developer ID signed app and DMG: Apple notarization accepted and both stapled.
  The receipt is `build/Decrumb-1.1.1-8-arm64-release.json`; it records asset
  SHA-256 digests, source-material provenance and both notarization results.
- Packaged synthetic smoke passed (`build/packaged-smoke.log`), including
  bootstrap, previews, pairing cancellation, cleanup, delivery, removal and phone
  commands. The real Signal client used an isolated empty configuration.
- All ten signed Sparkle scenarios passed (`build/sparkle-acceptance.log`):
  install, paused, quit, automatic, drafts, pairing, crash, cancel, bad-feed and
  bad-archive. These checks used synthetic worker state.
- A fresh bundle reported version 1.1.1/build 8 and correctly cleaned the synthetic
  X/Twitter test link.
- [Mac/Linux CI](https://github.com/moey823/decrumb/actions/runs/36140645832)
  and [native Windows CI](https://github.com/moey823/decrumb/actions/runs/36140649249)
  passed. Windows remains an unsigned source-build preview.
- [Container CI](https://github.com/moey823/decrumb/actions/runs/36140653704)
  passed on ARM64 and AMD64 and published the image. The tested digest is pinned
  on `main` and verified through an anonymous manifest download; exact image
  provenance is recorded in [UMBREL.md](UMBREL.md#build-and-verify).

Published artifacts, with checksums alongside them:

| Artifact | Bytes |
| --- | ---: |
| `Decrumb-1.1.1-8-arm64.dmg` | 67,213,312 |
| `Decrumb-1.1.1-8-arm64-sources.zip` | 462,565,773 |
| `Decrumb-1.1.1-8-arm64-update.zip` | 62,242,937 |
| `Decrumb-1.1.1-8-linux-arm64.tar.gz` | 545,066 |

The original signed feed is `build/Decrumb-1.1.1-8-arm64-appcast.xml`, deployed unchanged
to [the stable feed](https://mkships.app/decrumb/appcast.xml) by mkships commit
`cdeec424bab41c0f8ad7b84739cc2ab9d3d85dc1`. The notes correction below supersedes
that feed at the stable URL; the GitHub release assets remain immutable.

## Hosted acceptance

- All eleven GitHub assets match their local sizes and GitHub-computed SHA-256
  digests (`build/hosted-assets-verification.json`). The release is stable and latest.
- Downloaded DMG SHA-256:
  `89c53fc949561b74c674702517b42ea0c000869ca3a265e5641849a150d39286`.
  Image integrity, app/DMG signatures, both stapled tickets and both Gatekeeper
  assessments passed. The read-only mounted app reported 1.1.1/build 8 and all
  six packaged smoke groups passed. The image was detached afterward; nothing
  was installed. Logs: `build/hosted-mac-acceptance.log`, `build/hosted-mac-smoke.log`.
- Downloaded update ZIP, appcast and Pi archive match their local SHA-256 digests.
  Sparkle's official verifier accepted the downloaded feed and update archive.
- At initial publication, the live feed advertised 1.1.1/build 8 and matched the signed artifact byte for
  byte. Its official signature and the live download/release pages passed
  verification (`build/live-feed-verification.json`). **Check for Updates** can
  now offer build 8.

## Updater release-notes correction

Later on September 25, the update window's release-notes area was reported to
spin indefinitely. The app sets `SUShowReleaseNotes=true`, but the original feed
had neither an inline description nor a release-notes URL. Sparkle 2.10.0 opens
the notes area and starts its spinner in that case without a load to complete.

The stable feed was regenerated and signed with the pinned official
`generate_appcast` tool, using `--embed-release-notes` and
[`update-notes/1.1.1-8.txt`](update-notes/1.1.1-8.txt). Mkships commit `dc783fd`
publishes the corrected feed. The archive URL, length, signature, version/build
and publication date remain unchanged. No app rebuild or replacement of existing
GitHub assets is required. The regenerated feed SHA-256 is
`3ef294d0aef4789d73508274bde413380524eb2f66fb8ca28c830200a4870c20`.

- Official Sparkle verification passed for the regenerated feed and the original
  archive; the feed contains the exact expected plain-text notes.
- A hidden native fixture using the pinned Sparkle framework reproduced the
  missing-notes case (spinner starts, never stops). With inline notes, the native
  text view rendered the exact expected text and stopped the spinner. Both
  windows remained hidden; no real app or account state was used.
- Packaging now requires version/build-specific notes and validates their
  presence and content in the generated feed. The offline suite passed 275 tests
  with 4 platform skips (279 total), and `python3 build.py` completed.

Existing accounts and runtime data stay outside the app bundle. Release tests use
synthetic fixtures and isolated state. New live Signal or physical-device
acceptance is not claimed by these automated checks.
