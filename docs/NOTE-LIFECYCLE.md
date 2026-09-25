# Decrumb notes and cleanup

Decrumb sends cleaned links only to Signal's **Note to Self** conversation. Each
generated note identifies Decrumb, includes a searchable code such as
`#decrumb_7f12a096`, and can include the original sender's display name. The code
helps a person find a note in Signal. It is **not permission to delete a message**.

## Controls and defaults

| Control | Default | Behavior |
| --- | --- | --- |
| Include sender | On | Include an available display name in the generated note. Do not fall back to a raw phone number or account identifier. |
| Cleanup policy | Manual | New notes have no deadline. Existing note deadlines continue; choose Keep on a note to cancel its deadline. |
| Default note lifetime | Optional | New notes receive a deadline 1, 6, 12, or 23 hours after their acknowledged send time. A note's individual lifetime can also be changed. |
| Periodic cleanup | Optional | Request removal of eligible tracked notes at a sweep every 1, 6, or 12 hours. |
| Discard queued links on pause | Off | Pausing preserves unattempted queued notes unless this option is enabled. |
| Clear queued links | Manual action | Discard local notes that have not been attempted. This does not remove notes already sent to Signal. |

Manual, lifetime, and periodic cleanup are alternative default policies. Changing
the default lifetime affects newly sent notes; it does not replace or remove
existing individual deadlines. Choosing **Keep** on a note cancels that note's
deadline and exempts it from periodic sweeps. Changing the periodic policy changes
the sweep plan for notes without individual deadlines or a Keep preference.
Saving a policy configures cleanup work; it does not confirm removal from any device.
Automatic cleanup requires Decrumb's worker to run with Signal connectivity.
Pausing the worker also pauses its automatic cleanup. A powered-off, sleeping,
disconnected, or paused Mac can miss a scheduled cleanup window.

An explicit manual removal action while paused makes a bounded attempt of up to
three queued requests. Additional requests may remain queued. Use the action
again or resume the worker to continue; the action does not silently turn on the
receiver or change the pause preference.

Sender attribution is part of the generated note's content. It is a display name,
not verified identity. Normalize control characters and bound its length so it
cannot add misleading note fields. When no suitable name is available, omit the
attribution. Exclusions for view-once content, spoilers,
edits, outbound/synced messages, and Note to Self continue to apply before note
generation.

## What can be removed

Decrumb must record a successful send's Signal timestamp before it can later
identify that generated note for cleanup. Removal is restricted to this local
receipt allowlist and the currently linked account. Receipts bind the original
send timestamp to a hash of the linked account identity. A receipt belonging to
another account cannot authorize a removal request.

Never discover deletion targets by searching for `Decrumb`, `Clean link`, a URL,
sender text, or a `#decrumb_` code. Someone can type or copy those strings into a
personal note. A visible tag alone cannot prove that Decrumb generated a message.
Never accept arbitrary target timestamps, contacts, groups, or recipient lists
from the UI. Cleanup always targets Note to Self.

Only notes created after receipt tracking was introduced can be managed this
way. Older generated notes and sends with an ambiguous or missing acknowledgement
have no trustworthy cleanup receipt. They may require manual cleanup in Signal.
Do not guess timestamps or retry an ambiguous send merely to obtain a receipt.

## Signal behavior and limits

The pinned signal-cli 0.14.8 API is `remoteDelete`, with `account`,
`noteToSelf: true`, and `targetTimestamp` set to the **original send response's**
timestamp. No recipient or group parameters are needed. The removal command's
response has its own new timestamp and ordinary send-result entries. That
acknowledgement is evidence that the request was sent, not proof that another
device applied it.

Signal documents deletion for everyone as best effort for messages sent within
the previous **24 hours**. Decrumb uses that supported window and limits optional
lifetimes to 23 hours to leave time for dispatch and retries. A missed window must
be shown honestly; an expired receipt must not become a claim of successful
deletion. Current iOS has an internal exception when receiving a deletion authored
by the local account, but Decrumb must not depend on this undocumented behavior
for older notes or cross-device guarantees.

A remote deletion can leave a **message deleted** marker in the conversation.
It does not promise an empty conversation, deletion of quoted replies, removal
from backups, or erasure of copies. Use wording such as **Request removal** and
distinguish a requested operation, an unconfirmed operation, and a note outside
the supported window. Do not label a transport acknowledgement as confirmed
device-wide removal.

signal-cli 0.14.8 does not expose a per-message expiration argument or the
separate Signal *delete for me* synchronization mechanism. Its Note to Self send
path inherits the conversation's disappearing-message timer. Decrumb must not
change that conversation-wide timer to implement its own note lifetimes, because
doing so would affect unrelated personal notes.

Links in incoming disappearing messages are cleaned using the same rules as other
incoming links. Their generated notes follow the Note to Self timer and Decrumb's
configured note-cleanup policy; the source chat's timer is not copied. Authenticated
phone commands also work when Note to Self has a disappearing-message timer enabled.

## Local storage and privacy

Pending note payloads are plaintext in the protected local SQLite outbox. They
contain the cleaned URL, Decrumb code, and sender display name when enabled.
The payload is cleared after an attempted send, local cancellation, or expiry.
Pre-dispatch cancellation preserves an unattempted payload. Clearing queued links
or opting to discard them on pause removes those pending payloads without
requesting deletion of anything already in Signal.

The cleanup ledger retains only the metadata needed for targeted removal and
status: account binding, original send timestamp, note code, scheduling data,
and cleanup state. It must not retain URLs, original message bodies, sender
display names, or raw contact/account identifiers. Note codes and timestamps
still reveal that a generated note existed. The ledger retains metadata for
30 days for bounded status reporting, with expiry applied when Decrumb runs.
That retention does not extend Signal's supported removal window.

Cleanup of local stale outbox/receipt data must work without a successful Signal
connection. Run it during local maintenance and worker initialization as well as
normal operation, with the same lock used by the worker. No process can enforce
a disk-deletion deadline while the Mac is off. Describe retention as cleanup when
Decrumb next runs, and preserve the existing warning that filesystem snapshots
and backups may retain prior data.

These local policies do not erase Signal's linked-device keys, contacts, groups,
protocol databases, encrypted receive cache, or the copies delivered to the
user's other Signal devices. Preserve those account files during pause, rule
changes, and note cleanup. Logs and diagnostics remain content-free.

## Verified upstream references

- [signal-cli 0.14.8 remoteDelete command](https://github.com/AsamK/signal-cli/blob/v0.14.8/src/main/java/org/asamk/signal/commands/RemoteDeleteCommand.java#L25-L62)
- [signal-cli send/removal response format](https://github.com/AsamK/signal-cli/blob/v0.14.8/src/main/java/org/asamk/signal/util/SendMessageResultUtils.java#L42-L57)
- [Note to Self inherits its contact expiration timer](https://github.com/AsamK/signal-cli/blob/v0.14.8/lib/src/main/java/org/asamk/signal/manager/helper/SendHelper.java#L200-L209)
- [Signal's documented deletion window and best-effort behavior](https://support.signal.org/hc/en-us/articles/360050426432-Delete-for-everyone)
- [Signal iOS outgoing deletion eligibility](https://github.com/signalapp/Signal-iOS/blob/e5ea0729afc64261119ef232d4b00e8f48f53d3e/SignalServiceKit/Messages/Interactions/TSMessage.swift#L291-L309)
- [Signal iOS local-author validation exception](https://github.com/signalapp/Signal-iOS/blob/e5ea0729afc64261119ef232d4b00e8f48f53d3e/SignalServiceKit/Messages/Interactions/TSMessage.swift#L375-L379)
- [Signal iOS deleted-message marker](https://github.com/signalapp/Signal-iOS/blob/e5ea0729afc64261119ef232d4b00e8f48f53d3e/SignalServiceKit/Messages/Interactions/TSMessage.swift#L612-L633)
- [Signal's separate delete-for-me sync mechanism](https://github.com/signalapp/Signal-iOS/blob/e5ea0729afc64261119ef232d4b00e8f48f53d3e/SignalServiceKit/Messages/DeviceSyncing/DeleteForMe/DeleteForMeOutgoingSyncMessage.swift#L126-L140)

These references establish the API and expected behavior. Offline tests can
verify targeting, receipt retention, scheduling, and response handling; they
cannot establish that a phone received or applied a real removal request.
