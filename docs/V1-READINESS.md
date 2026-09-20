# Decrumb v1 readiness

Status recorded 2026-09-20. The project is ready to share as open-source
development work. **The consumer-ready DMG is coming soon**, by release-owner
choice; a local development image is not presented as a finished public installer.

## Completed

- Native SwiftUI/AppKit menu bar interface compiles, with local QR onboarding,
  pause/resume, editable rules, previews, and generated-note controls.
- The standalone Apple Silicon app packages its Python worker, Swift cleaner,
  and checksum-verified signal-cli 0.14.8 dependency. Development signing and
  recursive signature verification pass.
- The recorded full offline run passed **113 Python tests**. Native status tests
  also passed. See [VALIDATION.md](VALIDATION.md) for the tested scope and limits.
- Packaged smoke tests use synthetic data and fake Signal to exercise pairing
  cancellation, incoming-message filtering, deduplication, attributed notes,
  private receipt metadata, targeted removal requests, and shutdown.
- Notes have searchable Decrumb codes and optional sender display names. Cleanup
  is authorized by local send receipts and account binding, with manual requests,
  individual lifetimes, and periodic sweeps. The UI distinguishes requests from
  confirmed erasure and describes Signal's supported removal window.
- Local storage behavior, retention, privacy limits, upstream source provenance,
  and third-party dependencies are documented. Runtime account files are outside
  the source checkout and app bundle.
- Local development DMG packaging creates an Applications shortcut, verifies the
  image and app signature, and writes a SHA-256 checksum file.
- An explicit production packaging path supports Developer ID signing, hardened
  runtime, version/build and deployment-target inputs, source-material checks,
  Apple notarization/stapling, and Gatekeeper assessment. These checks must pass
  on the actual release; a successful mocked packaging test is not a notarization.
- The dependency collector has verified corresponding sources, build materials,
  and required notices with no unresolved dependency gaps. Every production
  build must regenerate or validate the packet against its exact source inputs.

## Required before the consumer download

1. **Distribution signing and notarization.** Configure Developer ID signing and
   appropriate hardened-runtime settings for nested executables; notarize and
   staple the release artifacts. Validate a downloaded installation under normal
   Gatekeeper settings on a clean Mac.
2. **An explicit supported platform.** Choose and test the minimum macOS version
   against the GUI and every bundled executable. The candidate targets Apple
   Silicon and macOS 26.4 or later. Packaged worker checks pass on 26.4 and 27.0;
   downloaded installation and interface acceptance on 26.4 remain to be checked.
3. **Publish redistributable dependency materials.** Ship the verified
   corresponding-source packet and notices beside the matching binary release.
   An upstream source link alone is not the binary release's source package.
   See [THIRD-PARTY.md](THIRD-PARTY.md).
4. **Real-device acceptance.** On an explicitly authorized test account, verify
   linking, ordinary incoming links, privacy exclusions, sender attribution,
   Note to Self delivery, manual and scheduled removal, offline recovery,
   login startup, and pause persistence. Confirm how deleted-message markers
   appear. Fake-Signal tests cannot establish these outcomes.
5. **A reproducible release identity and recovery path.** Select the explicit
   app version/build inputs, publish checksums and release notes, and
   verify manual replacement of an existing app preserves the linked account,
   rules, receipts, queued work, and pause preference. Document how to recover
   from an interrupted upgrade without unlinking the account.

The download page should state the actual supported OS and architecture and link
only to a completed release. Until then it should say **coming soon** and offer
the source and development instructions without implying a notarized installer
is available.

## Can follow v1

- **Sparkle automatic updates.** Useful, but not required for an initial release
  with a documented manual-update path. It needs a stable HTTPS feed, archive
  signing, worker-aware installation, and update/recovery tests before enabling.
- **Intel and additional macOS versions.** Add only when builds and acceptance
  tests support the claim.
- **Further footprint reductions and features.** A replacement worker language,
  extra cleanup policies, additional integrations, and more rules can follow the
  core release. The bundled Signal dependency dominates current app size.

The [distribution design](DISTRIBUTION.md) describes the proposed updater and
hosting approach; this checklist defines the narrower initial-release gate.
