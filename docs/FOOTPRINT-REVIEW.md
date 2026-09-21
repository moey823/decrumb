# Footprint, performance and local storage review

Reviewed 2026-09-20 by parallel naming, runtime and privacy reviewers. Measurements
used the local Apple Silicon development build and synthetic offline fixtures.
No live Signal account, message, contact, key, database or runtime was read.

## Distribution size

Baseline signed development bundle before this review's small code changes:

| Component | Bytes | Decimal MB |
| --- | ---: | ---: |
| Entire app | 132,697,045 | 132.70 |
| Distribution zip | 54,839,220 | 54.84 |
| Native signal-cli 0.14.8 | 121,676,160 | 121.68 |
| Frozen Python worker/runtime | 9,400,384 | 9.40 |
| Native Swift interface | 968,448 | 0.97 |
| Swift URL cleaner | 211,856 | 0.21 |
| Bundled source/docs | 188,055 | 0.19 |
| App icon | 155,779 | 0.16 |

Signal CLI is 91.69% of the app. Its native GraalVM image includes approximately
43.17 MB of text and 78.05 MB of prebuilt runtime heap. Stripping a temporary copy
saved only 3,712 bytes; the shipped binary was not altered by that experiment.
Replacing Python could save around 7% of the bundle, but cannot turn the current
self-contained Signal client into a 5 MB utility. Excluding Signal would move that
dependency to the user. Source/notices should remain bundled.

These figures describe the app, not runtime data, installer expansion, Python's
one-file extraction directory, or full memory use. Packaging uses a pinned native
Signal executable rather than requiring a separate Java installation.

## Performance

Baseline synthetic timings before this review's fixes:

| Operation | Samples | Median wall time | Mean child CPU time |
| --- | ---: | ---: | ---: |
| Frozen worker status snapshot | 20 | 1,003 ms | 242 ms |
| Source Python status snapshot | 20 | 56.5 ms | 55.7 ms |
| Frozen worker preview | 12 | 1,028 ms | 267 ms |
| Direct Swift helper | 50 | 8.54 ms | 5.98 ms |

The original interface spawned the frozen Python snapshot every three seconds,
even while hidden or paused. At 242 ms of child CPU per invocation, that implies
about 8% of one CPU core and up to 28,800 launches per day. One-file startup and
extraction, rather than URL rewriting, dominated that cost.

Implemented in this review:

- Read the small, content-free status JSON directly in Swift; watch the containing
  directory so atomic replacement triggers updates. Validate and bound input.
- Use a 60-second timer with tolerance only as fallback for detecting a stale
  worker. Normal status updates no longer start a Python process.
- Notice configuration-file changes separately, so external changes refresh the
  interface once without restoring periodic process launches.
- Use the Swift helper directly for previews in the normal interface as well as
  demo mode, preserving the ten-second helper deadline. Bootstrap, settings
  changes and explicit controls still use Python.
- Keep the per-message helper simple: the measured 8.5 ms invocation is cheap
  relative to the two-second sending interval. No persistent helper was added.

The idle frozen worker plus its bootloader used approximately **29.4 MiB RSS**
with a synthetic fake Signal process excluded. Over 15 idle seconds it accumulated
about 0.01 seconds of CPU, below 0.1% of a core at the sampling precision. This is
not a whole-app memory or energy measurement: it excludes the GUI and real Signal
client. Signal remains running while cleaning is enabled. Quitting the interface
leaves the background cleaner active; Pause stops it.

Native status tests cover stale/dead processes, field filtering, bounded reads and
atomic replacement notifications, and print a 1,000-read fixture benchmark.
A run averaged **33.83 microseconds per native status read**, compared with about
one second for the old frozen snapshot. These are different execution paths, not
a measurement of whole-app CPU after the change.
A live connected RAM/energy measurement remains unperformed.

## Local message storage

There is no normal conversation archive maintained by Decrumb. **It is not a
zero-storage Signal client.**

| Data | Storage and lifetime |
| --- | --- |
| Original received messages | Signal CLI caches the encrypted received envelope in `msg-cache` before acknowledging receipt. Usually deleted after processing; crashes and identity-trust failures can retain it. Decrypted text is passed to Decrumb in memory. |
| Cleaned links waiting to send | Plaintext in Decrumb's SQLite outbox; at most 256 notes, each at most 8 KiB. Bodies are cleared after attempted delivery. Cancellation before dispatch preserves unattempted notes. |
| Deduplication state | Hash of source/timestamp, original timestamp and delivery state. Eligible for deletion after 30 days; original body/contact name is not retained in these rows. |
| Signal account state | Keys, credentials, contacts, groups, profiles and protocol/session state persist in Signal CLI's files and account database/WAL. |
| Long-text messages | Upstream can download a `text/x-signal-plain` attachment to a temporary file even when ordinary attachment downloading is disabled, then reconstruct the body. Normal cleanup deletes the temporary file; a hard crash can leave it. |
| Diagnostics | Local fixed error codes, deduplicated per build/UTC day; at most 128 entries and less than 64 KiB, current day plus six previous days. Pruned while active; old files may persist while stopped. Report omits dates and activity counters. Separate local heartbeat/counters remain. No automatic uploads or raw message/URL logging. Signal CLI stderr is discarded and its outgoing resend log is disabled. |
| Delivered cleaned notes | Ordinary Note to Self messages on receiving Signal devices, with their own lifetime. Deleting the source message does not retract them. |

Pending plaintext becomes eligible for cleanup after 24 hours. This review moved
cleanup to store opening, before network connection, and added lock-aware local
maintenance during app bootstrap, explicit status requests and pause. It no longer
depends exclusively on a successful Signal connection. The running worker also
cleans periodically. Pause preserves unexpired queued notes. Stopped/paused data
can remain beyond the threshold until another maintenance action; no app can
enforce a deletion deadline while the Mac is off.

Runtime files are outside Git and the bundle, in
`~/Library/Application Support/Decrumb`. Restrictive permissions are not
application-level encryption. SQLite secure deletion is enabled; filesystem
snapshots/backups can retain previous data.
Aggregate counters are separate from the 30-day per-event records.

### Version-matched upstream evidence

Reviewed public signal-cli **v0.14.8** source, matching the bundled executable:

- [Receive cache before acknowledgment and normal deletion](https://github.com/AsamK/signal-cli/blob/v0.14.8/lib/src/main/java/org/asamk/signal/manager/helper/ReceiveHelper.java#L157-L163)
  and [retry handling](https://github.com/AsamK/signal-cli/blob/v0.14.8/lib/src/main/java/org/asamk/signal/manager/helper/ReceiveHelper.java#L295-L319).
- [Encrypted-envelope cache serialization](https://github.com/AsamK/signal-cli/blob/v0.14.8/lib/src/main/java/org/asamk/signal/manager/util/MessageCacheUtils.java#L125-L132).
- [Outgoing resend-log insertion gate](https://github.com/AsamK/signal-cli/blob/v0.14.8/lib/src/main/java/org/asamk/signal/manager/storage/sendLog/MessageSendLogStore.java#L116-L136).
  Disabling this log does not disable the incoming cache.
- [Account stores](https://github.com/AsamK/signal-cli/blob/v0.14.8/lib/src/main/java/org/asamk/signal/manager/storage/AccountDatabase.java#L46-L63)
  and [SQLite WAL configuration](https://github.com/AsamK/signal-cli/blob/v0.14.8/lib/src/main/java/org/asamk/signal/manager/storage/Database.java#L93-L106).
- [Long-text download exception](https://github.com/AsamK/signal-cli/blob/v0.14.8/lib/src/main/java/org/asamk/signal/manager/helper/IncomingMessageHandler.java#L997-L1008),
  [message body reconstruction](https://github.com/AsamK/signal-cli/blob/v0.14.8/lib/src/main/java/org/asamk/signal/manager/api/MessageEnvelope.java#L137-L146),
  and [temporary-file cleanup](https://github.com/AsamK/signal-cli/blob/v0.14.8/lib/src/main/java/org/asamk/signal/manager/helper/AttachmentHelper.java#L169-L190).

Potential follow-ups requiring product choices: an explicit Clear queued links
control, discard-on-pause preference, and stronger at-rest protection for the
outbox. Those do not eliminate Signal's own required account/protocol storage.
