# Decrumb 1.1.3 release preparation

**1.1.3**, build **10**, is in preparation. Source metadata is updated; the
published release and stable Mac feed remain **1.1.2/build 9**. No 1.1.3
publication, Apple notarization, hosted-artifact acceptance or live feed update
is claimed by this record.

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

Updater ownership, bounded recovery and visible retry entered source in
`a2bd4bf`. The final release source commit and immutable tag are not recorded yet.
The plain-text updater notes are
[`update-notes/1.1.3-10.txt`](update-notes/1.1.3-10.txt); the package must embed
these notes in the signed appcast unchanged.

## Pending release checks

- [x] Core changes committed as `7ef5e4a`. Offline Python suite: 309 passed,
  4 platform skips (313 total). Native status tests, development app build and
  all six packaged synthetic smoke groups passed.
- [x] All fourteen isolated signed Sparkle scenarios passed, including actual
  standard updater buttons, preparation failure/retry and Quit with a ready
  update. The Quit fixture verified replacement completed without relaunch,
  stopped cleaning and preserved synthetic account, queue and receipt bytes.
  The production coordinator/backend were used with a synthetic worker service.
- [ ] Pass Mac/Linux and Windows CI for the frozen release source.
- [x] [Container CI](https://github.com/moey823/decrumb/actions/runs/36164404884)
  passed both architectures and published source `7ef5e4a`. The store pins
  `sha256:e0bad5861cb0c57c54dcbe0f3210971329d4235ded08a6ab7f62e93be16bf3c9`.
  Anonymous index, child-manifest and config verification confirmed version
  1.1.3 and the exact source on ARM64 and AMD64.
- [ ] Collect complete corresponding-source materials for the final checkout.
- [ ] Build the production Mac app; pass packaged synthetic smoke; notarize,
  staple and verify the app and DMG with Gatekeeper.
- [ ] Package the Pi archive, source ZIP, update ZIP, signed appcast, checksums
  and production receipt for 1.1.3/build 10.
- [ ] Publish immutable `v1.1.3` assets and verify their public sizes and hashes.
- [ ] Verify the downloaded app, DMG, archive/feed signatures and installed-copy
  synthetic smoke before promoting the general download.
- [ ] Deploy the exact signed feed and matching website pages, then verify the
  canonical live files. Record publication, source, CI and packaging evidence.

## Planned artifacts

The release prefix is `Decrumb-1.1.3-10-arm64` for the Mac DMG,
corresponding-source ZIP, update ZIP, signed appcast and release receipt. The Pi
archive is `Decrumb-1.1.3-10-linux-arm64.tar.gz`. Checksums accompany downloadable
archives and the appcast. Existing published tags and assets must not be replaced.

The planned immutable update archive URL is
`https://github.com/moey823/decrumb/releases/download/v1.1.3/Decrumb-1.1.3-10-arm64-update.zip`.
The stable feed remains `https://mkships.app/decrumb/appcast.xml`.

Release acceptance uses synthetic fixtures and isolated state. Accounts,
messages and runtime data remain outside Git and the app bundle. Automated
checks do not establish new live Signal or physical-device acceptance. Windows
remains an unsigned source-build preview.
