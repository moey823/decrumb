# Decrumb macOS app

Accepted direction, 2026-09-20: a native menu bar app with QR onboarding,
bundled dependencies, editable URL rules, local previews, and background controls.
The CLI remains available for troubleshooting. Building the app does not deploy
to an existing account.

The app bundle and executable are `Decrumb.app` and `Decrumb`. The Python module
is `decrumb.py`, the frozen helper is `decrumb-worker`, and the bundle identifier
is `com.matthew.decrumb.desktop`. Its dedicated LaunchAgents use
`com.matthew.decrumb.link-cleaner` and `com.matthew.decrumb.app`.

## Architecture

- SwiftUI/AppKit owns windows, menu bar, onboarding, settings, and local previews.
- The existing Python worker owns the Signal connection and durable outbox.
- A frozen worker executable includes Python; a pinned native signal-cli binary
  and the Swift cleaner live inside the app bundle.
- Per-user configuration, keys, QR images and databases live in
  `~/Library/Application Support/Decrumb`. App upgrades preserve that directory.
- The worker can run through its dedicated LaunchAgent independently of an open
  window. Linking starts cleaning automatically; opening the app starts an
  linked cleaner without restarting an already running service. Pause lasts until
  the app is reopened or Resume cleaning is chosen. Startup is blocked during an unfinished
  update, and failures offer Retry connection. Start at login remains optional.
- UI configuration goes through a narrow local command interface, never a port.
  Account identifiers and received messages never enter UI diagnostic output.
  Diagnostics provides a local report preview, explicit copy, and history clearing.
  No reports are sent automatically; the report uses an explicit field allowlist.
- Routine status updates watch the content-free status file in Swift. Previews
  invoke the Swift helper directly; neither operation launches Python.

## Rules

Built-in rules are versioned JSON bundled with the cleaner. User settings hold
selected sites, excluded sites, and site-specific exact parameter names to remove
or preserve. Matching is case-insensitive for hosts and parameter names. Site
paths use boundaries. Precedence: protected signatures, excluded sites, mode/site
selection, explicit preserve, explicit remove plus built-in rules. Unknown rule
formats fail closed. No downloaded rules, regex execution, redirects or URL fetches.

Preview runs locally with the current unsaved settings and shows the original,
result and removed parameter names. It never sends a Signal message or saves the
sample. Import/export is for rules only, with no account or runtime data.

## Delivery and privacy

Preserve Note to Self-only delivery, skip protected/private message types, avoid
replaying ambiguous sends, retain fixed content-free logs, and clear attempted
payloads. Fix pre-dispatch cancellation, make helper errors per-message failures,
and expose durable loss counters. Status must work when the helper is broken.
Queued links are plaintext locally. Cleanup must run before network initialization
and during local lifecycle operations; paused/offline retention can exceed the
nominal age until maintenance runs. Signal CLI's separate receive cache and
long-text temporary downloads are documented explicitly.

## Generated notes

New notes contain a random searchable Decrumb code and an optional sanitized
sender display name. A separate, content-free receipt ledger binds the actual
successful send timestamp to the linked account. Only those receipts authorize
removal requests; matching text in a chat never does. The GUI supports individual
and bulk requests, per-note lifetimes and periodic sweeps. Scheduling runs in the
existing worker without another daemon or periodic GUI subprocess. See
[NOTE-LIFECYCLE.md](NOTE-LIFECYCLE.md) for options, retention and Signal limits.

Pause suspends automatic cleanup. Manual removal while paused uses a bounded
one-shot Signal connection with no receive subscription and attempts up to three
queued requests. Remaining work can be retried or drained by the resumed worker.
Clear queued links and discard-on-pause affect only local unsent payloads.

## Packaging and validation

Build the helper, compile the GUI, freeze the worker, embed verified signal-cli,
copy notices and source references, and sign the resulting bundle. Development
builds use ad-hoc signing; public distribution requires Developer ID signing and
notarization. Test against synthetic fixtures and an isolated demo UI; do not
access the live account to verify an app build. Confirm supported OS versions from
all bundled binaries before claiming a release minimum.
