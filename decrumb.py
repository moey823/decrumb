#!/usr/bin/env python3
# SPDX-License-Identifier: AGPL-3.0-only
"""Private linked-device worker. The only send destination is Note to Self."""
import argparse
import contextlib
import hashlib
import json
import logging
import os
from pathlib import Path
import queue
import signal
import sqlite3
import subprocess
import sys
import threading
import time
import uuid

import notes
import phone_commands
import diagnostics
import runtime_platform as runtime
from notes import read_notes

def default_root():
    if sys.platform == "win32":
        configured = os.environ.get("LOCALAPPDATA")
        if not configured or not Path(configured).is_absolute():
            raise RuntimeError("Windows local application data directory is unavailable.")
        return Path(configured) / "Decrumb"
    if sys.platform == "darwin":
        return Path.home() / "Library/Application Support/Decrumb"
    configured = os.environ.get("XDG_STATE_HOME")
    base = Path(configured) if configured and Path(configured).is_absolute() else Path.home() / ".local/state"
    return base / "decrumb"


DEFAULT_ROOT = default_root()
MAX_AGE_MS = 24 * 60 * 60 * 1000
LOG = logging.getLogger("decrumb")
LOG.addHandler(logging.NullHandler())


class SafeError(Exception):
    """Only fixed, content-free messages may cross the CLI/log boundary."""
    def __init__(self, message, diagnostic_code='operation_failed'):
        super().__init__(message)
        self.diagnostic_code = diagnostic_code

class NotDispatched(SafeError):
    """Cancellation occurred before any request bytes were written."""


def notes_settings(raw=None):
    try:
        return notes.normalize_settings(raw)
    except ValueError:
        raise SafeError("Invalid generated-note settings.") from None


def now_ms():
    return int(time.time() * 1000)


def write_json(path, value):
    temporary = path.with_suffix(".tmp")
    with temporary.open("w", encoding="utf-8") as output:
        runtime.private_mode(temporary)
        json.dump(value, output, indent=2)
        output.write("\n")
        output.flush()
        os.fsync(output.fileno())
    temporary.replace(path)


@contextlib.contextmanager
def exclusive(root):
    with (root / "worker.lock").open("a") as lock:
        try:
            runtime.lock_file(lock)
        except BlockingIOError:
            raise SafeError("Worker or pairing is already running.") from None
        yield


def clean_result(helper, text, settings):
    try:
        result = subprocess.run(
            runtime.helper_command(helper), input=json.dumps({"text": text, "settings": settings}).encode(),
            stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, timeout=10, check=True,
            **runtime.child_options(),
        )
        value = json.loads(result.stdout)
        urls = value["urls"]
        if not isinstance(urls, list) or not all(isinstance(x, str) for x in urls):
            raise ValueError()
        return value
    except (OSError, subprocess.SubprocessError, ValueError, KeyError):
        raise SafeError("URL helper failed or settings are invalid.", 'helper_failed') from None

def clean(helper, text, settings):
    return clean_result(helper, text, settings)["urls"]


def load_config(root, validate_helper=True):
    try:
        config = json.loads((root / "config.json").read_text())
        if config["version"] != 1 or not isinstance(config["settings"], dict):
            raise ValueError()
        if not all(Path(config[k]).is_absolute() for k in ("signal_cli", "helper")):
            raise ValueError()
        if validate_helper:
            clean(config["helper"], "", config["settings"])
        config["notes"] = notes_settings(config.get("notes"))
        config["phone_commands"] = phone_commands.normalize_settings(config.get("phone_commands"))
        return config
    except (OSError, KeyError, TypeError, ValueError):
        raise SafeError("Missing or invalid configuration. Run init first.", 'configuration_failed') from None


class Rpc:
    """One local stdio transport, with bounded receive buffering and no raw logs."""
    def __init__(self, root, config, command=None, cancel_event=None):
        self.pending = {}
        self.mutex = threading.Lock()
        self.events = queue.Queue(maxsize=256)
        self.closed = threading.Event()
        self.cancel_event = cancel_event
        self.dropped_events = 0
        if command is None:
            prefix = runtime.helper_command(config["signal_cli"])
            if sys.platform == 'win32' and config.get('java'):
                bridge = (Path(sys.executable).with_name('decrumb-signal.exe') if getattr(sys, 'frozen', False)
                          else Path(__file__).with_name('windows_signal.py'))
                prefix = runtime.helper_command(bridge) + [
                    '--java', config['java'], '--temporary', str(root / 'tmp'),
                    '--libraries', str(Path(config['signal_cli']).parent.parent / 'lib' / '*'), '--']
            command = prefix + ["--config", str(root / "signal-cli"),
                                "--scrub-log", "--disable-send-log", "jsonRpc", "--receive-mode", "manual",
                                "--ignore-attachments", "--ignore-stories", "--ignore-avatars", "--ignore-stickers"]
        environment = dict(os.environ)
        if sys.platform != 'win32':
            environment["PATH"] = ("/opt/homebrew/bin:" if sys.platform == "darwin" else "") + "/usr/bin:/bin:/usr/sbin:/sbin"
        else:
            for key in ('JAVA_TOOL_OPTIONS', 'JDK_JAVA_OPTIONS', '_JAVA_OPTIONS', 'CLASSPATH'):
                environment.pop(key, None)
            environment['TEMP'] = environment['TMP'] = str(root / 'tmp')
        # The container supervisor owns one group per worker so a forced stop
        # also stops its native child. Desktop/Pi retain independent RPC groups.
        self.own_process_group = sys.platform != 'win32' and environment.get("DECRUMB_INHERIT_PROCESS_GROUP") != "1"
        try:
            self.process = subprocess.Popen(
                command, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
                env=environment, start_new_session=self.own_process_group,
                **runtime.child_options(),
            )
        except OSError:
            raise SafeError("Signal connection failed.", 'connection_failed') from None
        self.reader = threading.Thread(target=self._read, daemon=True)
        self.reader.start()

    def _read(self):
        try:
            while True:
                line = self.process.stdout.readline(4 * 1024 * 1024 + 1)
                if not line:
                    break
                if len(line) > 4 * 1024 * 1024:
                    LOG.error("rpc_oversize")
                    break
                value = json.loads(line)
                if not isinstance(value, dict):
                    raise ValueError()
                if "id" in value:
                    with self.mutex:
                        waiting = self.pending.get(value["id"])
                    if waiting:
                        waiting.put_nowait(value)
                elif value.get("method") == "receive":
                    try:
                        self.events.put_nowait(value)
                    except queue.Full:
                        with self.mutex:
                            self.dropped_events += 1
                        LOG.error("receive_buffer_full")
        except (ValueError, TypeError, OSError, queue.Full):
            LOG.error("rpc_reader_failed")
        finally:
            self.closed.set()

    def call(self, method, params=None, timeout=60):
        request_id = str(uuid.uuid4())
        waiting = queue.Queue(maxsize=1)
        with self.mutex:
            self.pending[request_id] = waiting
        try:
            data = json.dumps({"jsonrpc": "2.0", "id": request_id,
                               "method": method, "params": params or {}}).encode() + b"\n"
            if self.cancel_event is not None and self.cancel_event.is_set():
                raise NotDispatched("Signal command interrupted before dispatch.")
            self.process.stdin.write(data)
            self.process.stdin.flush()
            deadline = time.monotonic() + timeout
            while time.monotonic() < deadline:
                if self.cancel_event is not None and self.cancel_event.is_set():
                    raise SafeError("Signal command interrupted.", 'signal_command_interrupted')
                try:
                    response = waiting.get(timeout=min(0.5, max(0.01, deadline - time.monotonic())))
                    if "error" in response or "result" not in response:
                        error = response.get("error")
                        code = error.get("code") if isinstance(error, dict) else None
                        if method == "finishLink" and isinstance(error, dict):
                            # Match fixed upstream text, never echo an arbitrary error message.
                            if error.get("message") == "Link request timed out, please try again.":
                                raise SafeError("Pairing code expired. Generate a new code to try again.", 'pairing_expired')
                        # Error strings can contain identifiers. Show only JSON-RPC's numeric code.
                        detail = " (code " + str(code) + ")" if type(code) is int else ""
                        raise SafeError("Signal command failed" + detail + ".", 'signal_command_failed')
                    return response["result"]
                except queue.Empty:
                    if self.closed.is_set():
                        raise SafeError("Signal connection closed.", 'connection_closed') from None
            raise SafeError("Signal command timed out.", 'connection_timeout')
        except (OSError, ValueError):
            raise SafeError("Signal connection failed.", 'connection_failed') from None
        finally:
            with self.mutex:
                self.pending.pop(request_id, None)

    def close(self):
        def stop(sig):
            if sys.platform == 'win32':
                self.process.terminate()
            elif self.own_process_group:
                os.killpg(self.process.pid, sig)
            else:
                self.process.send_signal(sig)
        try:
            if self.process.poll() is None:
                stop(signal.SIGTERM)
            self.process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            stop(getattr(signal, 'SIGKILL', signal.SIGTERM))
            self.process.wait(timeout=5)
        except ProcessLookupError:
            self.process.wait(timeout=5)
        for pipe in (self.process.stdin, self.process.stdout):
            pipe.close()
        self.reader.join(timeout=2)

    def __enter__(self):
        return self

    def __exit__(self, *_):
        self.close()


def account_details(result):
    # 0.14.1 returns number only; newer builds also supply aci.
    if not isinstance(result, list) or len(result) != 1 or not isinstance(result[0], dict):
        raise SafeError("Expected exactly one linked account in the dedicated directory.")
    aliases = {v for k, v in result[0].items() if k in ("number", "aci") and isinstance(v, str) and v}
    account = result[0].get("number") or result[0].get("aci")
    if not aliases or not isinstance(account, str):
        raise SafeError("Linked account identity is unavailable.")
    return account, aliases


def command_aliases(rpc, account, aliases):
    """Resolve our UUID from Signal's own recipient store, never a received event.

    The pinned 0.14.8 listAccounts response contains only a phone number. Real
    self-sync envelopes also carry a UUID, and every supplied identity must match.
    Restrict the lookup to our account; discard names and all other profile data.
    """
    result = rpc.call("listContacts", {"account": account, "recipient": [account], "allRecipients": True})
    try:
        if not isinstance(result, list) or len(result) != 1 or not isinstance(result[0], dict):
            raise ValueError()
        record = result[0]
        value = record.get("uuid")
        if record.get("number") != account or not isinstance(value, str):
            raise ValueError()
        identifier = uuid.UUID(value)
        if str(identifier) != value or identifier.int == 0 or aliases - {account, value}:
            raise ValueError()
        if record.get("isUnregistered") is True:
            raise ValueError()
    except (ValueError, TypeError, AttributeError):
        raise SafeError("Phone commands could not verify this linked account. Retry connection.") from None
    return aliases | {value}


def candidate(event, aliases, enabled_at, current):
    """Return identity and body only for a fresh, ordinary incoming text message."""
    if not isinstance(event, dict) or event.get("method") != "receive":
        return None
    params = event.get("params")
    if not isinstance(params, dict):
        return None
    payload = params.get("result", params)
    if not isinstance(payload, dict):
        return None
    if payload.get("account") is not None and payload["account"] not in aliases:
        return None
    envelope = payload.get("envelope")
    if not isinstance(envelope, dict) or envelope.get("syncMessage") is not None:
        return None
    sources = [envelope.get(k) for k in ("sourceUuid", "sourceNumber", "source")]
    sources = [x for x in sources if isinstance(x, str) and x]
    if not sources or any(x in aliases for x in sources):
        return None
    data = envelope.get("dataMessage")
    if not isinstance(data, dict):
        return None
    if envelope.get("editMessage") is not None:
        return None
    if any(data.get(k) for k in (
        "viewOnce", "isExpirationUpdate", "isEndSession", "isProfileKeyUpdate", "reaction",
        "remoteDelete", "adminDelete", "storyContext", "pollCreate", "pollVote", "pollTerminate",
    )):
        return None
    # Fail closed if the upstream schema no longer exposes disappearing-message lifetime.
    if type(data.get("expiresInSeconds")) is not int or data["expiresInSeconds"] != 0:
        return None
    if type(data.get("viewOnce")) is not bool:
        return None
    styles = data.get("textStyles", [])
    if not isinstance(styles, list) or any(
        not isinstance(style, dict) or style.get("style") not in
        {"BOLD", "ITALIC", "STRIKETHROUGH", "MONOSPACE"} for style in styles
    ):
        return None
    text, timestamp = data.get("message"), data.get("timestamp")
    if not isinstance(text, str) or "?" not in text or len(text.encode()) > 64 * 1024:
        return None
    if type(timestamp) is not int or not max(enabled_at, current - MAX_AGE_MS) <= timestamp <= current + 300000:
        return None
    event_id = hashlib.sha256(json.dumps([sources[0], timestamp], separators=(",", ":")).encode()).hexdigest()
    return event_id, timestamp, text


class Store(notes.NoteStore):
    error = SafeError

    def __init__(self, path):
        self.db = sqlite3.connect(path)
        self.db.execute("PRAGMA secure_delete=ON")
        self.db.execute("CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value INTEGER NOT NULL)")
        self.db.execute("CREATE TABLE IF NOT EXISTS outbox (id TEXT PRIMARY KEY, timestamp INTEGER NOT NULL, state TEXT NOT NULL, body TEXT)")
        self.db.execute("CREATE TABLE IF NOT EXISTS metrics (key TEXT PRIMARY KEY, value INTEGER NOT NULL)")
        self.db.execute("INSERT OR IGNORE INTO meta VALUES ('enabled_at', ?)", (now_ms(),))
        # An interrupted send could already have arrived. Never automatically duplicate it.
        self.db.execute("UPDATE outbox SET state='uncertain', body=NULL WHERE state='inflight'")
        self.init_notes()
        self.db.commit()
        self.enabled_at = self.db.execute("SELECT value FROM meta WHERE key='enabled_at'").fetchone()[0]
        # Expiration must not depend on successfully connecting to Signal.
        self.expire(now_ms())

    def contains(self, event_id):
        return self.db.execute("SELECT 1 FROM outbox WHERE id=?", (event_id,)).fetchone() is not None

    def enqueue(self, event_id, timestamp, urls, sender=None, options=None):
        options = notes_settings(options)
        if not urls or self.contains(event_id):
            return False
        if self.db.execute("SELECT count(*) FROM outbox WHERE state='pending'").fetchone()[0] >= 256:
            self.increment("outbox_dropped")
            LOG.error("outbox_full")
            return False
        with self.db:
            note_id = self.add_note(event_id, timestamp)
            name = notes.sanitize_sender(sender) if options["include_sender"] else None
            header = "Decrumb" + (" · From " + name if name else "")
            body = header + "\n" + "\n".join(urls[:10]) + "\n#" + note_id
            if len(body.encode()) > 8192:
                self.db.execute("DELETE FROM generated_notes WHERE id=?", (note_id,))
                self.db.execute("INSERT INTO metrics VALUES ('oversize_dropped',1) ON CONFLICT(key) DO UPDATE SET value=value+1")
                LOG.warning("cleaned_message_oversize")
                return False
            self.db.execute("INSERT OR IGNORE INTO outbox VALUES (?, ?, 'pending', ?)", (event_id, timestamp, body))
        return True

    def finish(self, event_id, state):
        with self.db:
            self.db.execute("UPDATE outbox SET state=?, body=NULL WHERE id=?", (state, event_id))
            if state == "uncertain":
                self.db.execute("UPDATE generated_notes SET state='unmanageable',cleanup_at=NULL WHERE event_id=?", (event_id,))

    def expire(self, current):
        with self.db:
            self.db.execute("UPDATE outbox SET state='expired', body=NULL WHERE state='pending' AND timestamp<?", (current - MAX_AGE_MS,))
            self.expire_notes(current)
            self.db.execute("DELETE FROM outbox WHERE timestamp<? AND state!='pending'", (current - 30 * MAX_AGE_MS,))

    def counts(self):
        return dict(self.db.execute("SELECT state,count(*) FROM outbox GROUP BY state"))

    def increment(self, key, amount=1):
        with self.db:
            self.db.execute("INSERT INTO metrics VALUES (?,?) ON CONFLICT(key) DO UPDATE SET value=value+excluded.value", (key, amount))

    def metrics(self):
        return dict(self.db.execute("SELECT key,value FROM metrics"))

    def close(self):
        self.db.close()


def maintain_outbox(root):
    """Expire local data while stopped without interfering with an active worker."""
    if not (root / "outbox.sqlite3").exists():
        return None
    try:
        with exclusive(root), contextlib.closing(Store(root / "outbox.sqlite3")) as store:
            return {"counts": store.counts(), "metrics": store.metrics(), "note_counts": store.note_summary()}
    except SafeError:
        # A running worker/pairing owns the lock and its own maintenance schedule.
        return None


def deliver_one(store, rpc, account, options=None):
    options = notes_settings(options)
    cancelled = getattr(rpc, "cancel_event", None)
    if cancelled is not None and cancelled.is_set():
        return False
    row = store.db.execute("SELECT id,body FROM outbox WHERE state='pending' ORDER BY timestamp LIMIT 1").fetchone()
    if not row:
        return False
    event_id, body = row
    with store.db:
        if store.note_for_event(event_id) is None:
            # A queued legacy note has not been sent yet: give that future send its own ID.
            note_id = store.add_note(event_id, now_ms())
            body += "\n#" + note_id
            store.db.execute("UPDATE outbox SET body=? WHERE id=?", (body, event_id))
        store.db.execute("UPDATE outbox SET state='inflight' WHERE id=?", (event_id,))
    try:
        # No caller-supplied recipient, group, attachments, previews or commands.
        result = rpc.call("send", {"account": account, "noteToSelf": True, "message": body})
        if not isinstance(result, dict) or type(result.get("timestamp")) is not int or result["timestamp"] <= 0:
            raise SafeError("Signal send acknowledgement was not recognized.")
        if not isinstance(result.get("results"), list) or not result["results"]:
            raise SafeError("Signal send acknowledgement was not recognized.")
        for item in result["results"]:
            if not isinstance(item, dict) or item.get("type") != "SUCCESS":
                raise SafeError("Signal send was not confirmed.")
        with store.db:
            store.db.execute("UPDATE outbox SET state='sent',body=NULL WHERE id=?", (event_id,))
            store.record_receipt(event_id, account, result["timestamp"], options)
            store.db.execute("INSERT OR REPLACE INTO metrics VALUES ('last_sent_at', ?)", (now_ms(),))
    except NotDispatched:
        with store.db:
            store.db.execute("UPDATE outbox SET state='pending' WHERE id=?", (event_id,))
        return False
    except SafeError:
        store.finish(event_id, "uncertain")
        LOG.warning("send_unconfirmed_no_retry")
        raise
    return True


def cleanup_one(store, rpc, account, options=None, current=None, schedule=True):
    """Request deletion of one recorded self-send; acknowledgements are not erasure receipts."""
    current = now_ms() if current is None else current
    options = notes_settings(options)
    stopped = getattr(rpc, "cancel_event", None)
    if stopped is not None and stopped.is_set():
        return False
    if schedule:
        store.update_schedule(options, current)
    row = store.db.execute("""SELECT id,account_hash,sent_at,attempts FROM generated_notes
        WHERE state IN ('cleanup_pending','offline','delete_uncertain') AND next_attempt_at<=?
        ORDER BY next_attempt_at,sent_at LIMIT 1""", (current,)).fetchone()
    if not row:
        return False
    note_id, binding, sent_at, attempts = row
    if not binding or not notes.can_cleanup(sent_at, current):
        with store.db:
            store.db.execute("UPDATE generated_notes SET state=? WHERE id=?", ("too_old" if sent_at else "unmanageable", note_id))
        return True
    dispatched = False
    try:
        verified_account, aliases = account_details(rpc.call("listAccounts", timeout=3))
        if account not in aliases or binding != notes.account_binding(verified_account):
            LOG.error('account_mismatch')
            with store.db:
                store.db.execute("UPDATE generated_notes SET state='account_mismatch' WHERE id=?", (note_id,))
            return True
        if stopped is not None and stopped.is_set():
            return False
        with store.db:
            store.db.execute("UPDATE generated_notes SET state='deleting',attempts=attempts+1 WHERE id=?", (note_id,))
        dispatched = True
        result = rpc.call("remoteDelete", {"account": verified_account, "noteToSelf": True,
                                          "targetTimestamp": sent_at}, timeout=8)
        if (not isinstance(result, dict) or type(result.get("timestamp")) is not int or result["timestamp"] <= 0 or
                not isinstance(result.get("results"), list) or not result["results"]):
            raise SafeError("Signal cleanup acknowledgement was not recognized.")
        results = result["results"]
        if any(not isinstance(item, dict) or item.get("type") != "SUCCESS" for item in results):
            # A confirmed transport failure still does not prove no linked device received it.
            with store.db:
                _cleanup_retry(store, note_id, attempts + 1, "offline", current)
            return True
        with store.db:
            store.db.execute("UPDATE generated_notes SET state='deletion_requested',next_attempt_at=0 WHERE id=?", (note_id,))
    except NotDispatched:
        if dispatched:
            with store.db:
                store.db.execute("UPDATE generated_notes SET state='cleanup_pending',attempts=? WHERE id=?", (attempts, note_id))
        return False
    except SafeError:
        with store.db:
            _cleanup_retry(store, note_id, attempts + 1, "delete_uncertain" if dispatched else "offline", current)
        LOG.warning("note_cleanup_unconfirmed")
    return True


def _cleanup_retry(store, note_id, attempts, state, current):
    # Repeating a delete for the same allowlisted timestamp is safe; never resend a note.
    delay = (30, 60, 300, 900, 1800)[min(max(attempts - 1, 0), 4)] * 1000
    state = "cleanup_failed" if attempts >= 6 else state
    store.db.execute("UPDATE generated_notes SET state=?,attempts=?,next_attempt_at=? WHERE id=?",
                     (state, attempts, current + delay, note_id))


def run(root, config, stopped=None):
    try:
        _run(root, config, stopped)
    except Exception as error:
        diagnostics.failure(root, error)
        raise


def _run(root, config, stopped=None):
    if not config.get("account"):
        raise SafeError("Pair with Signal before starting the worker.")
    stopped = stopped if stopped is not None else threading.Event()
    options = notes_settings(config.get("notes"))
    commands_started_at = now_ms()
    def stop(*_):
        stopped.set()
    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)
    with exclusive(root), contextlib.ExitStack() as started:
        # Check after acquiring worker.lock: the interface may have prepared an
        # update between launchd spawning us and this process reaching the lock.
        if (root / "update-transition.json").exists():
            raise SafeError("An app update is preparing to install. Reopen Decrumb to finish it.")
        store = started.enter_context(contextlib.closing(Store(root / "outbox.sqlite3")))
        heartbeat = {"state": "starting", "updated_at": now_ms(), "pid": os.getpid()}
        write_json(root / "status.json", heartbeat)
        try:
            with Rpc(root, config, cancel_event=stopped) as rpc:
                account, aliases = account_details(rpc.call("listAccounts"))
                if config["account"] not in aliases:
                    raise SafeError("Configured account does not match the linked account.", 'account_mismatch')
                if phone_commands.normalize_settings(config.get("phone_commands"))["enabled"]:
                    aliases = command_aliases(rpc, account, aliases)
                rpc.call("subscribeReceive", {"account": account})
                next_send = next_cleanup = next_health = 0.0
                recorded_drops = 0
                while not stopped.is_set():
                    if rpc.closed.is_set():
                        raise SafeError("Signal connection closed.", 'connection_closed')
                    monotonic = time.monotonic()
                    with rpc.mutex:
                        drops = rpc.dropped_events
                    if drops > recorded_drops:
                        store.increment("receive_dropped", drops - recorded_drops)
                        recorded_drops = drops
                    if monotonic >= next_health:
                        try:
                            diagnostics.maintain(root)
                        except OSError:
                            pass
                        store.expire(now_ms())
                        store.update_schedule(options)
                        write_json(root / "status.json", {
                            "state": "running", "updated_at": now_ms(), "pid": os.getpid(),
                            "counts": store.counts(),
                            "metrics": store.metrics(),
                            "note_counts": store.note_summary(),
                        })
                        next_health = monotonic + 30
                    try:
                        event = rpc.events.get(timeout=0.5)
                        try:
                            handled = phone_commands.process(
                                event, aliases, store, config,
                                lambda text: clean(config["helper"], text, config["settings"]),
                                now_ms(), commands_started_at,
                            )
                        except SafeError:
                            store.increment("helper_failures")
                            LOG.error("phone_command_cleanup_failed")
                            handled = True
                        if handled:
                            # Keep draining the same bounded outbox below; a reply
                            # never enters the ordinary incoming-message cleaner.
                            event = None
                        item = candidate(event, aliases, store.enabled_at, now_ms())
                        if item and not store.contains(item[0]):
                            try:
                                urls = clean(config["helper"], item[2], config["settings"])
                                store.enqueue(item[0], item[1], urls, notes.sender_name(event), options)
                            except SafeError:
                                store.increment("helper_failures")
                                LOG.error("message_cleanup_failed")
                    except queue.Empty:
                        pass
                    if not stopped.is_set() and monotonic >= next_send:
                        if deliver_one(store, rpc, account, options):
                            next_send = time.monotonic() + 2
                    if not stopped.is_set() and monotonic >= next_cleanup:
                        cleanup_one(store, rpc, account, options, schedule=False)
                        next_cleanup = time.monotonic() + 2
        except SafeError:
            if not stopped.is_set():
                raise
        finally:
            write_json(root / "status.json", {
                "state": "stopped" if stopped.is_set() else "error", "updated_at": now_ms(),
                "counts": store.counts(),
                "metrics": store.metrics(),
                "note_counts": store.note_summary(),
            })


def pair(root, config, emit=None, terminal_qr=False):
    qr_path = root / "pairing.png"
    if terminal_qr and not sys.stdout.isatty():
        raise SafeError("Terminal pairing requires an interactive terminal.")
    stopped = threading.Event()
    def stop(*_):
        stopped.set()
    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)
    def report(state):
        if emit:
            emit(state)
        else:
            print({"linked": "Linked successfully. Ready to start the worker.",
                   "qr_ready": "QR ready. Scan pairing.png using Signal → Settings → Linked Devices."}[state], flush=True)
    with exclusive(root), Rpc(root, config, cancel_event=stopped) as rpc:
        accounts = rpc.call("listAccounts")
        if accounts:
            account, _ = account_details(accounts)
            config["account"] = account
            write_json(root / "config.json", config)
            report("linked")
            return
        try:
            uri = rpc.call("startLink")["deviceLinkUri"]
            if not isinstance(uri, str) or not uri.startswith("sgnl://linkdevice?"):
                raise SafeError("Unexpected pairing response.")
            subprocess.run(runtime.helper_command(config["helper"], "--qr", str(qr_path)), input=uri.encode(),
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=True, timeout=15,
                           **runtime.child_options())
            runtime.private_mode(qr_path)
            report("qr_ready")
            if terminal_qr:
                subprocess.run(runtime.helper_command(config["helper"], "--qr-terminal"), input=uri.encode(),
                               stderr=subprocess.DEVNULL, check=True, timeout=15)
            rpc.call("finishLink", {"deviceLinkUri": uri, "deviceName": "Decrumb"}, timeout=180)
            account, _ = account_details(rpc.call("listAccounts"))
            config["account"] = account
            write_json(root / "config.json", config)
            report("linked")
        finally:
            qr_path.unlink(missing_ok=True)


def main():
    os.umask(0o077)
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=DEFAULT_ROOT)
    commands = parser.add_subparsers(dest="command", required=True)
    setup = commands.add_parser("init")
    setup.add_argument("--helper", type=Path, required=True)
    setup.add_argument("--signal-cli", type=Path,
                       default=Path("/opt/homebrew/bin/signal-cli" if sys.platform == "darwin" else "/usr/bin/signal-cli"))
    settings = commands.add_parser("configure")
    settings.add_argument("--mode", choices=["all", "selected", "off"], required=True)
    settings.add_argument("--base-url", action="append", default=[])
    commands.add_parser("pair")
    commands.add_parser("run")
    commands.add_parser("status")
    commands.add_parser("diagnostics", help="Preview a content-free report; nothing is uploaded")
    commands.add_parser("clear-diagnostics", help="Clear local error history without changing Signal state")
    commands.add_parser("preview", help="Read sample text from stdin; make no network requests")
    args = parser.parse_args()
    root = args.root.expanduser().resolve()
    root.mkdir(parents=True, exist_ok=True, mode=0o700)
    os.chmod(root, 0o700)
    diagnostics.configure(root, LOG)
    if args.command in ('diagnostics', 'clear-diagnostics'):
        if args.command == 'clear-diagnostics':
            diagnostics.maintain(root, clear=True)
        print(json.dumps(diagnostics.report(root), indent=2))
        return
    if args.command == "init":
        with exclusive(root):
            if (root / "config.json").exists():
                raise SafeError("Configuration already exists; use configure to change URL rules.")
            config = {"version": 1, "signal_cli": str(args.signal_cli.expanduser().absolute()),
                      "helper": str(args.helper.resolve()), "account": None,
                      "settings": {"mode": "all", "baseURLs": []}}
            clean(config["helper"], "", config["settings"])
            (root / "signal-cli").mkdir(mode=0o700)
            write_json(root / "config.json", config)
        print("Initialized. Next: pair.")
        return
    config = load_config(root, validate_helper=args.command != "status")
    if args.command == "configure":
        with exclusive(root):
            config["settings"] = {"mode": args.mode, "baseURLs": args.base_url}
            config["settings"] = clean_result(config["helper"], "", config["settings"])["settings"]
            # Previously queued links were authorized under the old rules.
            if (root / "outbox.sqlite3").exists():
                with contextlib.closing(Store(root / "outbox.sqlite3")) as store:
                    store.clear_pending()
            write_json(root / "config.json", config)
        print("Settings saved. Start the worker to apply them.")
    elif args.command == "pair":
        pair(root, config)
    elif args.command == "run":
        run(root, config)
    elif args.command == "preview":
        sample = sys.stdin.buffer.read(64 * 1024 + 1)
        if len(sample) > 64 * 1024:
            raise SafeError("Sample exceeds 64 KiB.")
        print(json.dumps({"urls": clean(config["helper"], sample.decode(), config["settings"])}, indent=2))
    elif args.command == "status":
        print(json.dumps(read_status(root, config), indent=2))


def read_status(root, config):
    status = {"state": "not_started", "counts": {}, "metrics": {}, "note_counts": {}}
    try:
        saved = json.loads((root / "status.json").read_text())
        # Only fixed fields cross the public diagnostic boundary.
        if saved.get("state") in {"starting", "running", "stopped", "error"}:
            status["state"] = saved["state"]
        for key in ("updated_at", "pid"):
            if type(saved.get(key)) is int:
                status[key] = saved[key]
        for key, allowed in (("counts", {"pending", "inflight", "sent", "uncertain", "expired", "cancelled"}),
                             ("metrics", {"receive_dropped", "outbox_dropped", "oversize_dropped", "helper_failures", "last_sent_at"}),
                             ("note_counts", notes.STATES | {"total", "manageable", "legacy_unmanageable"})):
            if isinstance(saved.get(key), dict):
                status[key] = {k: v for k, v in saved[key].items() if k in allowed and type(v) is int}
        if status["state"] in {"running", "starting"}:
            stale = now_ms() - status.get("updated_at", 0) > 90000
            try:
                if status.get("pid", 0) <= 0:
                    stale = True
                else:
                    stale = stale or not runtime.process_alive(status["pid"])
            except ProcessLookupError:
                stale = True
            if stale:
                status["state"] = "stale"
    except (OSError, ValueError, TypeError, AttributeError):
        pass
    status["linked"] = bool(config.get("account"))
    mode = config["settings"].get("mode", "off")
    status["mode"] = mode if mode in ("all", "selected", "off") else "off"
    status["helper_available"] = os.access(config["helper"], os.X_OK)
    status["signal_available"] = os.access(config["signal_cli"], os.X_OK)
    status["needs_attention"] = (status["state"] in {"error", "stale"} or not status["helper_available"] or not status["signal_available"] or
                                any(v for k, v in status["metrics"].items() if k != "last_sent_at") or
                                bool(status["counts"].get("uncertain")))
    return status


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        sys.exit(130)
    except SafeError as error:
        LOG.error(error.diagnostic_code)
        print(str(error), file=sys.stderr)
        sys.exit(1)
    except Exception as error:
        # A traceback or upstream exception can include private message data.
        LOG.error(diagnostics.failure_code(error))
        print("Operation failed; see the content-free worker log.", file=sys.stderr)
        sys.exit(1)
