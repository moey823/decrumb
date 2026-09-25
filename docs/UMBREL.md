# Decrumb on Umbrel

Decrumb is a good fit for an always-on home server: incoming Signal links are
cleaned while your phone and laptop come and go. Your Umbrel must stay powered on
and online. Decrumb only sends the result to your Signal **Note to Self**.

The Umbrel edition is an **experimental community app, Decrumb 1.1.3**, for ARM64
and Intel/AMD 64-bit systems. Both container architectures pass automated tests.
The maintainer confirmed live Umbrel testing for an earlier release on 2026-09-21; see the
[validation record](VALIDATION.md#maintainer-confirmed-umbrel-testing-2026-09-21).
This is not an official Umbrel App Store listing.

## Install

1. In Umbrel's App Store, open its community app store settings.
2. Add `https://github.com/moey823/decrumb` as a community store.
3. Open the **mkships** store, install **Decrumb**, and launch it.
4. Use the app password displayed by Umbrel, then follow the pairing steps below.

Normal setup happens in the browser. You do not need SSH, a terminal, or a
separate Signal CLI installation. The proxy uses port **8857**. The image download
is about **44–45 MB**; first setup also downloads the pinned native Signal helper
(about 44 MB on ARM64 or 114 MB on AMD64, before extraction).

## Browser setup

Open Decrumb from Umbrel and unlock it with the app password displayed in its app
details. Umbrel generates this password for your installation; it is separate
from your Umbrel login. Keep both private.

On first start, Decrumb downloads and verifies a pinned Signal helper. This needs
internet access and several hundred megabytes of free disk space. Download or
validation failures appear in the dashboard with a **Retry setup** button.
Subsequent starts verify and reuse the cached helper.

Choose **Connect Signal**. On your phone, open **Signal → Settings → Linked
devices → Link a new device** and scan the private QR. Cleaning starts as soon as
linking finishes. The QR disappears after linking, cancellation, or expiry.
If you already run Decrumb on a Mac or Pi, pause that instance before using the
new one to avoid duplicate notes. Accounts are not copied between machines.

## Controls

- Clean all sites, selected sites, or no sites. Exclude sites or add exact
  parameter rules in the advanced editor. Changing cleaning rules clears pending
  links authorized under the old rules.
- Preview a link with the form's current rules. Nothing is fetched or sent, and
  the preview is not saved.
- Enable optional commands from your own Note to Self. They start off. Supported
  commands are `/decrumb help`, `/decrumb status`, and `/decrumb clean <link>`.
  No shell commands, arbitrary file access, URL fetching, or AI calls are added.
- Include sender names in generated notes; remove tracked notes manually, after
  a lifetime, or on a schedule. Removal is optional and subject to Signal's
  roughly 24-hour deletion window. Originals are never removed.
- Pause or resume cleaning. Unlike opening the Mac app, opening the dashboard
  does not resume a pause. A server pause persists across browser refreshes,
  restarts, and image updates. Closing the browser leaves the helper running.

## Data and security

The app runs as UID/GID 1000, without root privileges, extra capabilities, host
networking, or access to the Docker socket. Umbrel's login proxy remains enabled.
The dashboard additionally requires its per-install app password so other apps
on Umbrel's shared Docker network cannot read pairing codes or change controls.
Browser sessions expire after 12 hours and are stored per browser origin in
session storage, not cross-port cookies. Server restarts invalidate sessions.

The native Signal client extracts libraries into an app-private, disk-backed
temporary directory (`data/tmp`, mounted at `/tmp`). This is excluded from
backups. It avoids reserving hundreds of megabytes of RAM for the larger AMD64
native library. Allow at least 1 GB of free disk space for setup and temporary
files; message-processing memory use depends on Signal activity.

Only the proxy publishes a browser port. Do not expose it directly to the public
internet. Use your trusted home network or an authenticated encrypted connection
for remote access; the internal app speaks HTTP behind Umbrel's proxy.

Mutable state is bind-mounted under `data/state` in Umbrel's app directory:

| Path | Contents |
| --- | --- |
| `config.json` | Linked account identifier and saved settings |
| `signal-cli/` | Linked-device keys and Signal protocol state |
| `outbox.sqlite3` | Bounded delivery queue and content-free note receipts |
| `dependency/` | Verified, replaceable Signal helper download |
| `pairing.png` | Temporary private linking code, removed after pairing |
| `status.json`, `worker.log`, `diagnostics.lock` | Content-free status and bounded local error codes; old rotating log backups are removed on upgrade |

Decrumb does not keep a chat-history archive. Pending cleaned notes can exist in
the local delivery queue; the shared worker's retention and privacy rules still
apply. The dashboard never displays message bodies, contacts, account
identifiers, keys, or raw logs. The authenticated Diagnostics controls preview a
content-free report and clear local error history without restarting the worker.
Nothing is uploaded automatically. Private preview text stays in memory until the page
is cleared or locked. No analytics, remote fonts, or CDN scripts are loaded.

Updates replace the image and preserve `data/state`. Use Umbrel's app update
control; there is no self-updating code inside the container. Account state and
queued messages are sensitive: protect backups. Removing the app's saved data
removes its keys and requires pairing again. Never mount the same account state
into two running instances.

## Build and verify

```sh
docker build -f container/Dockerfile -t decrumb-local .
python3 build.py
python3 -B -m unittest discover -s tests -p 'test_*.py' -v
```

The `Umbrel container` workflow builds natively on ARM64 and AMD64, verifies the
real helper with an empty account, and runs synthetic browser pairing,
cancellation, automatic startup, settings, preview, pause/resume, and persistent
state tests. Publishing requires a manual workflow dispatch with `publish` enabled, after
both architectures pass. It produces immutable commit tags and one
multiarchitecture manifest. The store is updated separately to pin that tested
manifest's digest; preparing an image does not deploy it.

The container uses Python's standard library HTTP server with bounded request
sizes and concurrency, authenticated JSON APIs, same-origin mutations, no CORS,
a restrictive content security policy, and content-free errors. It is intended
for a private server behind Umbrel's authentication proxy, not public hosting.
Native Signal pairing and delivery are covered by the maintainer's separate
live-test confirmation; synthetic tests do not establish that result.

Decrumb 1.1.3 uses source commit
`7ef5e4ae6b50b6839e18a4d08ba622f63857e81a`, with multiarchitecture digest
`sha256:e0bad5861cb0c57c54dcbe0f3210971329d4235ded08a6ab7f62e93be16bf3c9`.
The [native container build, tests and publication](https://github.com/moey823/decrumb/actions/runs/36164404884)
passed on ARM64 and AMD64. The store pins this tested digest. Anonymous registry
downloads verified the index, both architecture manifests and their configuration
digests; both images carry the shared `1.1.3` version and exact source revision
labels. Link cleaning and server controls are unchanged from 1.1.2; this release's
updater and Quit behavior changes apply to the Mac app.

Decrumb 1.1.2 used source commit
`b03d5a4701ab0b5e62a521ebca2513254a5f678e`, with multiarchitecture digest
`sha256:bd41c8c9b61a9e5f0171e4d2a3af0fbddc5fecaa5c4b67225f46dafe0e7b54ce`.
The [native container build, tests and publication](https://github.com/moey823/decrumb/actions/runs/36153723444)
passed on ARM64 and AMD64. Anonymous registry
downloads verified the manifest, both architectures and their source/version
labels. Both images carry the shared `1.1.2` release label. This release cleans
links from disappearing messages and accepts phone commands when Note to Self
has a disappearing-message timer. Generated notes use the Note to Self timer
and configured cleanup policy, not the source chat's timer. View-once content
and spoilers remain excluded.

Decrumb 1.1.1 used source commit
`318ac635900377a9f1a2e79c6db622cddb3639c1`, with multiarchitecture digest
`sha256:ebc0162421a5ee7d153211159e326e9088406e0b517ff55f52a1fde39cd94f72`.
The [native container build, tests and publication](https://github.com/moey823/decrumb/actions/runs/36140653704)
passed on ARM64 and AMD64. Both images carry the shared `1.1.1` release label.
That release added X/Twitter share-link cleanup and the running version/build
in the optional `/decrumb status` reply.

Decrumb 1.1.0 used source commit
`27c41e493a462d9d201be15b5e688b8fbe83b821`, with multiarchitecture digest
`sha256:d116eb7708246447df10cd945912744f40aa821ffbbdf17c56f02394b7289193`.
The [native container build, tests and publication](https://github.com/moey823/decrumb/actions/runs/35631881616)
passed on ARM64 and AMD64. Both images carry the shared `1.1.0` release label.

The previous Decrumb 1.0.0 release used the image built from source commit
`dcd4195c379fd0585f82b54f06db8d6e8c000385`, with multiarchitecture digest
`sha256:f49c757583e2f279af1680f34aca719b1d02c6a6822b60caab1e56962f6e728f`.
The [native container checks](https://github.com/moey823/decrumb/actions/runs/35616089916)
passed on both architectures. Anonymous manifest downloads confirmed that the
images are public. Browser tests covered login, preview, saved settings, logout,
and layouts at 375, 768, and 1280 pixels. No real account was linked or moved
during these tests.

All platforms share the release in `release.json`. Umbrel displays the equivalent
SemVer string `1.1.3`; Mac, Pi and Windows use version `1.1.3`, build `10`. The first
Umbrel preview was labelled `0.1.0`; that historical tag remains available, but
current releases use the shared Decrumb version. Each new release pins its tested
container image while preserving existing account data.
