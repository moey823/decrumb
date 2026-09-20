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
