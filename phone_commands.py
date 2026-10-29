# SPDX-License-Identifier: AGPL-3.0-only
"""Optional, bounded owner-to-Note-to-Self commands; no machine execution or fetches."""
import copy
import hashlib
import json
from typing import NamedTuple

import diagnostics


MAX_AGE_MS = 24 * 60 * 60 * 1000
MAX_COMMAND_BYTES = 4096
HELP = (
    "Phone commands (send to Note to Self):\n"
    "/decrumb help — show this list\n"
    "/decrumb status — check the running helper\n"
    "/decrumb clean <link> — apply your cleaning rules\n"
    "/decrumb rules [page] — show bundled and custom rules\n"
    "/decrumb rules add <site> <parameter> [parameter …] — remove query fields\n"
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
    if type(data.get("expiresInSeconds")) is not int or data["expiresInSeconds"] < 0 or data.get("viewOnce") is not False:
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
    elif text == "/decrumb rules" or text.startswith("/decrumb rules "):
        operation, argument = "rules", text[len("/decrumb rules"):].strip()
    elif text.startswith("/decrumb clean "):
        operation, argument = "clean", text[len("/decrumb clean "):].strip()
        if not argument:
            return None
    else:
        return None
    identity = json.dumps(["phone-command", sorted(aliases), timestamp], separators=(",", ":"))
    return Command("phone_" + hashlib.sha256(identity.encode()).hexdigest(), timestamp, operation, argument)


def process(event, aliases, store, config, cleaner, current, started_at, rules=None):
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
    elif command.operation == "rules":
        lines = rules.handle(command, store, config) if rules else ["Rule commands are unavailable in this installation."]
    elif command.operation == "status":
        counts = store.counts()
        release = diagnostics.release()
        version = release["version"]
        if release["build"]:
            version += f" (build {release['build']})"
        mode = {"all": "All sites", "selected": "Selected sites", "off": "Off"}.get(config.get("settings", {}).get("mode"), "Off")
        lines = [
            "The helper is running and received your command.\n"
            f"Version: {version}\n"
            f"Cleaning: {mode}\n"
            f"Queued: {counts.get('pending', 0)} · Sent: {counts.get('sent', 0)} · Unconfirmed: {counts.get('uncertain', 0)}\n"
            "Counts include command replies. Sent means Signal acknowledged the send."
        ]
    else:
        lines = [HELP]
    store.enqueue(command.event_id, command.timestamp, lines, options=config.get("notes"))
    return True


RULE_USAGE = (
    "/decrumb rules [page] — show rules\n"
    "/decrumb rules add <site> <parameter> [parameter …]\n"
    "Example: /decrumb rules add doordash.com/store aw\n"
    "Use exact query names, separated by spaces or commas. No wildcards or regex."
)


class RuleCommands:
    """Worker-owned rule operations. Callbacks access only installed rules/config."""

    def __init__(self, defaults, validate, save):
        self.defaults, self.validate, self.save = defaults, validate, save

    @staticmethod
    def _names(label, names):
        if not names:
            return [label + ": none"]
        lines, line = [], label + ": "
        for name in names:
            if len(line) + len(name) > 1000:
                lines.append(line.rstrip(", "))
                line = label + " (continued): "
            line += name + ", "
        return lines + [line.rstrip(", ")]

    def _pages(self, config):
        bundled = self.defaults()
        settings = self.validate(config["settings"])
        lines = [
            "Cleaning rules — bundled revision " + bundled["revision"],
            "Mode: " + settings["mode"],
        ]
        # Site lists may each contain 100 long values; keep every response bounded.
        lines = lines[:2] + [
            "Selected site: " + site for site in settings["baseURLs"]
        ] + ["Excluded site: " + site for site in settings["excludedURLs"]]
        lines += self._names("Global remove", bundled["globalRemove"])
        lines += self._names("Protect entire signed link", bundled["protectedParameters"])
        for label, entries in (("Bundled", bundled["sites"]), ("Custom", settings["rules"])):
            if not entries:
                lines.append(label + " rules: none")
            for entry in entries:
                lines.append(label + " site: " + entry["site"])
                lines += self._names("  Remove", entry["remove"])
                lines += self._names("  Keep", entry["keep"])
        lines.append("Keep rules override removals. Exclusions, cleaning mode and signed-link protection still apply.")
        pages, page, size = [], "", 0
        for line in lines:
            # Normalized sites can contain Unicode. Bound actual UTF-8 bytes.
            for character in line + "\n":
                width = len(character.encode())
                if size + width > 5000:
                    pages.append(page)
                    page, size = "", 0
                page += character
                size += width
        if page:
            pages.append(page)
        return pages

    def handle(self, command, store, config):
        args = command.argument.split()
        if not args or (len(args) == 1 and args[0].isascii() and args[0].isdigit()):
            try:
                pages = self._pages(config)
            except (ValueError, OSError, KeyError, TypeError):
                return ["Rules could not be read. Retry the command or check the app."]
            page = int(args[0]) if args else 1
            if not 1 <= page <= len(pages):
                return [f"Choose a rules page from 1 to {len(pages)}: /decrumb rules <page>"]
            footer = f"Page {page}/{len(pages)}."
            if page < len(pages):
                footer += f" Next: /decrumb rules {page + 1}"
            return [pages[page - 1] + footer]
        if args[0] != "add" or len(args) < 3:
            return [RULE_USAGE]
        if store.rule_change_seen(command.event_id):
            return []
        try:
            names = [name for item in args[2:] for name in item.split(",")]
            addition = self.validate({"mode": "all", "baseURLs": [], "rules": [
                {"site": args[1], "remove": names, "keep": []}
            ]})["rules"][0]
            previous = self.validate(config["settings"])
            settings = copy.deepcopy(previous)
            existing = next((entry for entry in settings["rules"] if entry["site"] == addition["site"]), None)
            if existing is None:
                settings["rules"].append(addition)
            else:
                if set(addition["remove"]).intersection(existing["keep"]):
                    return ["An existing keep rule preserves these names. Edit that keep rule in the app first."]
                existing["remove"] = list(dict.fromkeys(existing["remove"] + addition["remove"]))
            settings = self.validate(settings)
        except (ValueError, KeyError, TypeError):
            return ["Invalid rule or rule limit reached. No settings changed.\n" + RULE_USAGE]
        if settings == previous:
            return ["This custom rule already exists. No settings changed."]
        # Reserve before any write. A crash or missing reply must never replay a
        # settings mutation; the owner can send a fresh command to retry.
        if not store.reserve_rule_change(command.event_id, command.timestamp):
            return []
        try:
            self.save(settings)
        except (OSError, ValueError):
            return ["The rule could not be saved. Retry with a new command or check the app."]
        return [
            "Rule added. Remove " + str(len(addition["remove"])) + " query parameter(s)."
            "\nUse /decrumb rules to see the saved rule." +
            "\nSaved and active; no restart needed. Pending notes from the previous rules were discarded."
            "\nKeep rules, exclusions, cleaning mode and signed-link protection still apply."
        ]
