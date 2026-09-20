# SPDX-License-Identifier: AGPL-3.0-only
"""Content-free receipts authorizing cleanup of this installation's own notes."""
import hashlib
import contextlib
import re
import secrets
import sqlite3
import time
import unicodedata
from pathlib import Path

HOUR_MS = 60 * 60 * 1000
DELETE_WINDOW_MS = 24 * HOUR_MS
# Leave a margin for sending the delete request before Signal's supported window.
DELETE_MARGIN_MS = 5 * 60 * 1000
METADATA_RETENTION_MS = 30 * DELETE_WINDOW_MS
DEFAULTS = {"include_sender": True, "cleanup_mode": "manual", "lifetime_hours": 6,
            "sweep_hours": 12, "discard_on_pause": False}
STATES = {"pending_send", "available", "cleanup_pending", "deleting", "deletion_requested",
          "offline", "delete_uncertain", "cleanup_failed", "too_old", "unmanageable",
          "account_mismatch", "cancelled", "expired"}
RETRY_STATES = ("cleanup_pending", "offline", "delete_uncertain")
AGE_LIMITED_STATES = {"available", "cleanup_pending", "offline", "delete_uncertain", "cleanup_failed", "account_mismatch"}


def now_ms():
    return int(time.time() * 1000)


def normalize_settings(raw=None):
    if raw is None:
        return dict(DEFAULTS)
    if not isinstance(raw, dict) or set(raw) - set(DEFAULTS):
        raise ValueError("Invalid generated-note settings.")
    value = {**DEFAULTS, **raw}
    if (type(value["include_sender"]) is not bool or type(value["discard_on_pause"]) is not bool or
            value["cleanup_mode"] not in ("manual", "lifetime", "schedule") or
            type(value["lifetime_hours"]) is not int or value["lifetime_hours"] not in (1, 6, 12, 23) or
            type(value["sweep_hours"]) is not int or value["sweep_hours"] not in (1, 6, 12)):
        raise ValueError("Invalid generated-note settings.")
    return value


def account_binding(account):
    return hashlib.sha256(("decrumb-account-v1:" + account).encode()).hexdigest()


def sender_name(event):
    """Use only an explicit display name; never derive a name from an identifier."""
    params = event.get("params", {}) if isinstance(event, dict) else {}
    payload = params.get("result", params) if isinstance(params, dict) else {}
    envelope = payload.get("envelope", {}) if isinstance(payload, dict) else {}
    raw = envelope.get("sourceName") if isinstance(envelope, dict) else None
    identifiers = [envelope.get(key) for key in ("source", "sourceUuid", "sourceNumber")]
    return sanitize_sender(raw, identifiers)


def sanitize_sender(raw, identifiers=()):
    if not isinstance(raw, str):
        return None
    value = " ".join("".join(" " if c.isspace() else c for c in raw
                             if c.isspace() or not unicodedata.category(c).startswith("C")).split())[:64]
    if (not value or value in identifiers or re.fullmatch(r"\+?[\d ()\-.]{6,}", value) or
            re.fullmatch(r"[0-9a-fA-F]{8}(?:-[0-9a-fA-F]{4}){3}-[0-9a-fA-F]{12}", value)):
        return None
    # A display name must not be able to imitate an app marker or create lines.
    return value.replace("#", "")


def can_cleanup(sent_at, current):
    return type(sent_at) is int and 0 < sent_at <= current and current - sent_at < DELETE_WINDOW_MS - DELETE_MARGIN_MS


def note_metadata(row, current):
    state = row[3]
    if state in AGE_LIMITED_STATES and row[1] is not None and row[1] <= current - DELETE_WINDOW_MS + DELETE_MARGIN_MS:
        state = "too_old"
    return {"id": row[0], "marker": "#" + row[0], "sent_at": row[1], "expires_at": row[2],
            "state": state, "lifetime_hours": row[4], "attempts": row[5],
            "can_cleanup": can_cleanup(row[1], current) and state not in
            {"pending_send", "deleting", "deletion_requested", "unmanageable", "cancelled", "expired"}}


class NoteStore:
    """Mixin using the Store connection; mutation callers must own the worker lock."""
    error = ValueError

    def init_notes(self):
        self.db.execute("""CREATE TABLE IF NOT EXISTS generated_notes (
            id TEXT PRIMARY KEY, event_id TEXT UNIQUE NOT NULL, account_hash TEXT,
            sent_at INTEGER, cleanup_at INTEGER, state TEXT NOT NULL,
            created_at INTEGER NOT NULL, lifetime_hours INTEGER, attempts INTEGER NOT NULL DEFAULT 0,
            next_attempt_at INTEGER NOT NULL DEFAULT 0, cleanup_reason TEXT)""")
        self.db.execute("CREATE INDEX IF NOT EXISTS note_cleanup_due ON generated_notes(state,next_attempt_at,cleanup_at)")
        self.db.execute("UPDATE generated_notes SET state='unmanageable' WHERE state='pending_send' AND event_id IN (SELECT id FROM outbox WHERE state='uncertain')")
        self.db.execute("UPDATE generated_notes SET state='delete_uncertain',next_attempt_at=? WHERE state='deleting'", (now_ms() + 60000,))

    def add_note(self, event_id, timestamp):
        note_id = "decrumb_" + secrets.token_hex(12)
        self.db.execute("INSERT INTO generated_notes (id,event_id,state,created_at) VALUES (?,?,'pending_send',?)", (note_id, event_id, timestamp))
        return note_id

    def note_for_event(self, event_id):
        row = self.db.execute("SELECT id FROM generated_notes WHERE event_id=?", (event_id,)).fetchone()
        return row[0] if row else None

    def record_receipt(self, event_id, account, timestamp, options):
        row = self.db.execute("SELECT lifetime_hours FROM generated_notes WHERE event_id=?", (event_id,)).fetchone()
        if row is None:
            # Old outbox records never acquire invented markers or receipt authority.
            return
        hours = row[0]
        if hours is None and options["cleanup_mode"] == "lifetime":
            hours = options["lifetime_hours"]
        deadline = timestamp + hours * HOUR_MS if hours else None
        reason = "lifetime" if hours else None
        if hours is None and options["cleanup_mode"] == "schedule":
            deadline = self._meta("note_next_sweep") or now_ms() + options["sweep_hours"] * HOUR_MS
            reason = "schedule"
        self.db.execute("""UPDATE generated_notes SET account_hash=?,sent_at=?,cleanup_at=?,
            lifetime_hours=?,cleanup_reason=?,state='available' WHERE event_id=?""",
                        (account_binding(account), timestamp, deadline, hours, reason, event_id))

    def clear_pending(self):
        with self.db:
            self.db.execute("UPDATE generated_notes SET state='cancelled',cleanup_at=NULL WHERE event_id IN (SELECT id FROM outbox WHERE state='pending')")
            changed = self.db.execute("UPDATE outbox SET state='cancelled',body=NULL WHERE state='pending'").rowcount
        return changed

    def _meta(self, key):
        row = self.db.execute("SELECT value FROM meta WHERE key=?", (key,)).fetchone()
        return row[0] if row else None

    def _set_meta(self, key, value):
        self.db.execute("INSERT OR REPLACE INTO meta VALUES (?,?)", (key, value))

    def expire_notes(self, current):
        for state in ("expired", "cancelled"):
            self.db.execute("UPDATE generated_notes SET state=?,cleanup_at=NULL WHERE state='pending_send' AND event_id IN (SELECT id FROM outbox WHERE state=?)", (state, state))
        self.db.execute("""UPDATE generated_notes SET state='too_old',next_attempt_at=0
            WHERE sent_at IS NOT NULL AND sent_at<=? AND state IN
            ('available','cleanup_pending','offline','delete_uncertain','cleanup_failed','account_mismatch')""",
                        (current - DELETE_WINDOW_MS + DELETE_MARGIN_MS,))
        self.db.execute("DELETE FROM generated_notes WHERE COALESCE(sent_at,created_at)<? AND state!='pending_send'", (current - METADATA_RETENTION_MS,))

    def update_schedule(self, options, current=None):
        options = normalize_settings(options)
        current = now_ms() if current is None else current
        with self.db:
            self.expire_notes(current)
            if options["cleanup_mode"] == "schedule":
                interval = options["sweep_hours"] * HOUR_MS
                due = self._meta("note_next_sweep")
                if not due or self._meta("note_sweep_hours") != options["sweep_hours"]:
                    due = current + interval
                    self._set_meta("note_sweep_hours", options["sweep_hours"])
                if due <= current:
                    self.db.execute("""UPDATE generated_notes SET state='cleanup_pending',cleanup_at=?,
                        next_attempt_at=?,cleanup_reason='schedule' WHERE state='available' AND lifetime_hours IS NULL""", (current, current))
                    due = current + interval
                self._set_meta("note_next_sweep", due)
                self.db.execute("UPDATE generated_notes SET cleanup_at=?,cleanup_reason='schedule' WHERE state='available' AND lifetime_hours IS NULL", (due,))
            else:
                self.db.execute("DELETE FROM meta WHERE key IN ('note_next_sweep','note_sweep_hours')")
                self.db.execute("UPDATE generated_notes SET cleanup_at=NULL,cleanup_reason=NULL WHERE state='available' AND cleanup_reason='schedule'")
                self.db.execute("""UPDATE generated_notes SET state='available',cleanup_at=NULL,cleanup_reason=NULL,
                    next_attempt_at=0 WHERE state IN ('cleanup_pending','offline','delete_uncertain') AND cleanup_reason='schedule'""")
            self.db.execute("""UPDATE generated_notes SET state='cleanup_pending',next_attempt_at=?
                WHERE state='available' AND cleanup_at IS NOT NULL AND cleanup_at<=?""", (current, current))

    def list_notes(self, limit=200, current=None):
        current = now_ms() if current is None else current
        limit = min(1000, max(1, int(limit)))
        rows = self.db.execute("""SELECT id,sent_at,cleanup_at,state,lifetime_hours,attempts
            FROM generated_notes ORDER BY created_at DESC,id LIMIT ?""", (limit,)).fetchall()
        return [note_metadata(row, current) for row in rows]

    def note_summary(self, current=None):
        current = now_ms() if current is None else current
        result = dict(self.db.execute("""SELECT CASE WHEN sent_at<=? AND state IN
            ('available','cleanup_pending','offline','delete_uncertain','cleanup_failed','account_mismatch')
            THEN 'too_old' ELSE state END AS displayed_state,count(*) FROM generated_notes GROUP BY displayed_state""",
            (current - DELETE_WINDOW_MS + DELETE_MARGIN_MS,)))
        result["total"] = sum(result.values())
        result["manageable"] = self.db.execute("""SELECT count(*) FROM generated_notes WHERE
            sent_at>? AND sent_at<=? AND state IN ('available','cleanup_pending','offline',
            'delete_uncertain','cleanup_failed','account_mismatch')""", (current - DELETE_WINDOW_MS + DELETE_MARGIN_MS, current)).fetchone()[0]
        result["legacy_unmanageable"] = self.db.execute("""SELECT count(*) FROM outbox WHERE state IN ('sent','uncertain')
            AND NOT EXISTS (SELECT 1 FROM generated_notes WHERE event_id=outbox.id)""").fetchone()[0]
        return result

    def request_cleanup(self, ids=None, current=None):
        current = now_ms() if current is None else current
        if ids is not None and (not isinstance(ids, list) or len(ids) > 1000 or
                                any(not isinstance(value, str) for value in ids)):
            raise self.error("Choose valid generated-note IDs.")
        selected = None if ids is None else set(ids)
        if selected is not None:
            if not selected:
                return 0
            placeholders = ",".join("?" for _ in selected)
            known = {row[0] for row in self.db.execute("SELECT id FROM generated_notes WHERE id IN (" + placeholders + ")", tuple(selected))}
            if not selected <= known:
                raise self.error("A selected note is not in this installation's receipt list.")
        with self.db:
            self.expire_notes(current)
            clause = " AND id IN (" + placeholders + ")" if selected is not None else ""
            changed = self.db.execute("""UPDATE generated_notes SET state='cleanup_pending',cleanup_at=?,next_attempt_at=?,
                attempts=0,cleanup_reason='manual' WHERE state IN
                ('available','cleanup_pending','offline','delete_uncertain','cleanup_failed','account_mismatch')
                AND sent_at>? AND sent_at<=?""" + clause,
                (current, current, current - DELETE_WINDOW_MS + DELETE_MARGIN_MS, current) +
                (tuple(selected) if selected is not None else ())).rowcount
        return changed

    def set_note_lifetime(self, note_id, hours, current=None):
        if not isinstance(note_id, str) or type(hours) is not int or hours not in (0, 1, 6, 12, 23):
            raise self.error("Choose Keep or a supported note lifetime.")
        current = now_ms() if current is None else current
        row = self.db.execute("SELECT sent_at,state FROM generated_notes WHERE id=?", (note_id,)).fetchone()
        if row is None:
            raise self.error("This note is not in this installation's receipt list.")
        if row[1] not in ("pending_send", "available", "cleanup_pending", "offline", "delete_uncertain", "cleanup_failed", "account_mismatch", "too_old"):
            raise self.error("This note's lifetime can no longer be changed.")
        if row[0] is not None and not can_cleanup(row[0], current):
            raise self.error("This note is outside Signal's supported cleanup window.")
        deadline = row[0] + hours * HOUR_MS if hours and row[0] is not None else None
        state = "pending_send" if row[0] is None else ("cleanup_pending" if deadline is not None and deadline <= current else "available")
        with self.db:
            self.db.execute("""UPDATE generated_notes SET lifetime_hours=?,cleanup_at=?,state=?,
                cleanup_reason=?,next_attempt_at=?,attempts=0 WHERE id=?""",
                            (hours, deadline, state, "lifetime" if hours else None, current if state == "cleanup_pending" else 0, note_id))
        row = self.db.execute("SELECT id,sent_at,cleanup_at,state,lifetime_hours,attempts FROM generated_notes WHERE id=?", (note_id,)).fetchone()
        return note_metadata(row, current)


def read_notes(path, limit=200):
    """Read public receipt metadata without migrations, recovery or worker locking."""
    empty = {"notes": [], "note_counts": {"total": 0, "manageable": 0, "legacy_unmanageable": 0}}
    path = Path(path)
    if not path.exists():
        return empty
    try:
        with contextlib.closing(sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True, timeout=0.25)) as db:
            tables = {row[0] for row in db.execute("SELECT name FROM sqlite_master WHERE type='table'")}
            if "generated_notes" not in tables:
                if "outbox" in tables:
                    empty["note_counts"]["legacy_unmanageable"] = db.execute("SELECT count(*) FROM outbox WHERE state IN ('sent','uncertain')").fetchone()[0]
                return empty
            view = NoteStore()
            view.db = db
            return {"notes": view.list_notes(limit), "note_counts": view.note_summary()}
    except (OSError, sqlite3.Error, ValueError):
        return empty
