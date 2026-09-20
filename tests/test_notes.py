# SPDX-License-Identifier: AGPL-3.0-only
"""Synthetic receipt and cleanup tests: never use a Signal account or network."""
import json
from pathlib import Path
import sqlite3
import tempfile
import threading
import unittest
from unittest.mock import patch

import notes
import decrumb

SELF = "synthetic-self-account"
URL = "https://example.invalid/clean"


class Rpc:
    def __init__(self, timestamp, fail=None, account=SELF, result=None):
        self.timestamp, self.fail, self.account, self.result = timestamp, fail, account, result
        self.calls = []
        self.cancel_event = threading.Event()

    def call(self, method, params=None, timeout=60):
        self.calls.append((method, params))
        if self.fail == method:
            raise decrumb.SafeError("Synthetic transport unavailable.")
        if method == "listAccounts":
            return [{"number": self.account}]
        if self.result is not None:
            return self.result
        return {"timestamp": self.timestamp, "results": [{"type": "SUCCESS"}]}


class NotesTests(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.path = Path(self.folder.name) / "outbox.sqlite3"
        self.store = decrumb.Store(self.path)
        self.now = decrumb.now_ms()

    def tearDown(self):
        self.store.close()
        self.folder.cleanup()

    def send(self, event="event", sender=None, options=None, sent_at=None):
        self.store.enqueue(event, self.now, [URL], sender=sender, options=options)
        rpc = Rpc(sent_at or self.now)
        decrumb.deliver_one(self.store, rpc, SELF, options)
        return self.store.note_for_event(event), rpc

    def test_marker_and_sender_are_visible_but_not_retained(self):
        note_id, rpc = self.send(sender="Synthetic Name\n#Fake\u202e")
        message = rpc.calls[0][1]["message"]
        self.assertIn("#" + note_id, message)
        self.assertIn("Decrumb · From Synthetic Name Fake", message)
        self.assertNotIn("\u202e", message)
        record = self.store.list_notes()[0]
        self.assertEqual(record["sent_at"], self.now)
        self.assertEqual(record["state"], "available")
        self.assertNotIn("Synthetic Name", json.dumps(record))
        self.assertNotIn(URL.encode(), self.path.read_bytes())
        self.assertNotIn(b"Synthetic Name", self.path.read_bytes())
        self.assertNotIn(SELF.encode(), self.path.read_bytes())

    def test_sender_missing_or_identifiers_never_fall_back(self):
        for source_name in (None, "+15550000002", "12345678-abcd-abcd-abcd-123456789012"):
            value = {"params": {"result": {"envelope": {"sourceName": source_name, "sourceNumber": "+15550000002"}}}}
            self.assertIsNone(notes.sender_name(value))
        self.send(sender="Known Display Name", options={"include_sender": False})
        self.assertNotIn(b"Known Display Name", self.path.read_bytes())

    def test_only_acknowledged_original_send_timestamp_authorizes_delete(self):
        original = self.now - 1000
        note_id, _ = self.send(sent_at=original)
        self.assertEqual(self.store.request_cleanup([note_id], current=self.now), 1)
        rpc = Rpc(self.now + 5)
        self.assertTrue(decrumb.cleanup_one(self.store, rpc, SELF, current=self.now))
        self.assertEqual(rpc.calls, [("listAccounts", None), ("remoteDelete", {
            "account": SELF, "noteToSelf": True, "targetTimestamp": original})])
        record = self.store.list_notes()[0]
        self.assertEqual((record["sent_at"], record["state"]), (original, "deletion_requested"))
        self.assertFalse(decrumb.cleanup_one(self.store, rpc, SELF, current=self.now))

    def test_arbitrary_ids_are_rejected_without_partial_mutation(self):
        note_id, _ = self.send()
        with self.assertRaises(decrumb.SafeError):
            self.store.request_cleanup([note_id, "decrumb_untrusted"])
        self.assertEqual(self.store.list_notes()[0]["state"], "available")
        self.assertEqual(self.store.request_cleanup([], current=self.now), 0)

    def test_mismatched_account_never_deletes(self):
        note_id, _ = self.send()
        self.store.request_cleanup([note_id], current=self.now)
        rpc = Rpc(self.now, account="different-synthetic-account")
        decrumb.cleanup_one(self.store, rpc, "different-synthetic-account", current=self.now)
        self.assertEqual([call[0] for call in rpc.calls], ["listAccounts"])
        self.assertEqual(self.store.list_notes()[0]["state"], "account_mismatch")

    def test_ambiguous_send_and_crash_have_no_delete_authority(self):
        self.store.enqueue("uncertain", self.now, [URL])
        with self.assertRaises(decrumb.SafeError):
            decrumb.deliver_one(self.store, Rpc(self.now, fail="send"), SELF)
        self.assertEqual(self.store.list_notes()[0]["state"], "unmanageable")
        self.assertIsNone(self.store.list_notes()[0]["sent_at"])
        self.store.enqueue("crashed", self.now, [URL])
        with self.store.db:
            self.store.db.execute("UPDATE outbox SET state='inflight' WHERE id='crashed'")
        self.store.close()
        self.store = decrumb.Store(self.path)
        self.assertEqual(self.store.note_summary()["unmanageable"], 2)
        self.assertEqual(self.store.request_cleanup(current=self.now), 0)
        self.assertFalse(decrumb.cleanup_one(self.store, Rpc(self.now), SELF, current=self.now))

    def test_lifetime_capture_override_and_keep(self):
        opts = decrumb.notes_settings({"cleanup_mode": "lifetime", "lifetime_hours": 6})
        note_id, _ = self.send(options=opts)
        self.assertEqual(self.store.list_notes()[0]["expires_at"], self.now + 6 * notes.HOUR_MS)
        self.store.set_note_lifetime(note_id, 1, current=self.now)
        due = self.now + notes.HOUR_MS
        rpc = Rpc(due)
        self.assertFalse(decrumb.cleanup_one(self.store, rpc, SELF, opts, current=due - 1))
        self.assertTrue(decrumb.cleanup_one(self.store, rpc, SELF, opts, current=due))
        kept, _ = self.send("keep", options=opts)
        self.store.set_note_lifetime(kept, 0, current=self.now)
        self.store.update_schedule({"cleanup_mode": "schedule", "sweep_hours": 1}, self.now)
        self.store.update_schedule({"cleanup_mode": "schedule", "sweep_hours": 1}, due)
        self.assertEqual(next(v for v in self.store.list_notes() if v["id"] == kept)["state"], "available")
        self.assertEqual(self.store.request_cleanup([kept], current=due), 1)

    def test_schedule_survives_restart_without_resetting_deadline(self):
        opts = decrumb.notes_settings({"cleanup_mode": "schedule", "sweep_hours": 1})
        self.store.update_schedule(opts, self.now)
        note_id, _ = self.send(options=opts)
        due = self.now + notes.HOUR_MS
        self.assertEqual(self.store.list_notes()[0]["expires_at"], due)
        self.store.close()
        self.store = decrumb.Store(self.path)
        self.store.update_schedule(opts, due - 1)
        self.assertEqual(self.store.list_notes()[0]["expires_at"], due)
        rpc = Rpc(due)
        self.assertTrue(decrumb.cleanup_one(self.store, rpc, SELF, opts, current=due))
        self.assertEqual(self.store.list_notes()[0]["state"], "deletion_requested")

    def test_cleanup_retries_back_off_and_stop_outside_window(self):
        note_id, _ = self.send()
        self.store.request_cleanup([note_id], current=self.now)
        rpc = Rpc(self.now, fail="remoteDelete")
        self.assertTrue(decrumb.cleanup_one(self.store, rpc, SELF, current=self.now))
        self.assertEqual(self.store.list_notes()[0]["state"], "delete_uncertain")
        self.assertFalse(decrumb.cleanup_one(self.store, rpc, SELF, current=self.now + 29000))
        self.assertTrue(decrumb.cleanup_one(self.store, rpc, SELF, current=self.now + 30000))
        calls = len(rpc.calls)
        self.assertFalse(decrumb.cleanup_one(self.store, rpc, SELF, current=self.now + notes.DELETE_WINDOW_MS))
        self.assertEqual(len(rpc.calls), calls)
        self.assertEqual(self.store.list_notes()[0]["state"], "too_old")

    def test_offline_and_cancelled_cleanup_do_not_invent_success(self):
        note_id, _ = self.send()
        self.store.request_cleanup([note_id], current=self.now)
        rpc = Rpc(self.now, fail="listAccounts")
        decrumb.cleanup_one(self.store, rpc, SELF, current=self.now)
        self.assertEqual(self.store.list_notes()[0]["state"], "offline")
        rpc.cancel_event.set()
        self.assertFalse(decrumb.cleanup_one(self.store, rpc, SELF, current=self.now + 60000))

    def test_clear_pending_only_cancels_unsent_notes(self):
        sent, _ = self.send()
        self.store.enqueue("pending", self.now, [URL], sender="Private Sender")
        self.assertEqual(self.store.clear_pending(), 1)
        self.assertEqual(self.store.note_summary()["cancelled"], 1)
        self.assertEqual(self.store.note_summary()["available"], 1)
        self.assertNotIn(b"Private Sender", self.path.read_bytes())

    def test_old_schema_migrates_without_inventing_sent_receipts(self):
        legacy = Path(self.folder.name) / "legacy.sqlite3"
        with sqlite3.connect(legacy) as db:
            db.execute("CREATE TABLE outbox(id TEXT PRIMARY KEY,timestamp INTEGER NOT NULL,state TEXT NOT NULL,body TEXT)")
            db.execute("INSERT INTO outbox VALUES ('old-sent',?,'sent',NULL)", (self.now,))
            db.execute("INSERT INTO outbox VALUES ('old-pending',?,'pending',?)", (self.now, "Clean link\n" + URL))
        before = legacy.read_bytes()
        self.assertEqual(decrumb.read_notes(legacy)["note_counts"]["legacy_unmanageable"], 1)
        self.assertEqual(legacy.read_bytes(), before)
        migrated = decrumb.Store(legacy)
        try:
            self.assertEqual(migrated.note_summary()["legacy_unmanageable"], 1)
            self.assertEqual(migrated.request_cleanup(current=self.now), 0)
            rpc = Rpc(self.now)
            decrumb.deliver_one(migrated, rpc, SELF)
            self.assertIn("#decrumb_", rpc.calls[0][1]["message"])
            self.assertEqual(migrated.note_summary()["available"], 1)
            self.assertEqual(migrated.note_summary()["legacy_unmanageable"], 1)
        finally:
            migrated.close()

    def test_read_only_snapshot_does_not_recover_active_deletion(self):
        note_id, _ = self.send()
        with self.store.db:
            self.store.db.execute("UPDATE generated_notes SET state='deleting' WHERE id=?", (note_id,))
        state = decrumb.read_notes(self.path)
        self.assertEqual(state["notes"][0]["state"], "deleting")
        self.assertEqual(self.store.list_notes()[0]["state"], "deleting")
        serialized = json.dumps(state)
        self.assertNotIn(SELF, serialized)
        self.assertNotIn(URL, serialized)

    def test_receipt_metadata_expires_at_30_days(self):
        self.send()
        self.store.expire(self.now + 29 * notes.DELETE_WINDOW_MS)
        self.assertEqual(self.store.note_summary()["total"], 1)
        self.store.expire(self.now + 31 * notes.DELETE_WINDOW_MS)
        self.assertEqual(self.store.note_summary()["total"], 0)
        self.assertEqual(self.store.counts(), {})

    def test_paused_read_only_snapshot_reports_age_limit_without_writing(self):
        self.send()
        with patch("notes.now_ms", return_value=self.now + notes.DELETE_WINDOW_MS):
            result = decrumb.read_notes(self.path)
        self.assertEqual(result["notes"][0]["state"], "too_old")
        self.assertEqual(result["note_counts"]["too_old"], 1)
        self.assertFalse(result["notes"][0]["can_cleanup"])
        self.assertEqual(self.store.db.execute("SELECT state FROM generated_notes").fetchone()[0], "available")

    def test_missing_or_empty_results_never_grant_receipt_authority(self):
        for index, response in enumerate(({"timestamp": self.now}, {"timestamp": self.now, "results": []})):
            self.store.enqueue("malformed-" + str(index), self.now, [URL])
            with self.assertRaises(decrumb.SafeError):
                decrumb.deliver_one(self.store, Rpc(self.now, result=response), SELF)
        self.assertEqual(self.store.note_summary()["unmanageable"], 2)
        note_id, _ = self.send()
        self.store.request_cleanup([note_id], current=self.now)
        decrumb.cleanup_one(self.store, Rpc(self.now, result={"timestamp": self.now}), SELF, current=self.now)
        self.assertEqual(next(v for v in self.store.list_notes() if v["id"] == note_id)["state"], "delete_uncertain")

    def test_all_cleanup_is_not_limited_to_visible_page(self):
        with self.store.db:
            self.store.db.executemany("""INSERT INTO generated_notes
                (id,event_id,account_hash,sent_at,state,created_at) VALUES (?,?,?,?,'available',?)""",
                [("decrumb_synthetic" + str(i), "event-" + str(i), notes.account_binding(SELF), self.now, self.now) for i in range(205)])
        self.assertEqual(len(self.store.list_notes()), 200)
        self.assertEqual(self.store.request_cleanup(current=self.now), 205)
        self.assertEqual(self.store.note_summary()["cleanup_pending"], 205)

    def test_idle_cleanup_check_has_no_schedule_writes(self):
        with patch.object(self.store, "update_schedule", side_effect=AssertionError("unexpected scheduler write")):
            self.assertFalse(decrumb.cleanup_one(self.store, Rpc(self.now), SELF, schedule=False))

    def test_global_lifetime_changes_apply_only_to_future_sends(self):
        opts = decrumb.notes_settings({"cleanup_mode": "lifetime", "lifetime_hours": 6})
        self.send(options=opts)
        self.store.update_schedule(decrumb.notes_settings(), self.now + 7 * notes.HOUR_MS)
        self.assertEqual(self.store.list_notes()[0]["state"], "cleanup_pending")
        new_id, _ = self.send("new-manual", options=decrumb.notes_settings())
        self.assertIsNone(next(v for v in self.store.list_notes() if v["id"] == new_id)["expires_at"])

    def test_settings_are_strict_and_backward_compatible(self):
        self.assertEqual(decrumb.notes_settings()["cleanup_mode"], "manual")
        self.assertTrue(decrumb.notes_settings()["include_sender"])
        for value in ({"lifetime_hours": 24}, {"include_sender": 1}, {"cleanup_mode": "unknown"}, {"sweep_hours": 0}, {"surprise": True}):
            with self.assertRaises(decrumb.SafeError):
                decrumb.notes_settings(value)


if __name__ == "__main__":
    unittest.main(verbosity=2)
