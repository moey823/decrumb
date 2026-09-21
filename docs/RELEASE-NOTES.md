# Decrumb release notes

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
