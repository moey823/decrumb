# Decrumb release notes

## 1.1.1 — X/Twitter link cleanup and status version (build 8)

- Removes the `s` and `t` share parameters from X/Twitter links using the shared
  cleaning rules, including links to posts.
- Includes the running version and build number in the optional
  `/decrumb status` reply, for example `Version: 1.1.1 (build 8)`.

Published September 25, 2026. The signed, notarized Mac app passed packaged smoke,
signed update acceptance and downloaded-artifact checks. Mac **Check for Updates**
now offers build 8 through the verified signed feed. The matching Pi archive and
tested Umbrel image are also published; Windows remains a source-build preview. See
[distribution status](DISTRIBUTION.md#111-xtwitter-link-cleanup-and-status-version).

## 1.1.0 — native Windows CLI (build 7)

- Adds an experimental native Windows x64 CLI with terminal QR pairing, hidden
  background cleaning, pause/resume, and optional startup at login.
- Includes rule previews/import/export, note controls, optional phone commands,
  and content-free diagnostics. Python, Java and the pinned Signal client are
  included in the Windows development bundle.
- Protects Windows account state with per-user ACLs and contains Signal child
  processes so stopping or crashing the worker releases the runtime.
- Mac, Pi, Umbrel and Windows use one version: **1.1.0**, build **7**. Shared
  privacy filters, duplicate protection and Note-to-Self-only sending are unchanged.

Published with a signed, notarized Mac app and update, matching Pi installer,
and tested Umbrel image. Existing v1/RC6 Mac users can update to build 7.
Windows is an unsigned source-build preview pending its public-release checks,
including live pairing and sleep/wake validation. See
[distribution status](DISTRIBUTION.md).

## 1.0.0 — first stable release

V1 promotes the tested RC6 build with no changes to the app or release files.
If you have RC6 (build 6), you already have v1. Older Mac installations can use
Check for Updates. Your Signal connection and settings are preserved.

The release includes automatic link cleaning to Note to Self, editable rules,
optional phone commands, note removal controls, signed Mac updates, and private
local diagnostics. No automatic telemetry or hosted support service was added.
Pi and Umbrel editions remain experimental.

## 1.0.0 RC6 — local diagnostics

Troubleshooting now works without automatic telemetry or a support server.

- Preview a diagnostic report and copy it only when you choose to share it.
  Available in the Mac app, Pi command line, and authenticated Umbrel dashboard.
- Reports include versions, basic system information, local worker health, and
  recent error codes. They exclude messages, links, contacts, account details,
  cleaning rules, activity counts, and exact event times.
- Connection, cleaner, storage, and delivery failures have distinct error codes.
- Successful link processing no longer writes timed log entries. Existing
  rotating logs are removed when the updated app or worker starts.
- Local error history is limited to 128 entries from seven UTC calendar days.
  Clear diagnostics at any time without changing your Signal connection,
  settings, queued links, or notes. Cleanup runs while the app is active.

No analytics SDK, automatic crash upload, or new hosted service was added.

RC6 remains a prerelease. Mac requires Apple silicon and macOS 26.4 or later.
Pi and Umbrel remain experimental; physical-device and live Signal acceptance
are separate from synthetic regression checks.
