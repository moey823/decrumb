# Decrumb for Windows

Decrumb **1.1.0**, build **7**, uses the same release version as Mac, Pi and Umbrel.
Experimental native Windows x64 CLI for technical users. Windows 11 on Intel/AMD
is the initial target; Windows on ARM is not validated. The development bundle
is unsigned and is not a published Windows release. Mac, Pi and Umbrel release
status does not imply Windows acceptance.

Decrumb links as an additional Signal device and cleans incoming links into
**Note to Self**. Your PC must stay awake, online and signed in. No administrator
rights, WSL, Docker, separate Python/Java installation or browser are required
for the packaged edition. A private Java runtime and signal-cli 0.14.8 are included.
There is no local HTTP server and no AI provider.

## Setup

Extract the entire `Decrumb` folder to its final location, for example
`C:\Users\you\Apps\Decrumb`. Keep every file, including `_internal`, `jre` and
`signal-cli`. Open PowerShell in that folder:

```powershell
.\decrumb.exe setup
```

Scan the terminal QR from Signal on your phone under **Settings > Linked devices >
Link a new device**. Do not redirect, record or share the pairing screen. The QR
expires and its temporary image is removed after linking or cancellation. Re-run
`pair` if it expires. An existing linked account is recovered without registering
or replacing your phone's primary account. Pause any Decrumb instance on another
machine before switching, to avoid duplicate notes.

After pairing, cleaning starts in the background. You can close PowerShell.
Startup at login is optional:

```powershell
.\decrumb.exe setup --start-at-login
# Or change the preference later:
.\decrumb.exe start-at-login enable
.\decrumb.exe start-at-login disable
```

This uses only the current user's `Decrumb` entry in the Windows Run registry key.
Windows Startup Apps can disable or delay it. This is a user-session worker, not
a Windows system service; it does not run before login or after signing out.

## Commands

```powershell
.\decrumb.exe status
.\decrumb.exe pause
.\decrumb.exe resume
.\decrumb.exe pair
.\decrumb.exe run                         # foreground; Ctrl+C stops it
.\decrumb.exe diagnostics                 # content-free report; nothing uploaded
.\decrumb.exe clear-diagnostics
.\decrumb.exe notes
.\decrumb.exe cleanup decrumb_example     # use an actual ID from the notes command
.\decrumb.exe clear-queue
.\decrumb.exe phone-commands enable       # optional; off by default
.\decrumb.exe phone-commands disable
```

Pause persists through login and restart. Resume starts a hidden worker without
changing the startup preference. `run` explicitly resumes in the current terminal.
The background worker retries connection failures every 30 seconds. Status and
diagnostics distinguish a connecting/error state from a confirmed running worker.

Export, edit and import cleaning rules:

```powershell
.\decrumb.exe export-rules | Set-Content -Encoding utf8 rules.json
.\decrumb.exe configure rules.json
'https://example.com/article?utm_source=share&id=42' | .\decrumb.exe preview
.\decrumb.exe notes-settings note-settings.json
```

PowerShell 7 uses UTF-8 for native pipelines. In Windows PowerShell 5.1, set
`$OutputEncoding = [System.Text.UTF8Encoding]::new()` before piping non-ASCII text
to preview. Rule imports accept UTF-8 JSON, including the BOM produced by Windows
PowerShell. Rule exports contain no account state. See [URL-CLEANUP.md](URL-CLEANUP.md)
and [NOTE-LIFECYCLE.md](NOTE-LIFECYCLE.md) for the settings schemas. Preview
uses local rules and never fetches the submitted URL.

## Private state and shutdown

All keys, configuration, queue databases, pairing images, diagnostics and Java
temporary files live under `%LOCALAPPDATA%\Decrumb`, separately from the program.
Setup applies a protected Windows ACL granting access only to your user and SYSTEM;
new files inherit that protection. A filesystem supporting Windows ACLs is required.
Runtime links/junctions and overlapping code/state paths are rejected. Do not copy
this state into the source repository or share it in a bug report.

Windows byte-range locks prevent concurrent workers and pairing. Pause requests a
graceful stop through the private runtime directory and waits for the worker to
release its locks. The Signal bridge contains Java in a kill-on-close Windows Job
Object, so terminating the bridge also stops its child processes. The existing
delivery queue treats interrupted sends as uncertain and does not resend them.
Disappearing messages, view-once content and spoilers remain excluded; automated
sends remain restricted to Note to Self.

## Update and removal

Updates are manual for this first edition:

1. Run `pause` and `start-at-login disable` using the old copy.
2. Extract the complete new bundle into its final folder.
3. Run `setup` from the new folder; add `--start-at-login` if wanted.

Setup preserves the linked account, rules, queue and receipts and refreshes the
program paths. It starts cleaning after recovering the account. Never run setup
against the same state from two copies at once.

To remove the app, pause it, disable startup, then delete its extracted folder.
Private state remains until you deliberately delete `%LOCALAPPDATA%\Decrumb`.
Unlink **Decrumb** in Signal's Linked devices if you no longer use it. Deleting
local state requires pairing again; it does not delete already-delivered notes.

## Build and validation

Build on Windows x64 with Python 3.13, in an isolated environment:

```powershell
py -3.13 -m venv build\windows-tooling
.\build\windows-tooling\Scripts\python.exe -m pip install -r tools\requirements-build.txt -r windows\requirements.txt
.\build\windows-tooling\Scripts\python.exe build.py --windows
.\build\windows-tooling\Scripts\python.exe tools\run_windows_tests.py
.\build\windows-tooling\Scripts\python.exe tools\smoke_windows.py --bundle build\windows\Decrumb
```

The build downloads only the checksum-pinned Java and Signal archives from
`windows/dependencies.json`, rejects unsafe archive entries, retains their notices,
and freezes Python with PyInstaller. Outputs are under ignored `build/windows/`:
the runnable `Decrumb` folder, a versioned ZIP, its SHA-256, and a file manifest.
The ZIP includes Decrumb source and license notices. Builds and tests never open an
existing account. The Windows CI job runs synthetic tests, builds the executables
and probes the actual Signal dependency against an isolated empty account directory.

Native tests cover Windows ACL inheritance, byte-range locks, hidden background
startup, graceful stop, duplicate suppression, privacy exclusions, and Java child
containment after an abrupt bridge exit. Shared rule/filter/queue tests run too.
A live Windows pairing and sleep/wake test is still required before declaring a
supported public Windows release. Signing, a tested OS matrix, and corresponding
source/notice review for the Windows Java/JNI bundle are separate release gates.

Dependencies: [signal-cli 0.14.8](https://github.com/AsamK/signal-cli/tree/v0.14.8),
[Eclipse Temurin 25](https://github.com/adoptium/temurin25-binaries),
[Segno](https://github.com/heuer/segno), [pywin32](https://github.com/mhammond/pywin32).
Signal CLI is an unofficial Signal client. Decrumb retains AGPL-3.0-only; Java
and helper dependencies retain their respective licenses. See [PROVENANCE.md](PROVENANCE.md).
