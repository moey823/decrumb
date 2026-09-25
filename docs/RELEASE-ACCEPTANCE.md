# Download and installation acceptance

Run this against the exact signed, notarized release candidate that will be
distributed. A source build or an app copied directly from the build directory
does not establish that the public download installs correctly.

## Prepare the candidate

- Choose the publisher's Developer ID Application identity and an existing
  notarization Keychain profile. Keep certificates, private keys, credentials,
  and account-specific configuration outside the repository.
- Build with explicit app version, increasing build number, architecture, and
  minimum macOS version. Test every platform claimed by the download page.
- Complete and verify the third-party source/notices inventory. Publish the
  corresponding-source archive beside the DMG, with checksums and release notes.
- Notarize and staple the app and disk image, verify signatures and Gatekeeper
  acceptance, and record the exact artifact checksums. Do not replace an already
  published artifact with different bytes under the same versioned filename.

## Prepare the test Mac

Check Applications, per-user Applications, and Decrumb's dedicated login items.
If a development installation exists, pause its worker, disable its login
startup, quit its interface, and remove that app. Confirm its worker has stopped.
Removing the interface alone does not stop an already running worker.

For subsequent Decrumb upgrades, preserve `~/Library/Application Support/Decrumb`
and its linked account. Do not delete Signal credentials, reset the account,
or change another Signal service
to make a test pass. A fresh-install test and an upgrade test are separate cases;
record which was performed. Build output in a source checkout is not itself an
installed application.

## Download and install

1. Follow the Decrumb download page to the versioned release asset. Verify the
   DMG's SHA-256 against the published checksum. Keep the download's quarantine
   metadata intact; do not disable Gatekeeper or use a bypass command.
2. Open the downloaded DMG. Confirm its app identity, version, Applications
   shortcut, and supported-platform instructions.
3. Copy Decrumb to Applications, eject the image, and launch that installed copy.
   It must start under normal macOS security settings without developer tools,
   Homebrew, Python, Java, or a separate Signal CLI installation.
4. Confirm the interface and helper paths point to the installed bundle, not the
   source checkout, mounted image, or retired development files.
5. For a fresh installation, connect using the app's QR and Signal's Linked
   Devices screen. The account owner scans on their phone; do not save or post
   the linking code. For an upgrade, verify the existing link and settings remain.

## Exercise the installed app

Use synthetic content and an authorized test account. Never attach real message
or account data to a bug report.

- Preview `https://example.org/article?utm_source=signal&id=42`. The output should
  remove `utm_source` and preserve `id=42`, without visiting the URL.
- Have a test sender manually send an ordinary incoming message containing that
  URL. Confirm exactly one cleaned note arrives in Note to Self, with the random
  Decrumb code and the configured sender-attribution preference.
- Repeat the incoming-link check in a chat with disappearing messages enabled.
  Confirm a cleaned note arrives and follows the Note to Self timer and configured
  note-cleanup policy, without copying the source chat's timer.
- Verify outgoing and Note to Self messages do not loop. Confirm view-once and
  spoiler test content does not create a cleaned note. With phone commands enabled,
  confirm `/decrumb clean` works when Note to Self has a disappearing-message timer.
- Request removal of a tracked synthetic note within the supported window.
  Check the actual Signal devices and any deleted-message marker. An accepted
  request alone is not proof of erasure.
- Test an optional lifetime or sweep, Keep, and local queue clearing. Verify
  unrelated personal notes are unchanged.
- Pause, quit/reopen, and test login startup. Reopening must end the pause. Verify offline
  recovery and confirm that changing cleaning rules clears pending work made
  under the previous rules.
- After fresh pairing, confirm cleaning starts without pressing Resume. Quit and
  reopen an enabled installation with its worker stopped; it should start once.
  Reopening while it is running must not restart it. A failed connection should
  offer Retry connection, while a pause in the current session offers Resume cleaning.
  Opening from Finder or the menu bar must end that pause without a second click.
- For an upgrade, repeat with saved custom rules, a paused worker, queued work,
  and existing receipt metadata. An interrupted replacement must not require
  unlinking the account to recover.

Record the release asset hash, macOS version, architecture, fresh/upgrade case,
and pass/fail outcomes without message bodies, URLs from real conversations,
contacts, pairing images, keys, or raw logs. Promote the candidate to the general
download only after the required acceptance cases pass.
