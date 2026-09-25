# Decrumb for Mac, Raspberry Pi, Umbrel, and Windows

<picture>
  <source media="(prefers-color-scheme: dark)" srcset="branding/decrumb-wordmark-inverse.svg">
  <img src="branding/decrumb-wordmark.svg" alt="Decrumb" width="600">
</picture>

A helper that cleans incoming Signal links and saves the result to
**Note to Self**. Stock Signal stays on your phone. Decrumb links as an additional
device; it never replies to contacts or groups.

Run the native menu bar app on a Mac, the background service on a Raspberry Pi,
the Umbrel dashboard, or the experimental Windows CLI.
**The machine must stay awake and online.** An always-on Mac mini or Pi is a good
fit; a sleeping laptop cannot clean links. All platforms use the same rules,
message privacy filters, delivery queue, and note-removal controls.

The Mac app includes its own Python worker, Swift URL cleaner, and pinned native
Signal CLI. Users do not install Python, Java, Homebrew, or Signal CLI separately.
The Pi installer uses Python 3.11+, `qrencode`, and a checksum-pinned ARM64 Signal
CLI download. It pairs through a QR code in the terminal, including over SSH.
There is no hosted message-processing service or AI provider. The Mac and Pi
editions do not open a listening port. The experimental Umbrel edition adds a
private browser dashboard for an always-on server; see the
[Umbrel guide](docs/UMBREL.md) for its release and validation status.

**[Decrumb downloads](https://mkships.app/decrumb/download/).**
**Decrumb 1.1.1** (build 8; `1.1.1` in Umbrel) adds X/Twitter share-link cleanup
and version/build information in `/decrumb status`. The signed, notarized Mac
download and update feed are published and verified, alongside the matching Pi
archive and tested Umbrel image. Choose **Check for Updates** on Mac to install
build 8. Windows remains a source-build preview.
See the [release notes](docs/RELEASE-NOTES.md).
The release targets Apple Silicon Macs with macOS 26.4 or later,
Raspberry Pi OS 64-bit (Bookworm or later), and ARM64 or Intel/AMD Umbrel servers.
Mac releases are signed and
Apple-notarized; the Pi edition is an experimental command-line release.
Version 1.1 adds the experimental native Windows x64 CLI. See the
[Windows guide](docs/WINDOWS.md) and [v1 validation history](docs/V1-READINESS.md)
for platform validation and release limits.

[Website](https://mkships.app/decrumb/) ·
[Download](https://mkships.app/decrumb/download/) ·
[Release notes](https://mkships.app/decrumb/releases/) ·
[Source ZIP](https://github.com/moey823/decrumb/archive/refs/heads/main.zip) ·
[Contributing](CONTRIBUTING.md)

## The app

- **Connect Signal:** display a locally generated QR code, scan it from Signal on
  your phone under Settings → Linked devices → Link a new device, and confirm.
  The QR expires and is removed on completion or cancellation. Generate another
  code from the same screen if needed. Existing linked accounts are recovered
  without registering a new primary account. Cleaning starts automatically after
  connecting; there is no extra Resume step.
- **Overview:** see worker status, sent/queued/unconfirmed counts, and loss/error
  counters. Opening Decrumb starts cleaning automatically, including after a
  pause. Pause lasts until you reopen Decrumb or choose Resume cleaning.
  Connection failures show Retry connection rather than appearing paused.
- **Generated notes:** include an optional sender display name and a searchable
  `#decrumb_` code. Manage tracked notes, request removal, set a lifetime, or choose
  periodic cleanup. Clear queued links locally without removing sent notes.
- **Cleaning rules:** choose all sites, selected sites, or off. Exclude sites;
  remove or preserve exact parameter names per site. Save validates the rules and
  clears pending links authorized under the previous settings.
- **Try a link:** preview unsaved settings locally. Shows before/after and removed
  parameter names. Nothing is fetched, sent, or saved by the preview.
- **Import/export:** transfer versioned JSON rules without account keys or state.
- **Start at login:** optionally run the menu bar interface and enabled worker at
  login. Quitting the interface leaves an active worker running; use Pause to stop
  cleaning. The Mac must remain awake, online and logged in.

## Raspberry Pi

The Pi edition targets **Raspberry Pi OS 64-bit, Bookworm or later** and runs as a
per-user systemd service. It has a command-line interface, terminal QR pairing,
private local storage, rule previews and imports, and generated-note management.
It does not require a monitor, Java, or a desktop environment. See the
[Pi installation and upgrade guide](docs/RASPBERRY-PI.md) for prerequisites,
verified dependency sources, boot startup, and removal instructions.

## Umbrel

Add `https://github.com/moey823/decrumb` as a community app store in Umbrel, then
install **Decrumb** from the **mkships** store. Pair Signal and manage the helper
from its private browser dashboard. ARM64 and Intel/AMD 64-bit containers are
available as an experimental release. See the [Umbrel setup guide](docs/UMBREL.md)
for the app password, persistent storage, updates, and validation limits.

Release versions come from [`release.json`](release.json); see the
[shared release process](docs/DISTRIBUTION.md#one-version-for-every-platform).

## Windows

An experimental **native Windows x64 CLI** is also available to build from source,
with terminal pairing, a hidden background worker and optional startup at login.
See the [Windows guide](docs/WINDOWS.md) for builds, commands and validation limits.
There is not yet a published Windows download.

## Optional phone commands

In the Mac app, open **Cleaning rules**, turn on **Enable commands from Note to Self**,
and save. Or use `decrumb phone-commands enable`
on the Pi. Then write one of these commands in Signal's **Note to Self**:

```text
/decrumb help
/decrumb status
/decrumb clean https://example.com/article?utm_source=share&id=42
```

`clean` uses your current cleaning rules and replies with changed links, or
explains that no links changed. `status` returns the running app's version and
build number, cleaning mode, and queue counts, without machine names, account
identifiers, or message content.
Replies go through the same bounded queue and note-removal controls as cleaned
links. Nothing visits the URL, reads machine files, runs a shell command, or calls
an AI provider. This feature is off by default and accepts only your own self-to-self
messages while the helper is running. Commands sent while stopped are skipped.
Commands also work when Note to Self has a disappearing-message timer enabled.
View-once, spoiler, group, and edited commands are excluded.

On Mac, copy the app to its final location (normally `/Applications`) before connecting
and enabling login startup. If moved later, open it at its new location to
refresh its helper and LaunchAgent paths when cleaning
starts. Reopening also ends a pause.

## Build and validate

Mac development needs Apple command-line tools and Python 3.13 or newer. Build the
Swift components and run the offline tests:

```sh
python3 build.py
build/status-tests
python3 -B -m unittest discover -s tests -p 'test_*.py' -v
```

On Linux, Python 3.11+ and `qrencode` are sufficient: `python3 build.py` prepares
the portable helper without downloading a compiler. Run the same Python suite;
`build/status-tests` is Mac-only. Linux and Mac use different text detectors,
with shared conformance fixtures for cleaning rules and query preservation.

Build the standalone Apple Silicon app:

```sh
python3 build.py --app
python3 -B tools/smoke_app.py
```

The packaging build uses a local virtual environment, pinned PyInstaller, and a
checksum-verified native signal-cli 0.14.8 Homebrew `arm64_sonoma` bottle. Downloads
and generated artifacts stay under ignored `build/`. The result is
`build/Decrumb.app`. Subsequent builds reuse the verified download.

The packaged smoke test uses an isolated temporary runtime and fake Signal
process. It tests onboarding cancellation, cleanup, duplicate suppression and
shutdown. The real bundled Signal executable runs `--version` and lists accounts
using an isolated empty configuration, verifying native library loading without
opening an existing account. Use `--app /Applications/Decrumb.app` to run these
same synthetic checks against an installed copy.
macOS CoreImage and PyInstaller's process semaphores require ordinary OS access;
a restrictive execution sandbox can fail QR/packaged tests independently of the
app. The source worker tests use only synthetic offline fixtures.

To inspect the interface without touching any account or runtime:

```sh
open build/Decrumb.app --args --demo
# Or show the connected overview with synthetic counts:
open build/Decrumb.app --args --demo-connected
```

**Development distribution:** builds are ad-hoc signed by default and restricted
to the build host's macOS version until compatibility testing is done. The build
manifest records that version. This is not a notarized public release. A public
release requires a supported-OS build/test matrix, Developer ID signing with the
appropriate hardened-runtime settings, notarization, and complete third-party
source/notices. `DECRUMB_SIGNING_IDENTITY` selects a signing identity for packaging.
Selecting an identity does not by itself perform the remaining release steps.

Create a local development DMG with an Applications shortcut after building:

```sh
python3 -B tools/package_dmg.py
```

The image and SHA-256 checksum file stay under `build/`. This does not publish or
notarize the app. The native app includes Check for Updates and optional automatic
checks/downloads using Sparkle 2. Both automatic options start off. Signed updates
replace the app and bundled helpers together while preserving the Signal account,
queue, receipts and rules. Cleaning starts when the updated app reopens. RC1 predates the updater and requires
one manual installation of an updater-enabled release. See
[distribution guide](docs/DISTRIBUTION.md) for packaging, hosting and recovery.

## Cleaning behavior

Defaults live in [rules/defaults.json](rules/defaults.json). They include 19 exact
global tracking parameter names, Instagram-specific `stkn`, `igsh`, and
`igshid`, and X/Twitter-specific `s` and `t` (preserved under `/i/redirect`).
On Mac, open **Settings → Cleaning rules → View domains and rules** to see the
installed defaults, including every parameter, domain exception, and protection.
Global cleanup applies to other websites too. Unlisted parameters stay intact;
short links are not expanded. **Try a link** previews your current rules locally.
Custom rules are bounded data, not executable plugins or regexes.

Rule precedence: recognized signature parameters protect the whole link;
excluded sites stay untouched; the mode and selected sites determine eligibility;
explicit keep rules override removals; built-in and custom removals then apply.
Host matching includes subdomains and path prefixes match on a path boundary.
Parameter names are case-insensitive. Functional values, encoding, duplicate
fields, fragments and paths are preserved. Links are never fetched or expanded.
See [URL-CLEANUP.md](docs/URL-CLEANUP.md) for the schema and sources.

- Only fresh incoming text/captions are processed. Messages from before first
  worker startup or more than 24 hours old are skipped.
- Only changed URLs are sent, once per incoming message. Repeated links in one
  message are collapsed. A later message with the same link can produce a note.
  Notes identify Decrumb, include a searchable random code and optionally the
  sender's display name, and contain at most ten cleaned links and 8 KiB.
- Ordinary outgoing/synced messages and Note to Self are ignored to prevent
  loops. Writing a bare link to Note to Self does nothing. If you enable phone
  commands, the explicit `/decrumb` commands described above are accepted from
  your own self-to-self sync transcripts; generated replies cannot trigger them.
- Links in disappearing messages are cleaned too. Generated notes follow your
  Note to Self timer and Decrumb note-cleanup preferences; the source chat's
  timer is not copied to the note.
- View-once content, spoilers, edits, story replies and
  control messages are excluded. Unknown privacy/style metadata fails closed.
  Ordinary attachments, avatars, stories and stickers are skipped. Signal CLI
  0.14.8 makes an exception for long-text attachments: it downloads them through a
  temporary file and reconstructs the message body. Decrumb can process that body
  when it is within the 64 KiB limit. Normal temporary-file cleanup is not a
  guarantee against leftovers after a hard crash.
- No read receipts are requested. Normal Signal delivery receipts still occur.
- Deleting/editing a source message does not retract a note already sent.

## Generated notes and cleanup

New notes use a compact format:

```text
Decrumb · From Alex
https://example.com/article
#decrumb_7f12a096a143fa60eb729fa1
```

Sender names are optional, enabled by default, and omitted when a suitable display
name is unavailable. Decrumb never substitutes a raw phone number or account ID.
The code helps you find the note in Signal. It is not a deletion permission.

Cleanup is manual by default. Choose a 1, 6, 12, or 23-hour default lifetime for
new notes, or periodic cleanup every 1, 6, or 12 hours. Individual notes can have
their own lifetime or a **Keep** preference. Automatic cleanup needs the worker
running with Signal connectivity. Pausing also pauses automatic cleanup.

Decrumb can request removal only of notes for which this installation recorded
an acknowledged send, using that note's original send timestamp and linked-account
binding. Older notes without receipts and ambiguous sends cannot be managed.
Signal's supported removal window is 24 hours; a missed window is shown rather
than reported as success. **Removal requested** means Signal CLI acknowledged the
request, not that every device erased the note. A deleted-message marker can remain.

**Clear queued links** discards local unattempted notes. **Discard queued links on
pause** is optional and off by default. These controls preserve the Signal account
and other personal notes. See [note lifecycle](docs/NOTE-LIFECYCLE.md) for policy,
storage details, limits, and verified upstream behavior.

## Privacy and delivery

Private runtime files stay in `~/Library/Application Support/Decrumb` on Mac,
or `${XDG_STATE_HOME:-~/.local/state}/decrumb` on Linux,
with restrictive permissions. They never belong in Git or the application bundle.
This includes Signal keys/state, configuration, temporary pairing images and the
outbox. Signal CLI's outgoing message resend log is disabled. That flag does not
disable its incoming `msg-cache`: encrypted received envelopes are written before
acknowledgment and normally deleted after processing. Crashes or identity-trust
failures can leave them for later handling. There is no ordinary conversation
history UI/database maintained by Decrumb, but it is not a zero-storage client.

The worker retains cleaned URLs, optional sender attribution, and phone-command
replies in a **plaintext SQLite outbox** while queued and clears payloads after attempts. Pending payloads
become eligible for cleanup after 24 hours; hashed event IDs, timestamps, delivery
states and generated-note receipt metadata after 30 days. Receipts contain no
URLs, message bodies, display names or raw account identifiers. Local cleanup
runs during processing, before the worker connects, and on app bootstrap, explicit
status requests, or pausing (when the worker lock is free). Data can remain longer
while the app/worker are stopped or paused without another maintenance action.
Pause preserves valid queued notes unless discard-on-pause is enabled. Aggregate
loss counters persist separately.
SQLite secure deletion is enabled; backups and APFS may retain old data.
Local diagnostics retain only fixed error codes; upstream stderr is discarded.
There is no automatic telemetry or crash upload.


Signal CLI also retains keys, credentials, contacts, groups, profiles and protocol
state. The private folder permissions do not encrypt these files or the outbox.
Cleaned notes delivered to Note to Self have their own lifetime on Signal devices.
See [storage audit](docs/FOOTPRINT-REVIEW.md) for version-matched upstream evidence.

The queue holds up to 256 notes with at most one send every two seconds. Ambiguous
or interrupted sends become `uncertain` and are never automatically replayed.
Pre-dispatch cancellation preserves unattempted notes. Per-message helper errors
are counted without stopping subsequent processing. Queue/receive overflow is
counted, but exceptional bursts can still lose work. There is no exactly-once
or guaranteed-delivery claim.

Status reports the local worker's heartbeat and counters. A running process does
not prove uninterrupted Signal connectivity. Sent means Signal CLI acknowledged
the send, not that the phone displayed it. A real incoming message from another
contact remains the live end-to-end acceptance check.

The interface watches the content-free status file natively and uses a coarse
60-second fallback to detect a stale worker. It does not launch Python for idle
status updates. Local previews call the Swift cleaner directly. Initial setup,
settings changes and explicit controls still use the bundled Python command.

## Local diagnostics and support

On Mac, open **Diagnostics → Preview diagnostic report**, review the text, then
choose **Copy diagnostic report** if you want to share it yourself. On Pi, run
`decrumb diagnostics`. The authenticated Umbrel dashboard has the same preview
and copy controls. No support server or additional network connection is used.

The report includes app/build and dependency versions, operating-system version
(kernel version on Linux), architecture, local worker heartbeat state, and recent
error codes with their component and originating app/build. It excludes messages,
URLs, contacts, account identifiers, custom rules, paths, machine names, activity
counts, exact timestamps, raw exception text, and crash dumps. Worker heartbeat
state does not prove Signal connectivity. A missing error record does not prove
there was no crash, especially after forced termination or a storage failure.

Error history is bounded to 128 entries and less than 64 KiB, with duplicate codes
coalesced per build and UTC day. Only entries from the current UTC day and the
previous six days are retained. Cleanup runs on worker heartbeats, app/control
startup, and diagnostic preview. Files can remain longer while Decrumb is stopped.
Upgrading removes the previous rotating logs, including successful-send times.
The report omits even the coarse dates used locally for retention.

**Clear diagnostics** (or `decrumb clear-diagnostics` on Pi) removes the local
error history and old log backups. It preserves the linked account, settings,
outbox, and existing delivery/loss counters. New errors may be recorded afterward.
Clearing cannot erase reports already copied/shared or copies in system backups.


## Optional Mac CLI installation

The standalone app bundles its dependencies. A separate manual CLI installation
requires Python 3.13 or newer and a compatible, isolated signal-cli installation.
Source builds do not automatically deploy to an existing installation. Preserve
its linked account and unrelated services; do not copy account files from another
Signal installation or register a primary account.

Install `decrumb.py`, `runtime_platform.py`, `diagnostics.py`, `release.json`, **`notes.py`**,
`phone_commands.py`, and `service.py` together in the runtime's
`bin/` directory. Place `build/url-cleaner` and **`build/rules.json` beside that
helper** in the same directory. Keep the runtime directory private (mode 0700).
Use the absolute paths to Python and the isolated Signal executable on your Mac;
replace the example Signal path below:

```sh
DECRUMB_ROOT="$HOME/Library/Application Support/Decrumb"
DECRUMB_PY="$(command -v python3)"
DECRUMB_SIGNAL_CLI="/absolute/path/to/isolated/signal-cli"
"$DECRUMB_PY" "$DECRUMB_ROOT/bin/decrumb.py" init --helper "$DECRUMB_ROOT/bin/url-cleaner" \
  --signal-cli "$DECRUMB_SIGNAL_CLI"
"$DECRUMB_PY" "$DECRUMB_ROOT/bin/decrumb.py" pair
"$DECRUMB_PY" "$DECRUMB_ROOT/bin/service.py" install
"$DECRUMB_PY" "$DECRUMB_ROOT/bin/service.py" start
"$DECRUMB_PY" "$DECRUMB_ROOT/bin/decrumb.py" status
```

While CLI pairing runs, manually open the temporary `pairing.png` and scan it.
Stop the worker before `configure --mode selected --base-url example.com/news`,
then restart. `preview` reads sample text on stdin. `service.py stop` retains the
CLI login preference; the GUI's Pause also disables worker startup at next login.
Stopped LaunchAgent installations can be updated by running `install` again.

Signal CLI is unofficial and needs updates as Signal's service evolves.
Unlink only this app's linked device from your phone to revoke its account access.
The linked device is named Decrumb.

## Sources and license

- [Signal CLI JSON-RPC documentation](https://github.com/AsamK/signal-cli/blob/v0.14.8/man/signal-cli-jsonrpc.5.adoc)
- [Signal linked devices](https://support.signal.org/hc/en-us/articles/360007320551-Linked-Devices)
- [Provenance](docs/PROVENANCE.md)
- [Third-party software and release materials](docs/THIRD-PARTY.md)

AGPL-3.0-only. Preserve upstream attribution and licenses with modified source or
binaries. Signal CLI and other bundled components retain their respective licenses.
