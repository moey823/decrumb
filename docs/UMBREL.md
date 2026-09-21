# Decrumb on Umbrel

Decrumb is a good fit for an always-on home server: incoming Signal links are
cleaned while your phone and laptop come and go. Your Umbrel must stay powered on
and online. Decrumb only sends the result to your Signal **Note to Self**.

The Umbrel edition is experimental. The browser client and container build are
being validated for ARM64 and Intel/AMD 64-bit systems. Installation instructions
and the pinned community-store package will be added once the public image passes
both architecture checks. This is not an official Umbrel App Store listing.

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
| `status.json`, `worker.log*` | Content-free status and rotating diagnostics |

Decrumb does not keep a chat-history archive. Pending cleaned notes can exist in
the local delivery queue; the shared worker's retention and privacy rules still
apply. The dashboard never displays message bodies, contacts, account
identifiers, keys, or logs. Private preview text stays in memory until the page
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
state tests. Publishing is a manual workflow dispatch on `main`, after both
architectures pass. It produces immutable commit tags and one multiarchitecture
manifest; community-store releases pin that manifest's digest.

The container uses Python's standard library HTTP server with bounded request
sizes and concurrency, authenticated JSON APIs, same-origin mutations, no CORS,
a restrictive content security policy, and content-free errors. It is intended
for a private server behind Umbrel's authentication proxy, not public hosting.
Native Signal pairing and delivery on an actual Umbrel installation remain a
separate acceptance check; synthetic tests do not establish that result.
