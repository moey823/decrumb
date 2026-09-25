# SPDX-License-Identifier: AGPL-3.0-only
"""Offline Linux-helper conformance and private QR handling."""
import itertools
import json
import os
from pathlib import Path
import stat
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

import build
import decrumb
import portable_cleaner as cleaner

ROOT = Path(__file__).resolve().parents[1]
RULES = cleaner.load_rules(ROOT / "rules/defaults.json")
SETTINGS = {"mode": "all", "baseURLs": []}


def x_tracking_cases():
    """Synthetic expected results also exercised through the built Swift helper."""
    path = "/example/status/1234567890"
    tracking = "?s=46&t=synthetic_share_token"
    cases = []
    for host in ("x.com", "twitter.com", "www.x.com", "mobile.twitter.com"):
        for scheme, port in (("https", ""), ("https", ":443"), ("http", ":80")):
            base = scheme + "://" + host + port + path
            cases.append((base + tracking, SETTINGS, [base]))
    for host in ("x.com", "twitter.com"):
        base = "https://" + host
        media = base + path + "/photo/1"
        cases.append((media + "?s=46&id=a%2Bb&id=%26&t=synthetic_share_token&lang=en#media",
                      SETTINGS, [media + "?id=a%2Bb&id=%26&lang=en#media"]))
        cases.append((base + path + "?%73=46&T=synthetic_share_token&text=hello+world",
                      SETTINGS, [base + path + "?text=hello+world"]))
        for redirect in ("/i/redirect", "/i/redirect/", "/i/redirect/child"):
            # These names can be functional redirect inputs. Global trackers
            # may still be removed without discarding the redirect inputs.
            original = base + redirect + tracking
            cases.append((original, SETTINGS, []))
            cases.append((original + "&utm_source=synthetic", SETTINGS, [original]))
        cases.append((base + "/i/redirected" + tracking, SETTINGS, [base + "/i/redirected"]))
        cases.append((base + path + tracking + "&sig=synthetic_signature", SETTINGS, []))
    for host in ("example.com", "notx.com", "x.com.example", "nottwitter.com", "twitter.com.example", "x.com:8443"):
        cases.append(("https://" + host + path + tracking, SETTINGS, []))
    original = "https://x.com" + path + tracking
    cases.extend([
        (original, {**SETTINGS, "rules": [{"site": "x.com", "remove": [], "keep": ["s"]}]},
         ["https://x.com" + path + "?s=46"]),
        (original, {**SETTINGS, "excludedURLs": ["x.com/example"]}, []),
        (original, {"mode": "selected", "baseURLs": ["x.com/example"]}, ["https://x.com" + path]),
        (original, {"mode": "selected", "baseURLs": ["x.com/other"]}, []),
        (original, {"mode": "off", "baseURLs": []}, []),
        (original + "&X-Amz-Signature=synthetic_signature",
         {**SETTINGS, "rules": [{"site": "x.com", "remove": ["X-Amz-Signature"], "keep": []}]}, []),
    ])
    return cases


def swift_reference_available():
    if sys.platform != "darwin":
        return False
    try:
        with (ROOT / "build/url-cleaner").open("rb") as source:
            return source.read(4) in (b"\xcf\xfa\xed\xfe", b"\xfe\xed\xfa\xcf", b"\xca\xfe\xba\xbe")
    except OSError:
        return False


class PortableCleanerTests(unittest.TestCase):
    def result(self, text, **options):
        return cleaner.request({"text": text, "settings": {**SETTINGS, **options}}, RULES)

    def test_x_tracking_rules_preserve_functional_inputs_and_user_controls(self):
        for text, options, expected in x_tracking_cases():
            with self.subTest(text=text, options=options):
                self.assertEqual(self.result(text, **options)["urls"], expected)

    def test_preserves_query_bytes_and_functional_empty_fields(self):
        values = {
            "https://example.com/?utm_source=x&id=1&id=2#frag": "https://example.com/?id=1&id=2#frag",
            "https://example.com/?q=a%2Bb&fbclid=x&x=%26": "https://example.com/?q=a%2Bb&x=%26",
            "https://example.com/?%75tm_source=x&UTM_MEDIUM=y": "https://example.com/",
            "https://example.com/?utm_source=x&&a=": "https://example.com/?&a=",
            "https://example.com/?&utm_source=x": "https://example.com/?",
            "https://example.com/?=keep&utm_source=x": "https://example.com/?=keep",
            "https://example.com/?utm_source=x#https://example.net/?id=2": "https://example.com/#https://example.net/?id=2",
            "www.example.com/?next=https://other.example/path&utm_source=x": "http://www.example.com/?next=https://other.example/path",
            "https://example.com/?id=1%FF&utm_source=x": "https://example.com/?id=1%FF",
            "https://example.com/?utm_source%=x&fbclid=y": "https://example.com/?utm_source%=x",
        }
        for original, expected in values.items():
            with self.subTest(original=original):
                self.assertEqual(self.result(original)["urls"], [expected])

    def test_known_signed_links_never_change(self):
        for signature in ("sig", "signature", "X-Amz-Signature", "x-goog-signature", "%73ig"):
            self.assertEqual(self.result("https://example.com/?utm_source=x&" + signature + "=a%2Fb")["urls"], [])

    def test_rules_are_normalized_and_bounded(self):
        options = cleaner.settings({**SETTINGS, "baseURLs": [" Example.com/news/ "],
                                    "rules": [{"site": "instagram.com", "remove": ["TRACK"], "keep": ["IGSH"]}]})
        self.assertEqual(options["baseURLs"], ["https://example.com/news"])
        self.assertEqual(options["rules"][0]["remove"], ["track"])
        self.assertEqual(options["rules"][0]["keep"], ["igsh"])
        for values in (["*.example.com"], ["https://user@example.com"], ["https://example.com/?"],
                       ["https://example.com/#"], ["https://example.com:99999"], ["x"] * 101):
            with self.subTest(values=values[:1]), self.assertRaises(ValueError):
                cleaner.settings({**SETTINGS, "baseURLs": values})
        with self.assertRaises(ValueError):
            cleaner.settings({**SETTINGS, "rules": [{"site": "example.com", "remove": [".*"], "keep": []}]})

    def test_exclusions_port_scope_and_keep_overrides(self):
        choices = {"mode": "selected", "baseURLs": ["example.com/news"]}
        self.assertEqual(self.result("https://sub.example.com/news/a?utm_source=x", **choices)["urls"], ["https://sub.example.com/news/a"])
        for value in ("https://example.com/newsroom?utm_source=x", "https://notexample.com/news?utm_source=x", "https://example.com:8000/news?utm_source=x"):
            self.assertEqual(self.result(value, **choices)["urls"], [])
        self.assertEqual(self.result("https://example.com/?utm_source=x", excludedURLs=["example.com"])["urls"], [])
        overrides = [{"site": "instagram.com", "remove": [], "keep": ["igsh"]}]
        self.assertEqual(self.result("https://instagram.com/?igsh=x&utm_source=y", rules=overrides)["urls"], ["https://instagram.com/?igsh=x"])

    def test_text_boundaries_dedup_and_unsupported_schemes(self):
        value = "https://example.com/?utm_source=x"
        for text in ("Look 👋 (" + value + ").", "[" + value + "](" + value + ")", value + "\n" + value):
            self.assertEqual(self.result(text)["urls"], ["https://example.com/"])
        for text in ("mailto:hello@example.com?utm_source=x", "ftp://example.com/?utm_source=x", "a@example.com/?utm_source=x"):
            self.assertEqual(self.result(text)["urls"], [])

    def test_bounded_private_protocol(self):
        for raw in (b'{"secret":"private-fixture"}', json.dumps({"text": "private-fixture" * 6000, "settings": SETTINGS}).encode()):
            result = subprocess.run([sys.executable, "-B", str(ROOT / "portable_cleaner.py")], input=raw, capture_output=True)
            self.assertEqual(result.returncode, 65)
            self.assertEqual(result.stdout, b"")
            self.assertEqual(result.stderr.decode().splitlines(), ["Invalid cleanup request."])

    def test_rules_remain_shared_data(self):
        altered = {**RULES, "globalRemove": RULES["globalRemove"] + ["new_key"]}
        value = "https://example.com/?new_key=x&id=2"
        self.assertEqual(cleaner.request({"text": value, "settings": SETTINGS}, altered)["urls"], ["https://example.com/?id=2"])

    def test_unicode_host_rules_cannot_alias_unrelated_ascii_hosts(self):
        with self.assertRaises(ValueError):
            cleaner.settings({**SETTINGS, "rules": [{"site": "faß.de", "remove": ["id"], "keep": []}]})
        rule = [{"site": "xn--fa-hia.de", "remove": ["id"], "keep": []}]
        self.assertEqual(self.result("https://fass.de/?id=keep&utm_source=x", rules=rule)["urls"],
                         ["https://fass.de/?id=keep"])
        self.assertEqual(self.result("https://xn--fa-hia.de/?id=remove&utm_source=x", rules=rule)["urls"],
                         ["https://xn--fa-hia.de/"])

    def test_unsupported_hosts_do_not_hide_later_valid_links(self):
        for host in ("a" * 64 + ".com", "faß.de", "例子.测试", "example..com"):
            text = "https://" + host + "/?utm_source=x https://example.com/?utm_source=y"
            self.assertEqual(self.result(text)["urls"], ["https://example.com/"])

    @unittest.skipUnless(swift_reference_available(), "requires built macOS reference helper")
    def test_swift_differential_contract(self):
        # Real reference binary, synthetic corpus; compare the complete protocol,
        # including preview explanation and normalized user settings.
        fields = ("utm_source=x", "fbclid=y", "id=a%2Bb", "id=%26", "", "=keep")
        texts = ["https://example.com/path?" + "&".join(parts) + "#frag"
                 for count in (1, 2, 3) for parts in itertools.permutations(fields, count)]
        texts += [
            "Look 👋 (https://instagram.com/reel/a/?igsh=abc&img_index=2).",
            "https://example.com/?%75tm_source=x&UTM_MEDIUM=y",
            "https://example.com/?utm_source%=x&fbclid=y",
            "https://example.com/?id=%FF&utm_source=x",
            "https://example.com/?sig=s&utm_source=x",
            "https://example.com/?X-Amz-Signature=s&utm_source=x",
            "https://example.com/?%73ignature=s&utm_source=x",
            "https://example.com/?utm_source=x#https://example.net/?id=2",
            "www.example.com/?next=https://other.example/path&utm_source=x",
            "https://example.com/❤?utm_source=x",
            "https://xn--fa-hia.de/path?utm_source=x&id=%E2%9C%93",
            "https://[::1]/?utm_source=x",
            "https://example.com/?id=a(b)&utm_source=x",
            "[https://example.com/?utm_source=x](https://example.com/?utm_source=y)",
            "example.com/?utm_source=x", "example.invalid/?utm_source=x",
            "mailto:hello@example.com?utm_source=x", "ftp://example.com/?utm_source=x",
        ]
        cases = [(text, SETTINGS) for text in texts]
        cases.extend((text, options) for text, options, _ in x_tracking_cases())
        for options in ({"mode": "off", "baseURLs": []},
                        {"mode": "selected", "baseURLs": [" example.com/news/ "]},
                        {**SETTINGS, "excludedURLs": ["example.com/news"]},
                        {**SETTINGS, "rules": [{"site": "example.com", "remove": ["ID"], "keep": ["UTM_SOURCE"]}]}):
            for value in ("https://sub.example.com/news/a?utm_source=x&id=2", "https://example.com/newsroom?utm_source=x", "https://example.com:8000/news?utm_source=x"):
                cases.append((value, options))
        for text, options in cases:
            with self.subTest(text=text, options=options):
                raw = {"text": text, "settings": options}
                expected = json.loads(subprocess.check_output([str(ROOT / "build/url-cleaner")], input=json.dumps(raw).encode()))
                self.assertEqual(cleaner.request(raw, RULES), expected)


class PrivateQRTests(unittest.TestCase):
    def test_png_is_private_and_pairing_data_only_enters_stdin(self):
        data = b"sgnl://linkdevice?uuid=synthetic&pub_key=synthetic"
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "pairing.png"
            def generate(command, **kwargs):
                temporary = Path(command[-1])
                self.assertEqual(stat.S_IMODE(temporary.stat().st_mode), 0o600)
                self.assertNotIn(data.decode(), command)
                self.assertEqual(kwargs["input"], data)
                temporary.write_bytes(b"\x89PNG\r\n\x1a\n")
            with patch.object(cleaner.subprocess, "run", side_effect=generate):
                cleaner.render_qr(data, path)
            self.assertEqual(stat.S_IMODE(path.stat().st_mode), 0o600)
            self.assertEqual(list(Path(folder).iterdir()), [path])

    def test_qr_failure_removes_temporary_file_and_preserves_previous_file(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "pairing.png"
            path.write_bytes(b"previous")
            with patch.object(cleaner.subprocess, "run", side_effect=OSError), self.assertRaises(OSError):
                cleaner.render_qr(b"sgnl://linkdevice?synthetic", path)
            self.assertEqual(path.read_bytes(), b"previous")
            self.assertEqual(list(Path(folder).iterdir()), [path])

    def test_terminal_qr_requires_tty_at_helper_and_pair_boundary(self):
        with patch.object(sys.stdout, "isatty", return_value=False), patch.object(cleaner.subprocess, "run") as run:
            with self.assertRaises(ValueError):
                cleaner.render_qr(b"sgnl://linkdevice?synthetic")
            with self.assertRaises(decrumb.SafeError):
                decrumb.pair(Path("/nonexistent-synthetic-fixture"), {}, terminal_qr=True)
            run.assert_not_called()


class PortableBuildTests(unittest.TestCase):
    def test_linux_build_has_no_apple_toolchain_or_network(self):
        with tempfile.TemporaryDirectory() as folder, patch.object(build, "OUTPUT", Path(folder)), \
                patch.object(sys, "argv", ["build.py"]), patch.object(sys, "platform", "linux"), \
                patch.object(build.subprocess, "run") as run, patch.object(build.sparkle, "distribution") as sparkle:
            build.main()
            helper = Path(folder) / "url-cleaner"
            self.assertTrue(os.access(helper, os.X_OK))
            self.assertEqual((Path(folder) / "rules.json").read_bytes(), (ROOT / "rules/defaults.json").read_bytes())
            run.assert_not_called()
            sparkle.assert_not_called()

    def test_linux_runtime_uses_absolute_xdg_state_location(self):
        with patch.object(sys, "platform", "linux"), patch.dict(os.environ, {"XDG_STATE_HOME": "/synthetic/state"}):
            self.assertEqual(decrumb.default_root(), Path("/synthetic/state/decrumb"))
        with patch.object(sys, "platform", "linux"), patch.dict(os.environ, {"XDG_STATE_HOME": "relative"}):
            self.assertEqual(decrumb.default_root(), Path.home() / ".local/state/decrumb")
        with patch.object(sys, "platform", "darwin"):
            self.assertEqual(decrumb.default_root(), Path.home() / "Library/Application Support/Decrumb")


if __name__ == "__main__":
    unittest.main()
