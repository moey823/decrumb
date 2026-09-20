# Third-party software

Decrumb is AGPL-3.0-only. The app includes the Decrumb source snapshot under
Contents/Resources/Source. Extraction history is in PROVENANCE.md.

## Signal CLI 0.14.8

GPL-3.0-or-later. Upstream: https://github.com/AsamK/signal-cli/tree/v0.14.8
Source archive: https://github.com/AsamK/signal-cli/archive/refs/tags/v0.14.8.tar.gz
SHA-256: acc8d89463b5cdce2cf81ad00e91caf5aec37aab2d5f57d722139f254c0fd816

The native Apple Silicon executable is extracted from Homebrew's arm64_sonoma
bottle. SHA-256: 3d77c18866fca4366128b2e716c5cffc63ae937af65172e197594d0802faddea
Build recipe: https://github.com/Homebrew/homebrew-core/blob/87b31c623462c05a194d2d73a964e25cfe1ab9a0/Formula/s/signal-cli.rb
Includes libsignal v0.102.1: https://github.com/signalapp/libsignal/tree/v0.102.1

## Python and freezing tool

Python is included by PyInstaller. Python uses the PSF license and includes
third-party components such as SQLite and OpenSSL; preserve their notices.
https://docs.python.org/3/license.html

PyInstaller 6.22.3 uses GPLv2-or-later with its bootloader exception.
https://pyinstaller.org/en/v6.22.3/license.html

## Release preparation

This build is a local development artifact. Before public distribution, prepare
complete corresponding source/build materials for bundled copyleft components
and all required third-party notices; a source URL alone is not the release
compliance package. Developer ID signing, notarization, and testing on the claimed
minimum macOS version are also release tasks. No public upload occurs in build.py.
