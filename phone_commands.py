# SPDX-License-Identifier: AGPL-3.0-only
"""Optional, bounded owner-to-Note-to-Self commands; no machine execution or fetches."""
import hashlib
import json
from typing import NamedTuple


MAX_AGE_MS = 24 * 60 * 60 * 1000
MAX_COMMAND_BYTES = 4096
HELP = (
    "Phone commands (send to Note to Self):\n"
    "/decrumb help — show this list\n"
    "/decrumb status — check the running helper\n"
    "/decrumb clean <link> — apply your cleaning rules\n"
    "The helper must be running and online. Links are never opened or fetched."
)


def normalize_settings(raw=None):
    if raw is None:
        return {"enabled": False}
    if not isinstance(raw, dict) or set(raw) - {"enabled"} or type(raw.get("enabled")) is not bool:
        raise ValueError("Phone commands must be on or off.")
    return {"enabled": raw["enabled"]}


class Command(NamedTuple):
    event_id: str
    timestamp: int
    operation: str
    argument: str


def _own_aliases(value, fields, aliases):
    present = [value.get(field) for field in fields if value.get(field) is not None]
    return bool(present) and all(isinstance(item, str) and item in aliases for item in present)


def candidate(event, aliases, enabled_at, current):
    """Accept only a fresh, ordinary, authenticated self-to-self sent transcript.

    signal-cli 0.14.8 flattens JsonDataMessage into syncMessage.sentMessage.
    A peer's ordinary message, including text resembling a command, cannot enter
    this path. Every supplied identity must match the linked account.
    """
    if not isinstance(event, dict) or event.get("method") != "receive":
        return None
    params = event.get("params")
    if not isinstance(params, dict):
        return None
    payload = params.get("result", params)
    if not isinstance(payload, dict) or not isinstance(payload.get("account"), str) or payload["account"] not in aliases:
        return None
    envelope = payload.get("envelope")
    if not isinstance(envelope, dict) or not _own_aliases(envelope, ("source", "sourceNumber", "sourceUuid"), aliases):
        return None
    if any(envelope.get(key) is not None for key in ("dataMessage", "editMessage", "storyMessage")):
        return None
    sync = envelope.get("syncMessage")
    if not isinstance(sync, dict) or sync.get("sentStoryMessage") is not None:
        return None
    data = sync.get("sentMessage")
    if not isinstance(data, dict) or not _own_aliases(data, ("destination", "destinationNumber", "destinationUuid"), aliases):
        return None
    if any(data.get(key) is not None for key in (
        "editMessage", "groupInfo", "groupCallUpdate", "reaction", "remoteDelete", "adminDelete",
        "storyContext", "pollCreate", "pollVote", "pollTerminate", "pinMessage", "unpinMessage",
        "quote", "payment", "sticker",
    )):
        return None
    if any(data.get(key) for key in ("attachments", "contacts", "mentions")):
        return None
    for key in ("isExpirationUpdate", "isEndSession", "isProfileKeyUpdate"):
        if data.get(key) is not None and data.get(key) is not False:
            return None
    if type(data.get("expiresInSeconds")) is not int or data["expiresInSeconds"] != 0 or data.get("viewOnce") is not False:
        return None
    styles = data.get("textStyles", [])
    if not isinstance(styles, list) or any(
        not isinstance(style, dict) or style.get("style") not in {"BOLD", "ITALIC", "STRIKETHROUGH", "MONOSPACE"}
        for style in styles
    ):
        return None
    text, timestamp = data.get("message"), data.get("timestamp")
    if not isinstance(text, str):
        return None
    try:
        if len(text.encode()) > MAX_COMMAND_BYTES:
            return None
    except UnicodeError:
        return None
    if type(timestamp) is not int or not max(enabled_at, current - MAX_AGE_MS) <= timestamp <= current + 300000:
        return None
    text = text.strip()
    if text in ("/decrumb", "/decrumb help", "/decrumb status"):
        operation, argument = ("status" if text.endswith(" status") else "help"), ""
    elif text.startswith("/decrumb clean "):
        operation, argument = "clean", text[len("/decrumb clean "):].strip()
        if not argument:
            return None
    else:
        return None
    identity = json.dumps(["phone-command", sorted(aliases), timestamp], separators=(",", ":"))
    return Command("phone_" + hashlib.sha256(identity.encode()).hexdigest(), timestamp, operation, argument)


def process(event, aliases, store, config, cleaner, current, started_at):
    """Queue a fixed reply or locally cleaned links through the ordinary outbox.

    The supplied cleaner is the same local helper used for incoming links. All
    replies use Store.enqueue and the existing Note-to-Self-only delivery path,
    which supplies bounded storage, receipt tracking, and no ambiguous retries.
    Commands queued while this worker was stopped are intentionally ignored.
    """
    if not normalize_settings(config.get("phone_commands"))["enabled"]:
        return False
    command = candidate(event, aliases, max(store.enabled_at, started_at), current)
    if command is None:
        return False
    if store.contains(command.event_id):
        return True
    if command.operation == "clean":
        lines = cleaner(command.argument)
        if not lines:
            lines = ["No links changed under your current cleaning rules. No links were opened or fetched."]
    elif command.operation == "status":
        counts = store.counts()
        mode = {"all": "All sites", "selected": "Selected sites", "off": "Off"}.get(config.get("settings", {}).get("mode"), "Off")
        lines = [
            "The helper is running and received your command.\n"
            f"Cleaning: {mode}\n"
            f"Queued: {counts.get('pending', 0)} · Sent: {counts.get('sent', 0)} · Unconfirmed: {counts.get('uncertain', 0)}\n"
            "Counts include command replies. Sent means Signal acknowledged the send."
        ]
    else:
        lines = [HELP]
    store.enqueue(command.event_id, command.timestamp, lines, options=config.get("notes"))
    return True
