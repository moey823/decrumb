# Update acceptance

Sparkle owns signature validation, extraction, atomic replacement and relaunch.
Decrumb coordinates its separate worker using the real app updater delegate and a
private durable transition in the existing runtime directory.

## Repeatable checks

```sh
python3 build.py --app
build/status-tests
python3 -B -m unittest discover -s tests -p 'test_*.py' -v
python3 -B tools/smoke_app.py
```

Synthetic updater tests cover active and paused workers, automatic start after
relaunch (including a prior pause), pause preservation on cancellation, disabled login,
serialization with pairing/settings, independent worker-lock contention, matching
abort tokens, failed stops/restarts, changed helper paths, and byte-for-byte
survival of queued notes/removal state and receipts. Expired time by itself never
permits worker resumption. Release tests reject inconsistent version, OS,
architecture, archive length, URL, signature shape or pinned updater security
settings. These unit tests are separate from the real Sparkle integration run.

## Signed installation acceptance

Run the isolated integration harness with the existing signing identity:

```sh
python3 -B tools/test_sparkle_update.py \
  --identity "$DECRUMB_SIGNING_IDENTITY" --account decrumb-updates
```

It builds two distinct Developer ID signed fixture applications (builds 1 and 2)
using the production `AppUpdater.swift`, pinned Sparkle framework, and production
Python update coordinator. Sparkle's official signer signs the local feed and
archive; the real installer replaces the bundle and relaunches build 2. The
test-only native driver accepts dialogs, and a synthetic process holds the same
worker lock used by the real cleaner. Random fixture bundle identifiers isolate
preferences and caches. The HTTP server binds only to loopback; production uses
the pinned HTTPS feed. Private keys remain in Keychain.

Scenarios cover active and paused cleaning, manual install, dismissal followed by
ordinary quit, automatic install-on-quit, unsaved settings and pairing deferral,
forced GUI termination during handoff, cancellation, invalid signed-feed bytes,
and invalid signed-archive bytes. The crash case substitutes the watchdog's
reopen action after Sparkle has actually replaced the bundle. Account sentinel
bytes, queued-work sentinel bytes and receipt sentinel bytes must survive
unchanged. Unit tests separately exercise the real SQLite queue/receipt schema,
failed-stop retries, recovery ownership, service ownership and actual lock
contention. The integration fixture does not run Signal or mutate LaunchAgents.

These checks require normal macOS process/signing access. Real Signal pairing,
reception, and a login/logout cycle remain separate release acceptance; the
updater test does not establish real-account behavior.

## Publishing

Recorded September 20, 2026: all ten signed integration scenarios passed on
macOS 27.0, alongside 134 offline regression tests. RC2/build 2 is published with
the signed feed live at the URL below. Its public update archive and feed passed
official signature verification after download; the public DMG passed Gatekeeper
and packaged smoke from a read-only mount. See [VALIDATION.md](VALIDATION.md) for
the release source commit, checksum and remaining real-device boundaries.

Production packaging requires an existing Developer ID Application identity,
notarization Keychain profile, Sparkle Keychain account reference and immutable
release tag. It produces the notarized/stapled DMG, matching source ZIP, update
ZIP, signed appcast, checksums and release receipt. Upload assets before deploying
the exact signed appcast to `https://mkships.app/decrumb/appcast.xml`. Verify the
hosted bytes and signatures after download. Never hand-edit a signed appcast,
replace an existing release asset, publish a development image as production,
or bypass Gatekeeper for acceptance.

Build 1 / RC1 users must install one updater-enabled DMG manually. Existing
account state remains in `~/Library/Application Support/Decrumb`; app replacement
must not copy keys into the app bundle or require relinking.
