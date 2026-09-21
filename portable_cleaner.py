#!/usr/bin/env python3
# SPDX-License-Identifier: AGPL-3.0-only
"""Offline Linux URL helper using Decrumb's shared versioned rules.

The helper implements the same bounded JSON protocol as the macOS helper. It
never requests a URL. Original spelling, escaping, duplicate fields, and empty
query fields survive removal; URL parsing is used only for rule matching.
"""
import json
import ipaddress
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
from urllib.parse import quote, unquote, urlsplit, urlunsplit

MAX_REQUEST = 2 * 1024 * 1024
MAX_TEXT = 64 * 1024
SCHEME = re.compile(r"^[A-Za-z][A-Za-z0-9+.-]*://")
PARAMETER = re.compile(r"[A-Za-z0-9_.~-]{1,128}\Z")
# HTTP links, www links, and bare DNS names. Boundaries exclude email addresses
# and URLs nested inside an unsupported scheme. A complete outer URL is consumed
# before looking for the next one, so query values cannot become separate links.
LINK = re.compile(
    r"(?<![\w@/:.\-])(?:https?://|www\.|"
    r"(?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z]{2,63}(?=[/:?#]|\b))"
    r"(?:(?!\]\()[^\s<>\"\x00-\x1f])*", re.IGNORECASE,
)


def components(value):
    if not isinstance(value, str) or not value or "\\" in value:
        raise ValueError()
    if any(c.isspace() or ord(c) < 32 or ord(c) == 127 for c in value):
        raise ValueError()
    absolute = value if SCHEME.match(value) else "https://" + value
    parsed = urlsplit(absolute)
    if (parsed.scheme.lower() not in ("http", "https") or not parsed.hostname or
            "%" in parsed.hostname or "://" in parsed.hostname):
        raise ValueError()
    host = parsed.hostname
    # Python's built-in IDNA codec maps distinct modern domains together (for
    # example faß.de and fass.de). Without a full IDNA2008 implementation, accept
    # ASCII/Punycode hosts only; leave Unicode-host links completely untouched.
    # Never use lossy domain normalization to authorize a site-specific removal.
    if not host.isascii():
        raise ValueError()
    if ":" in host:
        ipaddress.IPv6Address(host)
    else:
        labels = host.rstrip(".").split(".")
        if len(host.rstrip(".")) > 253 or any(not 1 <= len(label) <= 63 or
                not re.fullmatch(r"[A-Za-z0-9_-]+", label) for label in labels):
            raise ValueError()
    # Evaluating port also rejects malformed authorities and out-of-range ports.
    parsed.port
    return parsed


def normalize_site(value):
    if not isinstance(value, str):
        raise ValueError()
    value = value.strip()
    if not value or len(value) > 2048 or "*" in value:
        raise ValueError()
    parsed = components(value)
    if parsed.username is not None or parsed.password is not None or "?" in value or "#" in value:
        raise ValueError()
    host = parsed.hostname.lower()
    if ":" in host:
        host = "[" + host + "]"
    if parsed.port is not None:
        host += ":" + str(parsed.port)
    path = quote(parsed.path.rstrip("/"), safe="/%:@!$&'()*+,;=-._~")
    return urlunsplit((parsed.scheme.lower(), host, path, "", ""))


def sites(values):
    if not isinstance(values, list) or len(values) > 100:
        raise ValueError()
    return [normalize_site(value) for value in values]


def parameters(values):
    if not isinstance(values, list) or len(values) > 50:
        raise ValueError()
    if any(not isinstance(value, str) or not PARAMETER.fullmatch(value) for value in values):
        raise ValueError()
    return [value.lower() for value in values]


def site_rules(values):
    if not isinstance(values, list) or len(values) > 100:
        raise ValueError()
    return [{"site": normalize_site(item["site"]), "remove": parameters(item["remove"]),
             "keep": parameters(item["keep"])} for item in values]


def settings(raw):
    if not isinstance(raw, dict) or raw.get("mode") not in ("off", "selected", "all"):
        raise ValueError()
    return {"mode": raw["mode"], "baseURLs": sites(raw["baseURLs"]),
            "excludedURLs": sites(raw.get("excludedURLs", [])),
            "rules": site_rules(raw.get("rules", []))}


def load_rules(path):
    raw = json.loads(path.read_bytes())
    if type(raw["version"]) is not int or raw["version"] != 1 or not raw["protectedParameters"]:
        raise ValueError()
    if not isinstance(raw["revision"], str):
        raise ValueError()
    return {"revision": raw["revision"], "globalRemove": parameters(raw["globalRemove"]),
            "protectedParameters": parameters(raw["protectedParameters"]),
            "sites": site_rules(raw["sites"])}


def matches(parsed, base):
    rule = components(base)
    host, base_host = parsed.hostname.lower(), rule.hostname.lower()
    if host != base_host and not host.endswith("." + base_host):
        return False
    default_port = 443 if parsed.scheme.lower() == "https" else 80
    if rule.port is not None:
        if (parsed.port if parsed.port is not None else default_port) != rule.port:
            return False
    elif parsed.port is not None and parsed.port != default_port:
        return False
    path = quote(parsed.path, safe="/%:@!$&'()*+,;=-._~")
    return not rule.path or rule.path == "/" or path == rule.path or path.startswith(rule.path + "/")


def decode_name(value):
    # Swift's removingPercentEncoding preserves the original name on a malformed
    # escape or invalid UTF-8; urllib's default replacement behavior would differ.
    if re.search(r"%(?![0-9A-Fa-f]{2})", value):
        return value
    try:
        return unquote(value, encoding="utf-8", errors="strict")
    except UnicodeError:
        return value


def query_parts(value):
    fragment = value.find("#")
    end = len(value) if fragment < 0 else fragment
    start = value.find("?")
    if start < 0 or start >= end:
        return None
    return start, end, value[start + 1:end].split("&")


def clean_url(value, options, rules):
    try:
        parsed = components(value)
        if (options["mode"] == "off" or
                any(matches(parsed, base) for base in options["excludedURLs"]) or
                (options["mode"] != "all" and
                 not any(matches(parsed, base) for base in options["baseURLs"]))):
            return value
    except (ValueError, UnicodeError):
        return value
    query = query_parts(value)
    if query is None:
        return value
    start, end, parts = query
    names = [decode_name(part.split("=", 1)[0]).lower() for part in parts]
    if set(names).intersection(rules["protectedParameters"]):
        return value
    matching = [rule for rule in rules["sites"] + options["rules"] if matches(parsed, rule["site"])]
    removed = set(rules["globalRemove"]).union(*(set(rule["remove"]) for rule in matching))
    kept = set().union(*(set(rule["keep"]) for rule in matching))
    retained = [part for name, part in zip(names, parts) if name not in removed or name in kept]
    if len(retained) == len(parts):
        return value
    return value[:start] + ("?" + "&".join(retained) if retained else "") + value[end:]


def detected_urls(text):
    for match in LINK.finditer(text):
        value = match.group()
        # Sentence punctuation and unmatched closing delimiters are outside the
        # link. Balanced brackets in paths and query values stay byte-for-byte.
        while value:
            if value[-1] in ".,;!\u2026\u2019":
                value = value[:-1]
            elif value[-1] in ")]}":
                opening = {")": "(", "]": "[", "}": "{"}[value[-1]]
                if value.count(value[-1]) > value.count(opening):
                    value = value[:-1]
                else:
                    break
            else:
                break
        try:
            parsed = components(value)
            if not SCHEME.match(value) and not value.lower().startswith("www.") and parsed.hostname.rsplit(".", 1)[-1] in {"invalid", "test", "example", "localhost"}:
                continue
        except (ValueError, UnicodeError):
            continue
        yield value


def request(raw, rules):
    text = raw["text"]
    if not isinstance(text, str) or len(text.encode("utf-8")) > MAX_TEXT:
        raise ValueError()
    options = settings(raw["settings"])
    urls, changes, seen = [], [], set()
    for original in detected_urls(text):
        cleaned = clean_url(original, options, rules)
        def keys(value):
            query = query_parts(value)
            return [] if query is None else [decode_name(part.split("=", 1)[0]) for part in query[2] if part]
        remaining = {name.lower() for name in keys(cleaned)}
        changes.append({"original": original, "cleaned": cleaned,
                        "removed": [name for name in keys(original) if name.lower() not in remaining]})
        if cleaned != original:
            absolute = cleaned if re.match(r"^https?://", cleaned, re.IGNORECASE) else "http://" + cleaned
            if absolute not in seen:
                seen.add(absolute)
                urls.append(absolute)
    return {"urls": urls, "changes": changes, "settings": options, "revision": rules["revision"]}


def render_qr(data, output=None):
    if len(data) > 4096 or not data.startswith(b"sgnl://linkdevice?"):
        raise ValueError()
    if output is None:
        if not sys.stdout.isatty():
            raise ValueError()
        subprocess.run(["/usr/bin/qrencode", "-t", "UTF8", "-l", "M", "-m", "4"],
                       input=data, stderr=subprocess.DEVNULL, check=True, timeout=10)
        return
    # Create privately before qrencode writes, avoiding a world-readable window.
    destination = Path(output)
    fd, temporary = tempfile.mkstemp(prefix=".decrumb-qr-", suffix=".png", dir=destination.parent)
    os.close(fd)
    try:
        subprocess.run(["/usr/bin/qrencode", "-t", "PNG", "-l", "M", "-s", "10", "-m", "4", "-o", temporary],
                       input=data, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                       check=True, timeout=10)
        os.chmod(temporary, 0o600)
        os.replace(temporary, destination)
    finally:
        Path(temporary).unlink(missing_ok=True)


def main():
    try:
        data = sys.stdin.buffer.read(MAX_REQUEST + 1)
        if len(data) > MAX_REQUEST:
            raise ValueError()
        if len(sys.argv) == 3 and sys.argv[1] == "--qr":
            render_qr(data, sys.argv[2])
        elif sys.argv[1:] == ["--qr-terminal"]:
            render_qr(data)
        elif len(sys.argv) == 1:
            rules_path = Path(__file__).resolve().with_name("rules.json")
            if not rules_path.exists():
                rules_path = Path(__file__).resolve().parent / "rules/defaults.json"
            output = request(json.loads(data), load_rules(rules_path))
            print(json.dumps(output, ensure_ascii=False))
        else:
            raise ValueError()
    except Exception:
        # Parser and process errors can contain original URLs or pairing secrets.
        print("Invalid cleanup request.", file=sys.stderr)
        return 65
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
