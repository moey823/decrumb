# SPDX-License-Identifier: AGPL-3.0-only
"""Synthetic owner-command security, persistence, app bridge and transport tests."""
import contextlib
import copy
import io
import json
import shutil
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import unittest
from unittest.mock import Mock, patch

import decrumb
import phone_commands
if sys.platform != 'win32':
    import desktop
    import service
from test_decrumb import HELPER, SETTINGS, SELF, PEER, StubRpc, event


ALIASES = {SELF, "00000000-0000-4000-8000-000000000001"}
SELF_UUID = "00000000-0000-4000-8000-000000000001"


def command_event(timestamp, text="/decrumb status", expires=0):
    return {"method": "receive", "params": {"result": {"account": SELF, "envelope": {
        "source": SELF, "sourceNumber": SELF, "sourceUuid": "00000000-0000-4000-8000-000000000001",
        "syncMessage": {"sentMessage": {
            "destination": SELF, "destinationNumber": SELF, "destinationUuid": "00000000-0000-4000-8000-000000000001",
            "timestamp": timestamp, "message": text, "expiresInSeconds": expires,
            "viewOnce": False, "textStyles": [],
        }},
    }}}}


def sent(value):
    return value["params"]["result"]["envelope"]["syncMessage"]["sentMessage"]


class OwnerIdentityTests(unittest.TestCase):
    def test_pinned_client_number_only_response_resolves_own_uuid(self):
        account, aliases = decrumb.account_details([{"number": SELF}])
        rpc = Mock()
        rpc.call.return_value = [{"number": SELF, "uuid": SELF_UUID,
                                  "name": "Private synthetic name", "profile": {"about": "private"}}]
        resolved = decrumb.command_aliases(rpc, account, aliases)
        self.assertEqual(resolved, ALIASES)
        self.assertEqual(aliases, {SELF})
        rpc.call.assert_called_once_with("listContacts", {
            "account": SELF, "recipient": [SELF], "allRecipients": True})
        now = decrumb.now_ms()
        self.assertIsNone(phone_commands.candidate(command_event(now), aliases, now, now))
        self.assertEqual(phone_commands.candidate(command_event(now), resolved, now, now).operation, "status")

    def test_unverified_or_ambiguous_lookup_fails_closed_without_private_errors(self):
        for result in (None, {}, [], [{"number": SELF}],
                       [{"number": PEER, "uuid": SELF_UUID}],
                       [{"number": SELF, "uuid": "not-a-uuid"}],
                       [{"number": SELF, "uuid": "00000000-0000-0000-0000-000000000000"}],
                       [{"number": SELF, "uuid": None}],
                       [{"number": SELF, "uuid": SELF_UUID, "isUnregistered": True}],
                       [{"number": SELF, "uuid": SELF_UUID}] * 2):
            rpc = Mock()
            rpc.call.return_value = result
            with self.subTest(result=result), self.assertRaises(decrumb.SafeError) as raised:
                decrumb.command_aliases(rpc, SELF, {SELF})
            for value in (SELF, PEER, SELF_UUID, "not-a-uuid"):
                self.assertNotIn(value, str(raised.exception))

    def test_conflicting_previously_known_identity_is_not_added(self):
        rpc = Mock()
        rpc.call.return_value = [{"number": SELF, "uuid": SELF_UUID}]
        with self.assertRaises(decrumb.SafeError):
            decrumb.command_aliases(rpc, SELF, {SELF, "00000000-0000-4000-8000-000000000002"})

    def test_lookup_failure_does_not_fall_back_to_unverified_event_identity(self):
        rpc = Mock()
        rpc.call.side_effect = decrumb.SafeError("Signal command timed out.")
        with self.assertRaises(decrumb.SafeError):
            decrumb.command_aliases(rpc, SELF, {SELF})


class CommandParsingTests(unittest.TestCase):
    def setUp(self):
        self.now = decrumb.now_ms()
        self.value = command_event(self.now)

    def parse(self, value):
        return phone_commands.candidate(value, ALIASES, self.now - 1000, self.now)

    def test_known_commands_and_direct_receive_shape(self):
        for text, operation in (("/decrumb", "help"), ("/decrumb help", "help"),
                                ("/decrumb status", "status"), ("/decrumb clean https://example.com/?utm_source=x", "clean"),
                                ("/decrumb rules", "rules"), ("/decrumb rules 2", "rules"),
                                ("/decrumb rules add doordash.com/store aw", "rules")):
            value = command_event(self.now, text)
            result = self.parse(value)
            self.assertEqual(result.operation, operation)
            self.assertNotIn(SELF, result.event_id)
            self.assertNotIn("example", result.event_id)
            self.assertEqual(result, self.parse({"method": "receive", "params": value["params"]["result"]}))

    def test_command_text_cannot_authorize_a_peer_or_nonself_destination(self):
        for container, fields in (("envelope", ("source", "sourceNumber", "sourceUuid")),
                                  ("sent", ("destination", "destinationNumber", "destinationUuid"))):
            for field in fields:
                value = copy.deepcopy(self.value)
                target = value["params"]["result"]["envelope"] if container == "envelope" else sent(value)
                target[field] = PEER
                self.assertIsNone(self.parse(value))
            value = copy.deepcopy(self.value)
            target = value["params"]["result"]["envelope"] if container == "envelope" else sent(value)
            for field in fields:
                target.pop(field)
            self.assertIsNone(self.parse(value))
        self.assertIsNone(self.parse(event(self.now, "/decrumb status")))

    def test_account_required_and_malformed_identities_fail_closed(self):
        for account in (None, PEER, [], {}, 1):
            value = copy.deepcopy(self.value)
            value["params"]["result"]["account"] = account
            self.assertIsNone(self.parse(value))
        for value in (None, [], {}, {"method": "receive", "params": []},
                      {"method": "receive", "params": {"result": []}}):
            self.assertIsNone(self.parse(value))

    def test_private_control_and_group_metadata_fail_closed(self):
        for key, value in (
            ("expiresInSeconds", None), ("expiresInSeconds", -1), ("expiresInSeconds", "0"),
            ("expiresInSeconds", True), ("expiresInSeconds", False), ("expiresInSeconds", 60.0),
            ("viewOnce", True), ("viewOnce", None), ("viewOnce", 0),
            ("groupInfo", {}), ("editMessage", {}), ("storyContext", {}), ("remoteDelete", {}),
            ("adminDelete", {}), ("reaction", {}), ("quote", {}), ("pollVote", {}),
            ("attachments", [{}]), ("isExpirationUpdate", True), ("isEndSession", "false"),
            ("textStyles", [{"style": "SPOILER"}]), ("textStyles", [{"style": "UNKNOWN"}]),
            ("textStyles", None), ("textStyles", [None]),
        ):
            with self.subTest(key=key, value=value):
                changed = copy.deepcopy(self.value)
                sent(changed)[key] = value
                self.assertIsNone(self.parse(changed))

    def test_disappearing_commands_are_accepted_but_missing_timer_is_not(self):
        for expires in (0, 1, 60, 604800):
            with self.subTest(expires=expires):
                self.assertEqual(self.parse(command_event(self.now, expires=expires)).operation, "status")
        sent(self.value).pop("expiresInSeconds")
        self.assertIsNone(self.parse(self.value))

    def test_unknown_commands_quotes_and_generated_replies_are_ignored(self):
        for text in ("/decrumb status now", "/Decrumb status", "Please /decrumb status", "/decrumb shell whoami",
                     "/decrumb clean", "Decrumb\n/decrumb help\n#decrumb_synthetic", "/decrumb clean  "):
            self.assertIsNone(self.parse(command_event(self.now, text)))

    def test_limits_and_timestamp_floor(self):
        self.assertIsNone(self.parse(command_event(self.now, "/decrumb clean " + "x" * 4096)))
        self.assertIsNone(self.parse(command_event(self.now, "/decrumb clean \ud800")))
        for timestamp in (self.now - 1001, self.now - 2 * phone_commands.MAX_AGE_MS, self.now + 300001, True, "0"):
            self.assertIsNone(self.parse(command_event(timestamp)))
        self.assertEqual(self.parse(command_event(self.now, "/decrumb clean https://example.com/" )).argument,
                         "https://example.com/")


class CommandDeliveryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / "outbox.sqlite3"
        self.store = decrumb.Store(self.path)
        self.addCleanup(lambda: self.store.close())
        self.now = decrumb.now_ms()
        self.config = {"phone_commands": {"enabled": True}, "settings": SETTINGS}
        self.cleaner = Mock(return_value=["https://example.com/"])

    def process(self, text="/decrumb status", timestamp=None, started_at=None):
        return phone_commands.process(command_event(self.now if timestamp is None else timestamp, text), ALIASES,
            self.store, self.config, self.cleaner, self.now, self.now if started_at is None else started_at)

    def body(self):
        return self.store.db.execute("SELECT body FROM outbox WHERE state='pending'").fetchone()[0]

    def test_default_off_and_strict_settings(self):
        self.assertEqual(phone_commands.normalize_settings(), {"enabled": False})
        for raw in (True, 1, {}, {"enabled": 1}, {"enabled": True, "shell": True}):
            with self.assertRaises(ValueError):
                phone_commands.normalize_settings(raw)
        self.config.pop("phone_commands")
        self.assertFalse(self.process())
        self.assertEqual(self.store.counts(), {})
        self.cleaner.assert_not_called()

    def test_status_and_help_are_fixed_content_only(self):
        self.assertTrue(self.process())
        self.assertIn("helper is running", self.body())
        self.assertNotIn(SELF, self.body())
        self.assertNotIn("synthetic-self", self.body())
        self.assertNotIn(self.temp.name, self.body())
        self.cleaner.assert_not_called()
        self.now += 1
        self.assertTrue(self.process("/decrumb help"))
        bodies = "\n".join(row[0] for row in self.store.db.execute("SELECT body FROM outbox"))
        self.assertIn("/decrumb clean <link>", bodies)

    def test_clean_uses_local_helper_and_standard_receipt_delivery(self):
        self.assertTrue(self.process("/decrumb clean https://example.com/?utm_source=synthetic"))
        self.cleaner.assert_called_once_with("https://example.com/?utm_source=synthetic")
        rpc = StubRpc({"timestamp": self.now, "results": [{"type": "SUCCESS"}]})
        self.assertTrue(decrumb.deliver_one(self.store, rpc, SELF))
        method, params = rpc.calls[0]
        self.assertEqual(method, "send")
        self.assertEqual(set(params), {"account", "noteToSelf", "message"})
        self.assertEqual((params["account"], params["noteToSelf"]), (SELF, True))
        self.assertIn("https://example.com/", params["message"])
        self.assertNotIn("utm_source", params["message"])
        self.assertEqual(self.store.db.execute("SELECT body FROM outbox").fetchone(), (None,))
        self.assertEqual(self.store.note_summary()["manageable"], 1)

    def test_no_change_is_a_fixed_reply_and_settings_are_not_overridden(self):
        self.config["settings"] = {"mode": "off"}
        self.cleaner.return_value = []
        self.assertTrue(self.process("/decrumb clean https://example.com/?secret=synthetic"))
        self.assertIn("No links changed", self.body())
        self.assertNotIn("secret", self.body())
        self.assertEqual(self.config["settings"], {"mode": "off"})

    def test_replay_is_deduplicated_durably_and_stopped_period_is_ignored(self):
        self.assertTrue(self.process())
        self.store.close()
        self.store = decrumb.Store(self.path)
        self.assertTrue(self.process())
        self.assertEqual(self.store.counts(), {"pending": 1})
        self.assertFalse(self.process(timestamp=self.now - 1))
        self.assertFalse(self.process(started_at=self.now + 1))

    def test_ambiguous_reply_is_not_retried(self):
        self.assertTrue(self.process())
        with self.assertRaises(decrumb.SafeError):
            decrumb.deliver_one(self.store, StubRpc(fail=True), SELF)
        self.assertEqual(self.store.counts(), {"uncertain": 1})
        self.assertFalse(decrumb.deliver_one(self.store, StubRpc(), SELF))
        self.assertTrue(self.process())
        self.assertEqual(self.store.counts(), {"uncertain": 1})

    def test_helper_failure_and_output_bounds(self):
        self.cleaner.side_effect = decrumb.SafeError("URL helper failed or settings are invalid.")
        with self.assertRaises(decrumb.SafeError):
            self.process("/decrumb clean https://example.com/")
        self.assertEqual(self.store.counts(), {})
        self.cleaner.side_effect = None
        self.cleaner.return_value = ["x" * 9000]
        self.assertTrue(self.process("/decrumb clean https://example.com/"))
        self.assertEqual(self.store.counts(), {})
        self.assertEqual(self.store.metrics()["oversize_dropped"], 1)

    def test_existing_queue_cap_still_applies(self):
        for index in range(256):
            self.store.enqueue(str(index), self.now, ["https://example.com/"])
        self.assertTrue(self.process())
        self.assertEqual(self.store.counts(), {"pending": 256})
        self.assertEqual(self.store.metrics()["outbox_dropped"], 1)


class RuleCommandTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.store = decrumb.Store(self.root / "outbox.sqlite3")
        self.addCleanup(lambda: self.store.close())
        self.config = {"version": 1, "account": SELF, "helper": str(HELPER),
                       "signal_cli": str(self.root / "fake-signal"), "paused": False,
                       "phone_commands": {"enabled": True},
                       "settings": {"mode": "all", "baseURLs": [], "excludedURLs": [],
                                    "rules": [{"site": "https://example.com", "remove": ["old"], "keep": []}]}}
        decrumb.write_json(self.root / "config.json", self.config)
        self.rules = decrumb.phone_rule_handler(self.root, self.config, self.store)
        self.now = max(decrumb.now_ms(), self.store.enabled_at)
        self.cleaner = lambda text: decrumb.clean(HELPER, text, self.config["settings"])

    def process(self, text, value=None):
        return phone_commands.process(value or command_event(self.now, text), ALIASES, self.store,
                                      self.config, self.cleaner, self.now, self.store.enabled_at,
                                      rules=self.rules)

    def body(self):
        return self.store.db.execute("SELECT body FROM outbox WHERE state='pending' ORDER BY timestamp DESC").fetchone()[0]

    def test_lists_installed_bundled_custom_protections_and_controls(self):
        self.config["settings"].update(mode="selected", baseURLs=["https://example.com"],
                                       excludedURLs=["https://example.com/private"])
        before = copy.deepcopy(self.config)
        self.assertTrue(self.process("/decrumb rules"))
        for value in ("Global remove: utm_source", "Protect entire signed link: signature",
                      "Bundled site: https://instagram.com", "Custom site: https://example.com",
                      "Remove: old", "Mode: selected", "Excluded site: https://example.com/private",
                      "Selected site: https://example.com", "Page 1/"):
            self.assertIn(value, self.body())
        self.assertEqual(self.config, before)
        self.assertEqual(self.store.db.execute("SELECT count(*) FROM phone_rule_changes").fetchone()[0], 0)

    @unittest.skipUnless(sys.platform == "darwin", "requires the Swift app helper layout")
    def test_packaged_mac_rules_are_read_from_resources(self):
        app = self.root / "Fixture.app/Contents"
        helper = app / "Helpers/url-cleaner"
        helper.parent.mkdir(parents=True)
        resources = app / "Resources"
        resources.mkdir()
        shutil.copy2(HELPER, helper)
        shutil.copy2(Path(decrumb.__file__).parent / "rules/defaults.json", resources / "rules.json")
        self.config["helper"] = str(helper)
        self.rules = decrumb.phone_rule_handler(self.root, self.config, self.store)
        self.assertFalse(helper.with_name("rules.json").exists())
        self.assertTrue(self.process("/decrumb rules"))
        self.assertIn("Global remove: utm_source", self.body())
        self.assertIn("Bundled site: https://instagram.com", self.body())

    def test_add_normalizes_merges_persists_and_cleans_immediately(self):
        before = copy.deepcopy(self.config)
        self.assertTrue(self.process("/decrumb rules add EXAMPLE.com/ SHARE_ID,ref"))
        self.assertIn("Rule added", self.body())
        expected = {"site":"https://example.com", "remove":["old", "share_id", "ref"], "keep":[]}
        self.assertEqual(self.config["settings"]["rules"], [expected])
        saved = json.loads((self.root / "config.json").read_bytes())
        self.assertEqual(saved, self.config)
        self.assertEqual({k:v for k,v in saved.items() if k != "settings"},
                         {k:v for k,v in before.items() if k != "settings"})
        self.assertEqual(self.cleaner("https://example.com/article?share_id=x&ref=y&id=42#menu"),
                         ["https://example.com/article?id=42#menu"])
        self.now += 1
        self.assertTrue(self.process("/decrumb clean https://example.com/article?share_id=x&id=42"))
        self.assertIn("https://example.com/article?id=42", self.body())
        self.assertNotIn("share_id", self.body())

    def test_add_preserves_scopes_and_signed_link_protection(self):
        self.assertTrue(self.process("/decrumb rules add example.com/news share_id"))
        self.assertEqual(self.cleaner("https://sub.example.com/news/a?share_id=x&item_id=42"),
                         ["https://sub.example.com/news/a?item_id=42"])
        for url in ("https://example.com/newsroom?share_id=x", "https://notexample.com/news?share_id=x",
                    "https://example.com/news?share_id=x&sig=synthetic"):
            self.assertEqual(self.cleaner(url), [])

    def test_invalid_rules_limits_and_keep_conflict_never_write(self):
        before = (self.root / "config.json").read_bytes()
        for command in ("/decrumb rules add", "/decrumb rules add *.example.com ref",
                        "/decrumb rules add https://example.com/?q=x ref",
                        "/decrumb rules add example.com .*", "/decrumb rules add example.com ref,,id",
                        "/decrumb rules add file:///etc/passwd ref",
                        "/decrumb rules add example.com " + " ".join("p" + str(i) for i in range(51))):
            with self.subTest(command=command):
                self.now += 1
                self.assertTrue(self.process(command))
                self.assertNotIn("Rule added", self.body())
                self.assertEqual((self.root / "config.json").read_bytes(), before)
        self.config["settings"]["rules"][0]["keep"] = ["ref"]
        self.now += 1
        self.assertTrue(self.process("/decrumb rules add example.com ref"))
        self.assertIn("keep rule", self.body())
        self.assertEqual((self.root / "config.json").read_bytes(), before)
        self.assertEqual(self.store.db.execute("SELECT count(*) FROM phone_rule_changes").fetchone()[0], 0)

    def test_peer_spoiler_and_disabled_commands_cannot_mutate_rules(self):
        before = (self.root / "config.json").read_bytes()
        forged = command_event(self.now, "/decrumb rules add example.com ref")
        forged["params"]["result"]["envelope"]["sourceNumber"] = PEER
        self.assertFalse(self.process("", value=forged))
        spoiler = command_event(self.now, "/decrumb rules add example.com ref")
        sent(spoiler)["textStyles"] = [{"style":"SPOILER"}]
        self.assertFalse(self.process("", value=spoiler))
        self.config["phone_commands"]["enabled"] = False
        self.assertFalse(self.process("/decrumb rules add example.com ref"))
        self.assertEqual((self.root / "config.json").read_bytes(), before)

    def test_queue_cancellation_reservations_and_restart_replay(self):
        self.store.enqueue("synthetic-old", self.now, ["https://example.com/"])
        self.assertTrue(self.process("/decrumb rules add example.com ref"))
        self.assertEqual(self.store.counts(), {"cancelled":1, "pending":1})
        self.store.clear_pending()
        self.store.close()
        self.store = decrumb.Store(self.root / "outbox.sqlite3")
        self.config = json.loads((self.root / "config.json").read_bytes())
        self.rules = decrumb.phone_rule_handler(self.root, self.config, self.store)
        self.assertTrue(self.process("/decrumb rules add example.com ref"))
        self.assertEqual(self.store.counts(), {"cancelled":2})
        self.assertEqual(self.store.db.execute("SELECT count(*) FROM phone_rule_changes").fetchone()[0], 1)
        self.now += 1
        self.assertTrue(self.process("/decrumb rules add example.com ref"))
        self.assertIn("already exists", self.body())

    def test_crash_after_save_cannot_reapply_or_cancel_later_notes(self):
        original = self.rules.save
        def crash(settings):
            original(settings)
            raise RuntimeError("synthetic crash after persistence")
        self.rules.save = crash
        with self.assertRaises(RuntimeError):
            self.process("/decrumb rules add example.com ref")
        self.store.enqueue("synthetic-later", self.now + 1, ["https://example.com/"])
        self.rules = decrumb.phone_rule_handler(self.root, self.config, self.store)
        self.assertTrue(self.process("/decrumb rules add example.com ref"))
        self.assertEqual(self.store.counts(), {"pending":1})
        self.assertEqual(self.body().splitlines()[1], "https://example.com/")

    def test_save_failure_gives_fixed_reply_and_fresh_command_can_retry(self):
        before = (self.root / "config.json").read_bytes()
        original = self.rules.save
        self.rules.save = Mock(side_effect=OSError("private synthetic error"))
        self.assertTrue(self.process("/decrumb rules add example.com ref"))
        self.assertIn("could not be saved", self.body())
        self.assertNotIn("private synthetic error", self.body())
        self.assertEqual((self.root / "config.json").read_bytes(), before)
        self.rules.save = original
        self.now += 1
        self.assertTrue(self.process("/decrumb rules add example.com ref"))
        self.assertIn("Rule added", self.body())

    def test_paginated_large_rule_lists_and_invalid_pages_are_bounded(self):
        self.config["settings"]["rules"] = [
            {"site":"https://site" + str(i) + ".example.com",
             "remove":["field_" + str(n) for n in range(50)], "keep":[]} for i in range(100)]
        pages = self.rules._pages(self.config)
        self.assertGreater(len(pages), 1)
        combined = ""
        for page in range(1, len(pages) + 1):
            self.now += 1
            self.assertTrue(self.process("/decrumb rules " + str(page)))
            body = self.body()
            self.assertLess(len(body.encode()), 8192)
            combined += body
        self.assertIn("site99.example.com", combined)
        for page in ("0", "999999999999999999999999999999999999", "-1", "2 extra"):
            self.now += 1
            self.assertTrue(self.process("/decrumb rules " + page))
            self.assertLess(len(self.body().encode()), 8192)


class AppPhonePreferenceTests(unittest.TestCase):
    def test_app_apply_saves_opt_in_and_restarts_only_active_worker(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            config = {"version": 1, "helper": str(HELPER), "signal_cli": str(root / "fake-signal"),
                      "account": SELF, "settings": SETTINGS, "paused": False}
            decrumb.write_json(root / "config.json", config)
            control = Mock()
            args = ["desktop.py", "--root", str(root), "--resources", str(HELPER.parent.resolve()), "apply"]
            with patch.object(sys, "argv", args), patch.object(desktop, "request", return_value={
                "settings": SETTINGS, "phone_commands": {"enabled": True}}), \
                patch.object(service, "Service", return_value=control), patch.object(service, "configure_app_login"), \
                patch("sys.stdout", new_callable=io.StringIO) as output:
                desktop.main()
            self.assertTrue(json.loads(output.getvalue())["phone_commands_enabled"])
            self.assertEqual(decrumb.load_config(root)["phone_commands"], {"enabled": True})
            control.stop.assert_called_once_with(disable_login=True)
            control.start.assert_called_once_with(False)


class CommandTransportTests(unittest.TestCase):
    def test_full_worker_rejects_forged_messages_echo_loops_and_replay_after_restart(self):
        self.run_transport(enabled=True, restart=True)

    def test_full_worker_default_off_never_replies(self):
        self.run_transport(enabled=False)

    def test_full_worker_no_change_is_a_fixed_reply(self):
        self.run_transport(enabled=True, command="/decrumb clean https://example.com/?page=2", expected="No links changed")

    def test_full_worker_helper_failure_does_not_stop_next_command(self):
        self.run_transport(enabled=True, failing_helper=True)

    def test_full_worker_cleans_disappearing_command_and_deduplicates_reply(self):
        self.run_transport(enabled=True, restart=True, expires=60,
            command="/decrumb clean https://x.com/example/status/1234567890?s=46&t=synthetic_share_token",
            expected="Decrumb\nhttps://x.com/example/status/1234567890\n#decrumb_")

    def test_full_worker_adds_rules_persists_and_rejects_forgery_and_replay(self):
        self.run_transport(enabled=True, restart=True,
                           command="/decrumb rules add example.com share_id", expected="Rule added")

    def test_full_worker_lists_bundled_and_custom_rules(self):
        self.run_transport(enabled=True, command="/decrumb rules", expected="Global remove: utm_source")

    def run_transport(self, enabled, restart=False, command="/decrumb status", expected="helper is running", failing_helper=False, expires=0):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            valid = command_event(0, command, expires=expires)
            invalid = []
            peer = copy.deepcopy(valid)
            peer["params"]["result"]["envelope"]["sourceNumber"] = PEER
            invalid.append(peer)
            elsewhere = copy.deepcopy(valid)
            sent(elsewhere)["destinationNumber"] = PEER
            invalid.append(elsewhere)
            for key, value in (("groupInfo", {}), ("expiresInSeconds", -1), ("viewOnce", True),
                               ("textStyles", [{"style": "SPOILER"}])):
                bad = copy.deepcopy(valid)
                sent(bad)[key] = value
                invalid.append(bad)
            invalid.append(event(0, "/decrumb status"))
            if failing_helper:
                invalid.append(command_event(0, "/decrumb clean https://example.com/?utm_source=x"))
            fake = root / "fake-signal"
            script = '''#!PYTHON
import json,sys,time
from pathlib import Path
root=Path(__file__).parent
for line in sys.stdin:
 r=json.loads(line); method=r['method']; result={}
 if method=='listAccounts': result=[{'number':SELF}]
 elif method=='listContacts':
  assert r['params']=={'account':SELF,'recipient':[SELF],'allRecipients':True}
  result=[{'number':SELF,'uuid':'00000000-0000-4000-8000-000000000001'}]
 elif method=='subscribeReceive': result=0
 elif method=='send':
  with (root/'calls.jsonl').open('a') as output: output.write(json.dumps(r)+'\\n')
  result={'timestamp':int(time.time()*1000),'results':[{'type':'SUCCESS'}]}
 print(json.dumps({'jsonrpc':'2.0','id':r['id'],'result':result}),flush=True)
 if method=='subscribeReceive':
  timestamp_file=root/'event-time'
  timestamp=int(timestamp_file.read_text()) if timestamp_file.exists() else int(time.time()*1000)
  timestamp_file.write_text(str(timestamp))
  for item in EVENTS:
   envelope=item['params']['result']['envelope']
   data=envelope.get('dataMessage') or envelope['syncMessage']['sentMessage']
   data['timestamp']=timestamp
   print(json.dumps(item),flush=True)
  (root/'ready').write_text('ready')
 if method=='send':
  item=ECHO
  item['params']['result']['envelope']['syncMessage']['sentMessage'].update(message=r['params']['message'],timestamp=int(time.time()*1000))
  print(json.dumps(item),flush=True)
'''.replace("PYTHON", sys.executable).replace("SELF", repr(SELF)).replace("EVENTS", repr(invalid + [valid, valid])).replace("ECHO", repr(valid))
            fake.write_text(script)
            fake.chmod(0o700)
            helper = HELPER
            if failing_helper:
                helper = root / 'fake-cleaner'
                helper.write_text('#!' + sys.executable + '\nimport json,sys\nvalue=json.load(sys.stdin)\n'
                                  'if value["text"]: sys.exit(1)\nprint(json.dumps({"urls": []}))\n')
                helper.chmod(0o700)
            config = {"version": 1, "helper": str(helper), "signal_cli": str(fake), "account": SELF,
                      "settings": SETTINGS}
            if enabled:
                config["phone_commands"] = {"enabled": True}
            decrumb.write_json(root / "config.json", config)
            process = subprocess.Popen([sys.executable, "-B", str(Path(decrumb.__file__)), "--root", str(root), "run"],
                                       stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            try:
                deadline = time.monotonic() + 10
                target = root / ("calls.jsonl" if enabled else "ready")
                while not target.exists() and process.poll() is None and time.monotonic() < deadline:
                    time.sleep(0.05)
                self.assertTrue(target.exists(), "Synthetic command transport did not become ready")
                # Let every already-buffered invalid, duplicate and generated-echo
                # event be processed before stopping the fixture worker.
                time.sleep(0.7)
            finally:
                process.terminate()
                stdout, stderr = process.communicate(timeout=10)
            self.assertEqual(process.returncode, 0)
            self.assertEqual(stdout + stderr, b"")
            if enabled:
                calls = [json.loads(line) for line in (root / "calls.jsonl").read_text().splitlines()]
                self.assertEqual(len(calls), 1)
                self.assertEqual(set(calls[0]["params"]), {"account", "noteToSelf", "message"})
                self.assertEqual((calls[0]["params"]["account"], calls[0]["params"]["noteToSelf"]), (SELF, True))
                self.assertIn(expected, calls[0]["params"]["message"])
                if command.startswith("/decrumb rules add "):
                    saved = decrumb.load_config(root)
                    self.assertEqual(saved["settings"]["rules"],
                                     [{"site":"https://example.com", "remove":["share_id"], "keep":[]}])
                    self.assertEqual(decrumb.clean(HELPER, "https://example.com/?share_id=x&id=42", saved["settings"]),
                                     ["https://example.com/?id=42"])
            else:
                self.assertFalse((root / "calls.jsonl").exists())
            with contextlib.closing(decrumb.Store(root / "outbox.sqlite3")) as store:
                self.assertEqual(store.counts(), {"sent": 1} if enabled else {})
                if failing_helper:
                    self.assertEqual(store.metrics()["helper_failures"], 1)
            if restart:
                (root / 'ready').unlink()
                process = subprocess.Popen([sys.executable, "-B", str(Path(decrumb.__file__)), "--root", str(root), "run"],
                                           stdout=subprocess.PIPE, stderr=subprocess.PIPE)
                try:
                    deadline = time.monotonic() + 10
                    while not (root / 'ready').exists() and process.poll() is None and time.monotonic() < deadline:
                        time.sleep(0.05)
                    self.assertTrue((root / 'ready').exists())
                    time.sleep(0.7)
                finally:
                    process.terminate()
                    stdout, stderr = process.communicate(timeout=10)
                self.assertEqual(process.returncode, 0)
                self.assertEqual(stdout + stderr, b'')
                self.assertEqual(len((root / 'calls.jsonl').read_text().splitlines()), 1)
            self.assertNotIn(SELF, (root / "worker.log").read_text())
            self.assertNotIn(PEER, (root / "worker.log").read_text())


if __name__ == "__main__":
    unittest.main()
