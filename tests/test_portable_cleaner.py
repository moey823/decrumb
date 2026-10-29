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


def instagram_rpxt_cases():
    """Offline fixtures for the reported Instagram sharing parameter."""
    path = "/reel/ExampleCode/"
    tracking = "?rpxt=c3ludGhldGlj=="
    base = "https://www.instagram.com" + path
    cases = [("https://" + host + path + tracking, SETTINGS,
              ["https://" + host + path])
             for host in ("instagram.com", "www.instagram.com", "m.instagram.com")]
    cases.extend([
        (base + "?rpxt=c3ludGhldGlj==&img_index=2&story_media_id=123#media", SETTINGS,
         [base + "?img_index=2&story_media_id=123#media"]),
        (base + "?%72pxt=a&RPXT=b&id=a%2Bb&id=%26", SETTINGS,
         [base + "?id=a%2Bb&id=%26"]),
        (base + tracking + "&sig=synthetic", SETTINGS, []),
        (base + tracking, {**SETTINGS, "rules": [
            {"site": "instagram.com", "remove": [], "keep": ["rpxt"]}]}, []),
        (base + tracking, {**SETTINGS, "excludedURLs": ["instagram.com"]}, []),
        (base + tracking, {"mode": "off", "baseURLs": []}, []),
        (base + tracking, {"mode": "selected", "baseURLs": ["instagram.com/reel"]}, [base]),
    ])
    for host in ("example.com", "notinstagram.com", "instagram.com.example", "instagram.com:8443"):
        cases.append(("https://" + host + path + tracking, SETTINGS, []))
    return cases


def doordash_share_cases():
    """Synthetic DoorDash store shares; preserve other inputs and user controls."""
    path = "/store/123456"
    tracking = "?utm_source=mx_share&aw=synthetic_share_token"
    base = "https://www.doordash.com" + path
    cases = []
    for host in ("doordash.com", "www.doordash.com", "m.doordash.com"):
        for scheme, port in (("https", ""), ("https", ":443"), ("http", ":80")):
            store = scheme + "://" + host + port + path
            cases.append((store + tracking, SETTINGS, [store]))
    cases.extend([
        (base + "/menu" + tracking, SETTINGS, [base + "/menu"]),
        (base + "?aw=synthetic_share_token", SETTINGS, [base]),
        (base + "?aw=a&id=a%2Bb&aw=b&id=%26&utm_source=mx_share#menu",
         SETTINGS, [base + "?id=a%2Bb&id=%26#menu"]),
        (base + "?%61w=a&AW=b&item_id=789", SETTINGS, [base + "?item_id=789"]),
        ("[" + base + tracking + "](" + base + tracking + ")", SETTINGS, [base]),
        (base + tracking + "&sig=synthetic_signature", SETTINGS, []),
        (base + tracking, {**SETTINGS, "rules": [
            {"site": "doordash.com/store", "remove": [], "keep": ["aw"]}]},
         [base + "?aw=synthetic_share_token"]),
        (base + tracking, {**SETTINGS, "excludedURLs": ["doordash.com/store"]}, []),
        (base + tracking, {"mode": "off", "baseURLs": []}, []),
        (base + tracking, {"mode": "selected", "baseURLs": ["doordash.com/store"]}, [base]),
        (base + tracking, {"mode": "selected", "baseURLs": ["doordash.com/other"]}, []),
    ])
    for host in ("example.com", "notdoordash.com", "doordash.com.example",
                 "doordash.com:8443"):
        original = "https://" + host + path
        cases.append((original + tracking, SETTINGS,
                      [original + "?aw=synthetic_share_token"]))
    for path in ("/", "/checkout", "/storefront/123456"):
        original = "https://www.doordash.com" + path
        cases.append((original + tracking, SETTINGS,
                      [original + "?aw=synthetic_share_token"]))
    return cases


def global_si_cases():
    """Global si removal, with functional inputs and existing controls preserved."""
    base = "https://open.spotify.com/track/SyntheticTrack"
    tracking = "?si=synthetic_share_token&utm_source=copy-link"
    cases = [(base + tracking, SETTINGS, [base]),
             (base + "?si=synthetic", SETTINGS, [base]),
             (base + "?%73i=a&SI=b&t=42&id=a%2Bb&id=%26#part", SETTINGS,
              [base + "?t=42&id=a%2Bb&id=%26#part"]),
             ("[" + base + tracking + "](" + base + tracking + ")", SETTINGS, [base]),
             (base + tracking + "&sig=synthetic", SETTINGS, []),
             (base + tracking, {**SETTINGS, "rules": [
                 {"site": "open.spotify.com", "remove": [], "keep": ["si"]}]},
              [base + "?si=synthetic_share_token"]),
             (base + tracking, {**SETTINGS, "excludedURLs": ["open.spotify.com"]}, []),
             (base + tracking, {"mode": "off", "baseURLs": []}, []),
             (base + tracking, {"mode": "selected", "baseURLs": ["open.spotify.com"]}, [base]),
             (base + tracking, {"mode": "selected", "baseURLs": ["example.com"]}, [])]
    for path in ("/album/SyntheticAlbum", "/playlist/SyntheticPlaylist",
                 "/episode/SyntheticEpisode", "/intl-de/track/SyntheticTrack"):
        url = "https://open.spotify.com" + path
        cases.append((url + tracking, SETTINGS, [url]))
    for host in ("example.com", "notopen.spotify.com", "open.spotify.com.example",
                 "accounts.spotify.com", "open.spotify.com:8443", "www.youtube.com", "youtu.be"):
        url = "https://" + host + "/track/SyntheticTrack"
        cases.append((url + tracking, SETTINGS, [url]))
    generic = "https://example.com/page"
    cases.extend([
        (generic + "?si=synthetic", SETTINGS, [generic]),
        (generic + "?%73i=a&SI=b&t=42&id=a%2Bb#part", SETTINGS,
         [generic + "?t=42&id=a%2Bb#part"]),
        (generic + "?sibling=keep&visit=keep", SETTINGS, []),
        (generic + tracking + "&signature=synthetic", SETTINGS, []),
        (generic + tracking, {**SETTINGS, "rules": [
            {"site": "example.com", "remove": [], "keep": ["si"]}]},
         [generic + "?si=synthetic_share_token"]),
        (generic + tracking, {**SETTINGS, "excludedURLs": ["example.com"]}, []),
    ])
    return cases


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

    def test_instagram_rpxt_rules(self):
        for text, options, expected in instagram_rpxt_cases():
            with self.subTest(text=text, options=options):
                self.assertEqual(self.result(text, **options)["urls"], expected)

    @unittest.skipUnless(swift_reference_available(), "requires built macOS reference helper")
    def test_swift_instagram_rpxt_rules(self):
        for text, options, expected in instagram_rpxt_cases():
            with self.subTest(text=text, options=options):
                self.assertEqual(decrumb.clean(ROOT / "build/url-cleaner", text, options), expected)

    def test_global_si_removal(self):
        for text, options, expected in global_si_cases():
            with self.subTest(text=text, options=options):
                self.assertEqual(self.result(text, **options)["urls"], expected)

    @unittest.skipUnless(swift_reference_available(), "requires built macOS reference helper")
    def test_swift_global_si_removal(self):
        for text, options, expected in global_si_cases():
            with self.subTest(text=text, options=options):
                self.assertEqual(decrumb.clean(ROOT / "build/url-cleaner", text, options), expected)

    def test_doordash_store_shares(self):
        for text, options, expected in doordash_share_cases():
            with self.subTest(text=text, options=options):
                self.assertEqual(self.result(text, **options)["urls"], expected)

    @unittest.skipUnless(swift_reference_available(), "requires built macOS reference helper")
    def test_swift_doordash_store_shares(self):
        for text, options, expected in doordash_share_cases():
            with self.subTest(text=text, options=options):
                self.assertEqual(decrumb.clean(ROOT / "build/url-cleaner", text, options), expected)

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
        cases.extend((text, options) for text, options, _ in doordash_share_cases())
        cases.extend((text, options) for text, options, _ in global_si_cases())
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
