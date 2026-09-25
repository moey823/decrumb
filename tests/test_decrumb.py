# SPDX-License-Identifier: AGPL-3.0-only
"""Offline tests only. No Signal account, remote service, or private messages."""
import copy
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import threading
import time
import unittest

import decrumb

HELPER = Path(os.environ.get("DECRUMB_TEST_HELPER", str(
    Path(__file__).resolve().parents[1] / "build/url-cleaner"
)))
SETTINGS = {"mode": "all", "baseURLs": []}
SAMPLE = "https://www.instagram.com/reel/ExampleCode/?utm_source=ig_web_copy_link&stkn=abc=="
CLEAN = "https://www.instagram.com/reel/ExampleCode/"
SELF = "+15550000001"
PEER = "+15550000002"


def event(timestamp, text=SAMPLE):
    return {"jsonrpc": "2.0", "method": "receive", "params": {"subscription": 0, "result": {
        "account": SELF, "envelope": {
            "sourceUuid": "synthetic-peer-uuid", "sourceNumber": PEER,
            "timestamp": timestamp, "dataMessage": {
                "timestamp": timestamp, "message": text, "expiresInSeconds": 0,
                "viewOnce": False, "textStyles": [],
            },
        },
    }}}


class CleanerTests(unittest.TestCase):
    def test_cleaner_contract(self):
        cases = [
            (SAMPLE, [CLEAN]),
            ("Look 👋 (" + SAMPLE + ").", [CLEAN]),
            (SAMPLE + "\n" + SAMPLE, [CLEAN]),
            ("https://example.com/?utm_source=a&id=1&id=2#yes", ["https://example.com/?id=1&id=2#yes"]),
            ("https://example.com/?q=a%2Bb&fbclid=bad&x=%26", ["https://example.com/?q=a%2Bb&x=%26"]),
            ("https://example.com/?%75tm_source=x&UTM_MEDIUM=share", ["https://example.com/"]),
            ("https://example.com/?sig=secret&utm_source=x", []),
            ("https://example.com/?X-Amz-Signature=secret&utm_source=x", []),
            ("https://example.com/?stkn=abc==", []),
            ("https://notinstagram.com/?stkn=abc==", []),
            ("https://instagram.com.evil.example/?stkn=abc==", []),
            ("https://instagram.com/p/a?igsh=abc&img_index=2", ["https://instagram.com/p/a?img_index=2"]),
            ("https://x.com/example/status/1234567890?s=46&t=synthetic_share_token", ["https://x.com/example/status/1234567890"]),
            ("www.instagram.com/reel/a/?stkn=abc==", ["http://www.instagram.com/reel/a/"]),
            ("https://example.com/?page=3", []),
            ("mailto:hello@example.com?utm_source=x", []),
            ("No links here", []),
        ]
        for text, expected in cases:
            with self.subTest(text=text):
                self.assertEqual(decrumb.clean(HELPER, text, SETTINGS), expected)

    def test_selected_and_off(self):
        chosen = {"mode": "selected", "baseURLs": ["example.com/news"]}
        self.assertEqual(decrumb.clean(HELPER, "https://sub.example.com/news/a?utm_source=x", chosen), ["https://sub.example.com/news/a"])
        for url in ("https://example.com/newsroom?utm_source=x", "https://notexample.com/news?utm_source=x", "https://example.com:8000/news?utm_source=x"):
            self.assertEqual(decrumb.clean(HELPER, url, chosen), [])
        self.assertEqual(decrumb.clean(HELPER, SAMPLE, {"mode": "off", "baseURLs": []}), [])
        self.assertEqual(decrumb.clean(HELPER, SAMPLE, {"mode": "selected", "baseURLs": []}), [])
        with self.assertRaises(decrumb.SafeError):
            decrumb.clean(HELPER, SAMPLE, {"mode": "selected", "baseURLs": ["*.instagram.com"]})

    def test_private_input_not_in_errors(self):
        result = subprocess.run([str(HELPER)], input=b'{"secret":"private-body"}', capture_output=True)
        self.assertNotEqual(result.returncode, 0)
        self.assertNotIn(b"private-body", result.stdout + result.stderr)

    def test_qr_generator(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "qr.png"
            result = subprocess.run([str(HELPER), "--qr", str(path)], input=b"sgnl://linkdevice?uuid=synthetic&pub_key=synthetic", capture_output=True)
            self.assertEqual(result.returncode, 0)
            self.assertTrue(path.read_bytes().startswith(b"\x89PNG\r\n\x1a\n"))


class FilteringTests(unittest.TestCase):
    def setUp(self):
        self.now = decrumb.now_ms()
        self.value = event(self.now)

    def accept(self, value):
        return decrumb.candidate(value, {SELF, "self-uuid"}, self.now - 1000, self.now)

    def test_receive_shapes(self):
        result = self.accept(self.value)
        self.assertEqual(result[1:], (self.now, SAMPLE))
        direct = {"method": "receive", "params": self.value["params"]["result"]}
        self.assertEqual(result, self.accept(direct))
        self.assertNotIn(PEER, result[0])
        self.assertNotIn("synthetic-peer-uuid", result[0])

    def test_private_and_control_messages_skipped(self):
        for key, value in [
            ("expiresInSeconds", 60), ("expiresInSeconds", None), ("expiresInSeconds", "0"),
            ("viewOnce", True), ("isExpirationUpdate", True), ("isEndSession", True),
            ("reaction", {"emoji": "👍"}), ("remoteDelete", {"timestamp": 123}),
            ("storyContext", {"timestamp": 123}), ("pollCreate", {"question": "q"}),
            ("textStyles", [{"style": "SPOILER", "start": 0, "length": 8}]),
            ("textStyles", [None]), ("message", "no tracking here"),
            ("message", "?" * 65537), ("timestamp", "wrong"),
        ]:
            with self.subTest(key=key, value=value if key != "message" else "omitted"):
                changed = copy.deepcopy(self.value)
                changed["params"]["result"]["envelope"]["dataMessage"][key] = value
                self.assertIsNone(self.accept(changed))

    def test_loop_and_account_protection(self):
        for key, value in [("syncMessage", {"sentMessage": {"message": SAMPLE}}), ("sourceNumber", SELF), ("sourceUuid", "self-uuid"), ("editMessage", {"targetSentTimestamp": 123})]:
            changed = copy.deepcopy(self.value)
            changed["params"]["result"]["envelope"][key] = value
            self.assertIsNone(self.accept(changed))
        self.value["params"]["result"]["account"] = PEER
        self.assertIsNone(self.accept(self.value))

    def test_history_and_future_skipped(self):
        for timestamp in (self.now - 1001, self.now + 300001, self.now - 2 * decrumb.MAX_AGE_MS):
            self.assertIsNone(self.accept(event(timestamp)))

    def test_malformed_events(self):
        for value in (None, [], {}, {"method": "receive", "params": None}, {"method": "receive", "params": {"result": []}}):
            self.assertIsNone(self.accept(value))

    def test_old_and_new_account_schema(self):
        self.assertEqual(decrumb.account_details([{"number": SELF}]), (SELF, {SELF}))
        self.assertEqual(decrumb.account_details([{"number": SELF, "aci": "self-uuid"}]), (SELF, {SELF, "self-uuid"}))
        with self.assertRaises(decrumb.SafeError):
            decrumb.account_details([{"number": SELF}, {"number": PEER}])


class StubRpc:
    def __init__(self, response=None, fail=False):
        self.calls = []
        self.response = response or {"timestamp": 123, "results": [{"type": "SUCCESS"}]}
        self.fail = fail

    def call(self, method, params):
        self.calls.append((method, params))
        if self.fail:
            raise decrumb.SafeError("Signal command timed out.")
        return self.response


class OutboxTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.path = Path(self.temp.name) / "outbox.sqlite3"
        self.store = decrumb.Store(self.path)

    def tearDown(self):
        self.store.close()
        self.temp.cleanup()

    def test_note_to_self_only_and_deduplicated_across_restarts(self):
        self.assertTrue(self.store.enqueue("id", decrumb.now_ms(), [CLEAN]))
        rpc = StubRpc()
        self.assertTrue(decrumb.deliver_one(self.store, rpc, SELF))
        self.assertEqual(len(rpc.calls), 1)
        method, params = rpc.calls[0]
        self.assertEqual((method, params["account"], params["noteToSelf"]), ("send", SELF, True))
        self.assertRegex(params["message"], r"^Decrumb\n" + __import__('re').escape(CLEAN) + r"\n#decrumb_[0-9a-f]{24}$")
        self.assertFalse(decrumb.deliver_one(self.store, rpc, SELF))
        self.store.close()
        self.store = decrumb.Store(self.path)
        self.assertFalse(self.store.enqueue("id", decrumb.now_ms(), [CLEAN]))
        self.assertEqual(self.store.db.execute("SELECT state,body FROM outbox").fetchone(), ("sent", None))
        self.assertNotIn(b"utm_source", self.path.read_bytes())
        self.assertNotIn(CLEAN.encode(), self.path.read_bytes())

    def test_unconfirmed_send_not_retried(self):
        self.store.enqueue("id", decrumb.now_ms(), [CLEAN])
        rpc = StubRpc(fail=True)
        with self.assertRaises(decrumb.SafeError):
            decrumb.deliver_one(self.store, rpc, SELF)
        self.assertFalse(decrumb.deliver_one(self.store, rpc, SELF))
        self.assertEqual(len(rpc.calls), 1)
        self.assertEqual(self.store.counts(), {"uncertain": 1})

    def test_upstream_failure_result_not_success(self):
        self.store.enqueue("id", decrumb.now_ms(), [CLEAN])
        with self.assertRaises(decrumb.SafeError):
            decrumb.deliver_one(self.store, StubRpc({"timestamp": 123, "results": [{"type": "NETWORK_FAILURE"}]}), SELF)
        self.assertEqual(self.store.counts(), {"uncertain": 1})

    def test_crash_during_send_is_not_replayed(self):
        self.store.enqueue("id", decrumb.now_ms(), [CLEAN])
        with self.store.db:
            self.store.db.execute("UPDATE outbox SET state='inflight'")
        enabled_at = self.store.enabled_at
        self.store.close()
        self.store = decrumb.Store(self.path)
        self.assertEqual(self.store.enabled_at, enabled_at)
        self.assertEqual(self.store.counts(), {"uncertain": 1})
        self.assertFalse(decrumb.deliver_one(self.store, StubRpc(), SELF))

    def test_queue_age_and_bound(self):
        self.store.enqueue("old", decrumb.now_ms() - decrumb.MAX_AGE_MS - 1, [CLEAN])
        self.store.expire(decrumb.now_ms())
        self.assertEqual(self.store.counts(), {"expired": 1})
        for i in range(256):
            self.assertTrue(self.store.enqueue(str(i), decrumb.now_ms(), [CLEAN]))
        self.assertFalse(self.store.enqueue("overflow", decrumb.now_ms(), [CLEAN]))


class TransportTests(unittest.TestCase):
    def test_upstream_error_details_are_private(self):
        script = '''import sys,json
for line in sys.stdin:
 r=json.loads(line)
 print(json.dumps({"id":r["id"],"error":{"code":-1,"message":"private-body +15550000001"}}),flush=True)
'''
        with tempfile.TemporaryDirectory() as folder:
            with decrumb.Rpc(Path(folder), {}, [sys.executable, "-c", script]) as rpc:
                with self.assertRaises(decrumb.SafeError) as error:
                    rpc.call("finishLink", timeout=3)
                self.assertEqual(str(error.exception), "Signal command failed (code -1).")

    def test_shutdown_interrupts_a_stalled_command(self):
        stopped = threading.Event()
        with tempfile.TemporaryDirectory() as folder:
            with decrumb.Rpc(Path(folder), {}, [sys.executable, "-c", "import time; time.sleep(60)"], stopped) as rpc:
                stopped.set()
                start = time.monotonic()
                with self.assertRaises(decrumb.SafeError):
                    rpc.call("test", timeout=60)
                self.assertLess(time.monotonic() - start, 1)

    def test_real_stdio_routes_events_and_responses(self):
        script = '''import sys,json,time
for line in sys.stdin:
 r=json.loads(line)
 print(json.dumps({"method":"receive","params":{"envelope":{}}}),flush=True)
 print(json.dumps({"jsonrpc":"2.0","id":r["id"],"result":{"ok":True}}),flush=True)
'''
        with tempfile.TemporaryDirectory() as folder:
            with decrumb.Rpc(Path(folder), {}, [sys.executable, "-c", script]) as rpc:
                self.assertEqual(rpc.call("test", timeout=3), {"ok": True})
                self.assertEqual(rpc.events.get(timeout=1)["method"], "receive")
            self.assertIsNotNone(rpc.process.poll())

    def test_closed_transport_fails_promptly(self):
        with tempfile.TemporaryDirectory() as folder:
            with decrumb.Rpc(Path(folder), {}, [sys.executable, "-c", "pass"]) as rpc:
                start = time.monotonic()
                with self.assertRaises(decrumb.SafeError):
                    rpc.call("test", timeout=10)
                self.assertLess(time.monotonic() - start, 3)

    def test_full_worker_with_fake_signal_server(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            fake = root / "fake-signal"
            script = '''#!PYTHON
import sys,json,time
from pathlib import Path
root=Path(__file__).parent
for line in sys.stdin:
 r=json.loads(line); method=r['method']; result={}
 if method=='listAccounts': result=[{'number':'SELF'}]
 elif method=='subscribeReceive': result=0
 elif method=='send':
  (root/'test-only-calls.json').write_text(json.dumps(r))
  result={'timestamp':123,'results':[{'type':'SUCCESS'}]}
 print(json.dumps({'jsonrpc':'2.0','id':r['id'],'result':result}),flush=True)
 if method=='subscribeReceive':
  e=EVENT
  e['params']['result']['envelope']['dataMessage']['timestamp']=int(time.time()*1000)
  print(json.dumps(e),flush=True)
  print(json.dumps(e),flush=True)
'''.replace("PYTHON", sys.executable).replace("'SELF'", repr(SELF)).replace("EVENT", repr(event(0)))
            fake.write_text(script)
            fake.chmod(0o700)
            decrumb.write_json(root / "config.json", {"version": 1, "signal_cli": str(fake), "helper": str(HELPER), "account": SELF, "settings": SETTINGS})
            process = subprocess.Popen([sys.executable, str(Path(decrumb.__file__)), "--root", str(root), "run"], stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            try:
                deadline = time.monotonic() + 12
                calls = root / "test-only-calls.json"
                while not calls.exists() and time.monotonic() < deadline and process.poll() is None:
                    time.sleep(0.05)
                self.assertTrue(calls.exists(), "Worker did not send the synthetic cleaned link")
                payload = json.loads(calls.read_text())["params"]
                self.assertEqual(set(payload), {"account", "noteToSelf", "message"})
                self.assertEqual((payload["account"], payload["noteToSelf"]), (SELF, True))
                self.assertRegex(payload["message"], r"^Decrumb\n" + __import__('re').escape(CLEAN) + r"\n#decrumb_[0-9a-f]{24}$")
            finally:
                process.terminate()
                stdout, stderr = process.communicate(timeout=10)
            self.assertEqual(process.returncode, 0)
            self.assertEqual(stdout + stderr, b"")
            status = json.loads((root / "status.json").read_text())
            self.assertEqual(status["counts"], {"sent": 1})
            log = (root / "worker.log").read_text()
            self.assertNotIn("instagram", log)
            self.assertNotIn(SELF, log)
            self.assertNotIn(PEER, log)
            self.assertEqual((root / "config.json").stat().st_mode & 0o777, 0o600)


if __name__ == "__main__":
    unittest.main(verbosity=2)
