# Third-party software and release materials

Decrumb is AGPL-3.0-only. Its app bundles a source snapshot under
`Contents/Resources/Source`; [PROVENANCE.md](PROVENANCE.md) records the original
extraction. A production release also distributes a versioned source ZIP beside
the DMG. Keep both downloadable. The app contains the material manifest and
license/notice files; the larger upstream source archives belong in the companion
ZIP, rather than every installed copy of the app.

## Bundled components

| Component | Pinned version | Source and license evidence |
| --- | --- | --- |
| signal-cli | 0.14.8 | [Upstream source](https://github.com/AsamK/signal-cli/tree/v0.14.8), GPL-3.0-or-later; exact Homebrew bottle build recipe retained. |
| Signal libsignal | 0.102.1 | [Upstream source](https://github.com/signalapp/libsignal/tree/v0.102.1), AGPL-3.0; upstream file-level exceptions/notices retained. |
| Turasa Signal service modules | 2.15.3_unofficial_153 | [Tagged upstream source](https://github.com/Turasa/libsignal-service-java/tree/v2.15.3_unofficial_153), GPL-3.0; matching published JVM source artifacts also retained. |
| JVM dependency libraries | Versions in the 0.14.8 upstream distribution | All 79 upstream JARs are inventoried. Matching public source JARs and POMs cover 76 external artifacts; signal-cli, libsignal-cli and libsignal-client are covered by full source archives. JAR license/NOTICE files are preserved. |
| Rust/native libsignal dependencies | Versions and checksums in the pinned Cargo.lock | The complete locked workspace dependency source set is included as a conservative superset, including pinned Signal Boring/SPQR repositories and the exact Google BoringSSL submodule. |
| GraalVM native-image runtime / Labs OpenJDK | 25.3.4.1 / jvmci-25.3-b22 | [Historical Homebrew recipe](https://github.com/Homebrew/homebrew-core/blob/87b31c623462c05a194d2d73a964e25cfe1ab9a0/Formula/g/graalvm.rb), both source archives and their notices; GPL-2.0 with Classpath exception and component-specific notices. |
| CPython | 3.14.6 | [Official source release](https://www.python.org/ftp/python/3.14.6/), PSF/Python licenses and bundled component notices. |
| Frozen Python native libraries | mpdecimal 4.0.1, OpenSSL 3.6.3, Zstandard 1.5.7, XZ 5.8.3, SQLite 3.53.4 | Exact upstream archives and installed Homebrew recipes; BSD, Apache, public-domain and other file-specific notices are retained. The producer checks these against the actual frozen-worker native inventory. |
| PyInstaller | 6.22.3 | [Upstream license and bootloader exception](https://pyinstaller.org/en/v6.22.3/license.html); source and license are included for transparency. The exception permits distribution of frozen applications without imposing PyInstaller's GPL on them. It does not replace the licenses of bundled dependencies. |

The authoritative hashes and URLs are in
[`tools/release-dependencies.json`](../tools/release-dependencies.json). The
Apple Silicon signal-cli executable is extracted from the Homebrew
`arm64_sonoma` bottle with SHA-256
`3d77c18866fca4366128b2e716c5cffc63ae937af65172e197594d0802faddea`.
Its [build recipe](https://github.com/Homebrew/homebrew-core/blob/87b31c623462c05a194d2d73a964e25cfe1ab9a0/Formula/s/signal-cli.rb)
pins the signal-cli and libsignal source archive checksums.

## Prepare a release

First create the frozen worker with the normal local build, so its native-library
inventory exists. After source edits are complete, collect materials for the
intended release version and build number:

```sh
python3 tools/prepare_release_materials.py --version 0.1.0 --build 1
```

The producer downloads public upstream source archives and metadata into ignored
`build/release-source-cache/`, verifies pinned checksums, and writes the release
materials under ignored `build/release-materials/`. `--offline` repeats validation
using an already populated cache. No Signal account, message, pairing, or runtime
files are read. Local build paths are omitted from the exported native inventory.

The material manifest binds its contents to the app version/build, dependency
lock, build-tool requirements, Python version, pinned signal-cli bottle, and a
deterministic path/hash inventory of Decrumb's bundled source. Its roles are
`source`, `notice`, `inventory`, `build_recipe`, and `release`. Every listed file
has a SHA-256 checksum. The production packager checks these inputs again, bundles
the manifest and notices, and puts the full materials in the companion source ZIP.
Rerun preparation after changing source, dependencies, or the release number.

An incomplete download, checksum mismatch, missing source mapping, changed source,
or unrecognized frozen native library yields a `blocked` manifest and a nonzero
exit. There is no override to declare incomplete materials ready. The production
builder rejects a blocked or stale manifest. Preparation does not publish files,
sign an application, or notarize it.

## What the coverage check establishes

The source package intentionally includes more than the final executable uses.
The full official JVM distribution supplies a concrete version inventory; the
Homebrew native build uses the same signal-cli source and replaces libsignal-client
with its pinned local build. The entire libsignal Cargo workspace is included to
avoid omitting dependencies used by target-specific native compilation. These
inventories are source coverage evidence, not a claim every listed class or crate
is linked into the shipped binary.

Original source archives, build recipes, crate lockfile/checksums, source JARs,
POMs, and original license/notice texts are retained without rewriting upstream
licenses. JVM file-level copyright/license comments, inherited POM license
declarations, and pinned standard license texts are also included in the app's
notices. Source comments and Cargo `license`/`license-file` declarations remain
in the complete archive even where no separately named license file is present.
The material check is a reproducible engineering check of this pinned dependency
set, not a legal certification or a promise of a byte-for-byte reproducible
Homebrew build. Dependency updates require updating and reviewing the coverage
lock. Signing, notarization, minimum-macOS testing, and real-device acceptance
remain separate release checks.

## Sparkle updater

The native app embeds official Sparkle **2.10.0**. The release distribution SHA-256
is `c2bf58aa8387266ac179357b1415d6f2635f044da8be41042af32425dae6da0c`; its corresponding
source archive SHA-256 is `cf43af1f26a921a8dc0be80834b9c3038bea5fd645708d26375126cbc57c316b`.
The original LICENSE covers Sparkle's MIT terms and its external components,
including BSD-licensed binary-diff code and public-domain Ed25519 code. The app
bundles this text unchanged and the release collector includes the full pinned
source archive with its original notices. The framework's nested installer,
updater and downloader executables are signed inside-out using Decrumb's release
identity before the outer app is notarized.

Upstream: <https://github.com/sparkle-project/Sparkle/releases/tag/2.10.0>.
