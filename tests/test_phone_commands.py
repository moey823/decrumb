# SPDX-License-Identifier: AGPL-3.0-only
"""Synthetic owner-command security, persistence, app bridge and transport tests."""
import contextlib
import copy
import io
import json
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


def command_event(timestamp, text="/decrumb status"):
    return {"method": "receive", "params": {"result": {"account": SELF, "envelope": {
        "source": SELF, "sourceNumber": SELF, "sourceUuid": "00000000-0000-4000-8000-000000000001",
        "syncMessage": {"sentMessage": {
            "destination": SELF, "destinationNumber": SELF, "destinationUuid": "00000000-0000-4000-8000-000000000001",
            "timestamp": timestamp, "message": text, "expiresInSeconds": 0,
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
                                ("/decrumb status", "status"), ("/decrumb clean https://example.com/?utm_source=x", "clean")):
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
            ("expiresInSeconds", None), ("expiresInSeconds", 60), ("expiresInSeconds", "0"),
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

    def run_transport(self, enabled, restart=False, command="/decrumb status", expected="helper is running", failing_helper=False):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            valid = command_event(0, command)
            invalid = []
            peer = copy.deepcopy(valid)
            peer["params"]["result"]["envelope"]["sourceNumber"] = PEER
            invalid.append(peer)
            elsewhere = copy.deepcopy(valid)
            sent(elsewhere)["destinationNumber"] = PEER
            invalid.append(elsewhere)
            for key, value in (("groupInfo", {}), ("expiresInSeconds", 60), ("viewOnce", True),
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
