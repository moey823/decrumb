# Source provenance

Extracted on 2026-09-20 from a personal Signal-iOS prototype into a standalone
macOS project.

The Python worker, service controller, Swift entry point, tests and setup docs
came from the prototype's command-line tooling. The cleaner came from its
SignalServiceKit message body-range utilities. Build paths and test discovery
were adjusted so this repository is independent of that checkout.
No account state, generated binary, message database, QR image or credential was
copied into the repository.

The Swift cleaner's extraction SHA-256 is:
`d78e5393f0a4785bc69d8b72d2c26c08f81dec8781d243de87a3028137c76bf6`.
Only its documentation-reference comment was adjusted during extraction; URL
cleanup behavior was unchanged at that point. It is a snapshot of the prototype's
implementation; changes in either repository do not automatically update the
other. Subsequent Decrumb changes are described below.

The personal prototype was based on [Signal-iOS](https://github.com/signalapp/Signal-iOS)
revision `e5ea0729afc64261119ef232d4b00e8f48f53d3e`. This repository retains its
AGPLv3 license text and the extracted files' AGPL-3.0-only identifiers. Signal's
name and marks belong to their owners. `signal-cli` is a separate unofficial
client maintained at [AsamK/signal-cli](https://github.com/AsamK/signal-cli).

## Standalone desktop app work, 2026-09-20

The standalone macOS app is Decrumb. Its bundle and executable are `Decrumb.app`
and `Decrumb`; its Python entry point is `decrumb.py` and its frozen worker is
`decrumb-worker`. The bundle identifier is `com.matthew.decrumb.desktop`.
The dedicated services are `com.matthew.decrumb.link-cleaner` and
`com.matthew.decrumb.app`; private runtime files live in
`~/Library/Application Support/Decrumb`.

The extracted implementation now has local changes: versioned JSON defaults,
normalized selected rules, site exclusions, exact per-site remove/keep overrides,
preview explanations, and corrected detection of schemeless links containing
nested URLs. The extraction hash above identifies the original snapshot, not the
modified cleaner. The original default tracking lists are retained in
`rules/defaults.json`. These changes do not automatically update the personal
Signal-iOS prototype.

`swift/DecrumbURLCleaner.swift` contains the standalone cleaner.
`app/DecrumbApp.swift` adds a native SwiftUI/AppKit menu bar interface. `desktop.py`
is the local stdio interface to the existing Python worker. `tools/build_app.py`
freezes Python and bundles a pinned native signal-cli 0.14.8 arm64_sonoma binary.
See [THIRD-PARTY.md](THIRD-PARTY.md) for package hashes, source references and
public-release preparation requirements.

Source builds and offline demos do not deploy, relink, or modify existing
accounts. Development bundles are ad-hoc signed; distribution signing and
notarization are separate release steps. Current validation and remaining release
work are recorded in [VALIDATION.md](VALIDATION.md) and
[V1-READINESS.md](V1-READINESS.md).

## Raspberry Pi and phone commands, 2026-09-20

`portable_cleaner.py` implements the shared JSON rule schema in Python for Linux.
It preserves query spelling and retained fields while applying the same ordered
rules as the Swift implementation. The text detector is a separate, bounded
implementation; conformance fixtures cover supported links on both platforms.
`pi.py` and `tools/install_pi.py` provide per-user systemd controls and installation.
`phone_commands.py` adds optional, owner-to-self commands shared by both platforms.
These additions retain this repository's AGPL-3.0-only license.

The Pi archive distributes Decrumb source. Its installer downloads a separate,
checksum-pinned ARM64 signal-cli build from the provider referenced in
`linux/dependencies.json`; it does not claim that binary is an official Signal
release. Exact binary metadata and source references are recorded in the
[Raspberry Pi guide](RASPBERRY-PI.md).

## Umbrel and container dashboard, 2026-09-21

`web_server.py`, `container_dependency.py`, and `web/` add browser controls and a
subprocess supervisor around the existing worker. They are original Decrumb
additions under AGPL-3.0-only. The container retains the license, source link,
provenance, and source revision label. It uses the official multiarchitecture
Python Debian image, `qrencode`, and system libraries with their distribution
notices retained in the image.

`diagnostics.py` and the Mac, Pi, and Umbrel diagnostics controls are original
Decrumb additions under AGPL-3.0-only. They use Python's standard library for
bounded local error history and an allowlisted support report. No third-party
analytics or crash-reporting SDK is included.

The image does not redistribute signal-cli. On first start it downloads the
architecture-specific archive recorded in `container/dependencies.json`, checks
its SHA-256, and verifies the executable architecture and version. ARM64 uses the
same community build and provenance as the Pi installer; AMD64 uses the native
asset published by the signal-cli project for v0.14.8. Both are unofficial Signal
clients. The private dependency cache is separate from the image and can be
recreated without changing the linked account.

## Native Windows CLI, 2026-09-21

`windows.py` adds per-user command-line controls and background supervision.
`runtime_platform.py` supplies shared locking, process probes and subprocess
handling; `cli_common.py` shares the existing Pi settings operations. Windows
uses the existing Python cleaner with Segno QR rendering in `windows_helper.py`.
`windows_native.py` and `windows_signal.py` use pywin32 for protected runtime ACLs
and a kill-on-close Job Object around Java. All are original Decrumb additions
under AGPL-3.0-only; the privacy filters, Note-to-Self restriction and queue are
the existing shared implementation.

The experimental Windows build freezes Python using PyInstaller and includes the
official signal-cli 0.14.8 JVM distribution and Eclipse Temurin 25 x64 JRE, locked
by version, upstream URL and SHA-256 in `windows/dependencies.json`. Upstream
notices are retained. This does not change the existing Mac or Linux dependency
pins. The unsigned development ZIP is not a public release; Windows runtime,
live-pairing and corresponding-source acceptance are documented in [WINDOWS.md](WINDOWS.md).
