# Decrumb 1.1.2 release record

**1.1.2**, build **9**, is in preparation. This record does not yet claim a
published release or completed acceptance of its artifacts. Planned tag: `v1.1.2`.

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

## Required acceptance — pending

- Validate shared 1.1.2/build 9 release metadata and matching platform versions.
- Run the offline Python suite, native Mac status tests and development build.
- Pass Mac/Linux and native Windows CI at the release source revision.
- Build, test and publish the matching ARM64/AMD64 Umbrel image, then pin and
  verify its public digest.
- Produce the Developer ID signed app and DMG; receive Apple's notarization
  acceptance, staple both tickets and pass Gatekeeper assessments.
- Run packaged synthetic smoke against the exact candidate. Verify the rules
  catalog and the disappearing-message X-link and phone-command paths.
- Pass all ten signed Sparkle scenarios: install, paused, quit, automatic, drafts,
  pairing, crash, cancel, bad-feed and bad-archive.
- Publish immutable Mac/Pi artifacts, matching source materials, checksums,
  signed update archive/feed and release receipt at `v1.1.2`.
- Download the hosted artifacts and verify checksums, signatures, notarization
  tickets and packaged smoke. Verify the official Sparkle signatures on the
  downloaded archive and feed, including embedded release notes.
- Deploy the verified feed to the stable update URL, then confirm it advertises
  1.1.2/build 9 and points to the published immutable update archive. Update the
  download/release pages after acceptance.

## Planned artifacts

The new release uses these names; their existence, sizes and checksums remain
pending until packaging and publication complete:

| Artifact | Purpose |
| --- | --- |
| `Decrumb-1.1.2-9-arm64.dmg` | Signed, notarized Mac download |
| `Decrumb-1.1.2-9-arm64-sources.zip` | Corresponding source and build materials |
| `Decrumb-1.1.2-9-arm64-update.zip` | Signed Sparkle update archive |
| `Decrumb-1.1.2-9-arm64-appcast.xml` | Signed feed with embedded release notes |
| `Decrumb-1.1.2-9-arm64-release.json` | Packaging receipt and provenance |
| `Decrumb-1.1.2-9-linux-arm64.tar.gz` | Experimental Pi release |

The update archive's immutable publication path will be
`https://github.com/moey823/decrumb/releases/download/v1.1.2/Decrumb-1.1.2-9-arm64-update.zip`.
The stable feed remains `https://mkships.app/decrumb/appcast.xml`. Existing tags
and release assets remain unchanged.

Release tests must use synthetic fixtures and isolated state. Existing accounts
and runtime data stay outside the app bundle. Automated acceptance does not claim
new live Signal or physical-device validation. Windows remains an unsigned
source-build preview.
