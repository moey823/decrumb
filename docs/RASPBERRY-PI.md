# Decrumb on Raspberry Pi

Leave a Raspberry Pi powered on and online, and Decrumb saves cleaned Signal
links to Note to Self on your phone. It uses the same cleaning rules and note lifecycle
as the Mac app, with a command-line interface over SSH. There is no web server,
open control port, or Decrumb cloud account.

The Pi release is **experimental** until acceptance testing on a physical Pi.
It targets **Raspberry Pi OS 64-bit, Bookworm or newer**, Python 3.11+, and an
ARM64 Pi. A Pi 4 or Pi 5 with at least 2 GB RAM is the recommended starting point;
physical-device memory and power measurements are still pending. 32-bit OS
images and ARMv6/ARMv7 are not supported. Cleaning stops if the Pi shuts down or
loses its internet connection. It does not need a monitor attached.

## Install and connect

The current source release is **1.1.0**, build **7**. Download the matching
Linux ARM64 `.tar.gz` and `.sha256` file when available from the
[Decrumb releases](https://github.com/moey823/decrumb/releases). Transfer them to
your Pi, or download them there. Verify the checksum before extracting:

```sh
sha256sum -c Decrumb-1.1.0-7-linux-arm64.tar.gz.sha256
tar -xzf Decrumb-1.1.0-7-linux-arm64.tar.gz
sudo apt update
sudo apt install python3 qrencode libstdc++6
cd Decrumb-1.1.0-7-linux-arm64
python3 tools/install_pi.py
```

Run the installer as your **normal user**, without `sudo`. It downloads a pinned
Signal dependency directly from its provider and verifies its SHA-256 before
running it. No Java installation is required. The dependency and its community
build provenance are listed in [linux/dependencies.json](../linux/dependencies.json).
The Decrumb archive contains our source, rules, tests, and license; it does not
redistribute that community binary.

In an interactive terminal on your computer connected to the Pi over SSH:

```sh
~/.local/bin/decrumb pair
```

A QR code appears **in that terminal**. On your phone, open Signal → Settings →
Linked Devices → Link New Device and scan it. Use a second screen; you cannot
scan a QR displayed on the same phone. Enlarge the terminal if the QR wraps.
Treat the pairing QR as private. Do not redirect, log, photograph, or share it.
The temporary private PNG is deleted when pairing finishes or is cancelled.
Pairing uses the existing account as a linked device; it never registers a new
primary account. A successful pairing starts cleaning automatically.

For cleaning to start at boot and survive your SSH logout, enable the user’s
systemd services outside login sessions once:

```sh
sudo loginctl enable-linger "$USER"
```

Without this setting, the user service depends on a login session and may stop
after logout. Check after reboot with `~/.local/bin/decrumb status`.
Only the Decrumb user service is installed; no system-wide daemon or privileged
Signal process is created.

## Control it

If `~/.local/bin` is on your `PATH`, you can use `decrumb` directly.

```sh
~/.local/bin/decrumb status
~/.local/bin/decrumb pause
~/.local/bin/decrumb resume
```

Pause survives reboot on the Pi until you explicitly resume. Status reports
connection state and counts without messages, account identifiers, or links.
The worker cleans links in disappearing messages too, while preserving view-once,
spoiler, and loop exclusions. Its only automatic send destination is Note to Self.
Generated notes use the Note to Self timer and configured note-cleanup policy;
the source chat's timer is not copied.

Cleaning rules use the same JSON format as the Mac app. Write settings in a
private file outside the extracted source folder, then apply them:

```json
{"mode":"all","baseURLs":[],"excludedURLs":["https://example.com"],"rules":[]}
```

```sh
~/.local/bin/decrumb configure ~/decrumb-rules.json
printf '%s' 'https://example.org/story?utm_source=sample' | ~/.local/bin/decrumb preview
```

Preview is offline and prints the sample’s cleaned links, so only use text you
intend to display in your terminal. Applying rules discards previously queued
links and restarts an active worker. See [URL-CLEANUP.md](URL-CLEANUP.md) for the
rule schema.

Generated-note tagging, sender display, and optional scheduled removal use the
same settings as macOS. Use `decrumb notes-settings /path/to/settings.json`,
`decrumb notes` for content-free receipts, `decrumb cleanup NOTE_ID ...` to
request removal, and `decrumb clear-queue` to discard unsent links. Cleanup
requires the worker running and remains limited by Signal’s supported removal
window; it is not guaranteed secure erasure. See [NOTE-LIFECYCLE.md](NOTE-LIFECYCLE.md).

## Optional phone commands

Enable locally once:

```sh
~/.local/bin/decrumb phone-commands enable
```

Then type `/decrumb help`, `/decrumb status`, or `/decrumb clean https://example.org/?utm_source=sample`
in your Signal **Note to Self** conversation. The helper must already be running
and online when the command is sent. Commands sent while it is off are ignored.
Disable with `decrumb phone-commands disable`. This is off by default. Other
people’s chats cannot trigger commands. No shell execution, arbitrary files,
web-page fetching, or AI provider is involved.

## Updates and removal

Pi updates are manual: download and verify the newer release, extract it, and
run its `python3 tools/install_pi.py` as the same user. The installer checks the
new dependency before stopping the worker, swaps the app, and preserves Signal
pairing, rules, receipts, and pause state. It rolls back the code and
configuration if activation fails. Keep the old archive until the update works.
The Mac automatic updater does not manage the Pi installation.

To remove the installed app while keeping pairing and local data for a later
reinstall:

```sh
~/.local/bin/decrumb pause
rm ~/.config/systemd/user/decrumb.service
systemctl --user daemon-reload
rm ~/.local/bin/decrumb
rm -r ~/.local/lib/decrumb
```

Unlink Decrumb in Signal → Settings → Linked Devices if you no longer use it.
The private runtime remains in `~/.local/state/decrumb` (or
`$XDG_STATE_HOME/decrumb` when an absolute XDG state directory was configured).
It contains Signal keys, configuration, bounded logs, local receipts, and any
queued unsent links. It is never in the source archive or app installation.
Back it up only as sensitive data. Removal commands above deliberately retain it.

## Dependency and validation notes

Upstream signal-cli publishes a Linux x86_64 native build, not an official ARM64
native build. This installer pins the ARM64 community build listed by
[signal-cli’s binary-distribution documentation](https://github.com/AsamK/signal-cli/wiki/Binary-distributions):
`0.14.8+2` with libsignal `0.102.1`, requiring glibc 2.30+. The two patches and
source revisions are recorded alongside the fixed download hash. Do not replace
it with an unversioned “latest” URL. Dependency updates require review and a new
Decrumb release. Signal server changes can eventually require updates.

Offline synthetic tests cover service ownership, private files, packaging,
updates, rollback, and QR handling. ARM64 Linux container verification can prove
executable and protocol compatibility; it does not substitute for physical Pi
pairing, reboot, logout, network recovery, and long-running resource acceptance.

## Local diagnostics

Run `decrumb diagnostics` to preview a content-free report of app/dependency
versions, basic system information, local worker health, and recent error codes.
Nothing is uploaded. Review the output before sharing it yourself. Run
`decrumb clear-diagnostics` to clear error history without changing the linked
account, settings, queue, or counters. These commands also work when configuration
is broken. See [diagnostics and retention](../README.md#local-diagnostics-and-support).
