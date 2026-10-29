# URL cleanup rules

The Mac worker uses `swift/DecrumbURLCleaner.swift`, extracted from the
personal Signal-iOS prototype with its original default tracking rules plus the
configurable overrides described below. Modes are `all`, `selected`, and `off`.
Base domains include subdomains; path prefixes match whole path boundaries.
Unspecified ports match normal HTTP
and HTTPS ports. Only HTTP and HTTPS URLs are processed.

The Pi worker uses `portable_cleaner.py` with the same bundled rules and override
schema. Its text detector is conservative and differs from Apple's detector.
It accepts ASCII and Punycode hostnames; raw Unicode hostnames stay untouched and
Unicode rule hosts are rejected. Use the domain's explicit Punycode form for Pi
rules. This avoids mapping distinct internationalized domains onto one rule.
Malformed links are skipped without preventing other links from being cleaned.

The worker sends only changed URLs to Note to Self; it does not edit the source
message or retain a copy of the original message body. See the main README for
message eligibility, delivery limits and privacy behavior.

The global list contains Google's nine documented UTM campaign
keys, `gclid`, `msclkid`, and Mozilla's eight documented initial tracking keys.
Instagram links additionally lose `stkn`, `igsh`, `igshid`, and `rpxt`; these sharing
identifiers are removed only on `instagram.com` and its subdomains. Parameters
such as `img_index` and `story_media_id` remain intact. Thus a reel link ending
in `?utm_source=ig_web_copy_link&stkn=abc==` becomes the plain reel URL.
X/Twitter links additionally lose `s` and `t` on `x.com`, `twitter.com`, and
their subdomains. For example, a post link ending in
`?s=46&t=synthetic_share_token` becomes the plain post URL. Both fields remain
intact under `/i/redirect`, where they may be needed for the redirect. They are
not removed on unrelated domains; other fields such as `lang` remain intact.
DoorDash store links additionally lose `aw` under `doordash.com/store` and
matching subdomains. A share ending in
`?utm_source=mx_share&aw=synthetic_share_token` becomes the plain store URL.
The `aw` rule is limited to the `/store` path boundary; other paths and domains
retain it. Store paths, functional query fields, and fragments remain intact.
The exact query parameter `si` is removed globally, on every HTTP(S) host and
port, by the owner's explicit preference. Spotify shares containing both `si`
and `utm_source` become the plain content URL; the same removal applies to
YouTube and any other domain. Case variants and encoded parameter names follow
the existing normalization rules. Other names such as `sibling` stay intact.
Site-specific keep rules can preserve `si` where needed. Signed-link protection,
exclusions and cleaning modes still take precedence.
Other query fields, byte encoding, duplicate functional fields, paths, and
fragments are preserved. Links containing `sig`, `signature`, `X-Amz-Signature`,
or `X-Goog-Signature` are left intact because the signature can cover the query.
No URL is fetched, expanded, or logged by the cleaner. The list ships as bundled versioned data;
it does not silently download new rules.

Parameter references: [Google campaign parameters](https://support.google.com/analytics/answer/10917952),
[Google click identifiers](https://support.google.com/google-ads/answer/3095550),
[Microsoft click identifiers](https://learn.microsoft.com/en-us/advertising/guides/uet-conversion-api-integration?view=bingads-13),
and [Mozilla query stripping](https://firefox-source-docs.mozilla.org/toolkit/components/antitracking/anti-tracking/query-stripping/index.html).
Instagram references: [ClearURLs' Instagram share-token proposal](https://github.com/ClearURLs/Rules/pull/332)
(open at the time of implementation), [AdGuard's report](https://github.com/AdguardTeam/AdguardFilters/issues/240901),
and [FixupXer's implemented Instagram cleanup](https://github.com/NeatCode-Labs/fixupxer-telegram-bot#changes-in-032-2026-09-05).
X/Twitter reference: [ClearURLs' bundled rules](https://github.com/ClearURLs/Rules/blob/master/data.min.json)
list `s` and `t` for both domains and exempt `/i/redirect` (checked 2026-09-25).
Decrumb adopts only these two exact names, with path-scoped keep rules for the
redirect exception; existing global removals still apply there.

## Extensible rules

The lists now live in `rules/defaults.json`, copied beside the helper as
`rules.json`. The bundled document has `version`, `revision`, `globalRemove`,
`protectedParameters`, and `sites`. Changing a list no longer requires changing
Swift code. Rebuild/repackage to distribute a new built-in revision.

User overrides remain separate in the private configuration. The app's import and
export format is:

```json
{
  "version": 1,
  "settings": {
    "mode": "all",
    "baseURLs": [],
    "excludedURLs": ["example.com/private"],
    "rules": [
      {"site": "example.com", "remove": ["share_id"], "keep": ["ref"]}
    ]
  }
}
```

The Pi `configure` command accepts this versioned export or the inner `settings`
object. Both platforms validate the rules and discard queued notes authorized
under the previous rules when you apply a change.

Site values are normalized: surrounding whitespace and trailing slashes are
removed. Exclusions override all cleaning. Preserve rules override removals,
including built-in removals. Recognized signed URLs stay unchanged regardless of
custom rules. Parameter names are exact ASCII names, case-insensitive, limited to
letters, numbers, `_`, `.`, `~`, and `-`. Wildcards and regex are rejected. At most
100 selected sites, 100 exclusions, 100 custom rules, and 50 names per remove/keep
list are accepted. Export/import never includes account data or startup settings.

The helper also returns local preview details and normalized settings; the worker
uses only the changed URL list. Preview originals are not stored by Decrumb. A URL
inside a functional query parameter does not confuse the outer scheme detection.

## Managing rules from Signal

With phone commands enabled, send `/decrumb rules` in Note to Self to inspect
the installed bundled defaults and custom settings. Each reply is bounded and
includes a page number; `/decrumb rules <page>` requests another page.

Send `/decrumb rules add doordash.com/store aw` to add a site-scoped removal.
Multiple exact names can be separated by spaces or commas. This uses the
installed helper's existing normalization and validation; it adds or merges a
custom rule without changing bundled defaults, keep rules, exclusions, selected
sites or cleaning mode. It persists to the existing private configuration and
updates the running cleaner immediately without a restart.

The worker already holds the runtime lock while handling these commands.
A durable command reservation precedes configuration changes, separately from
the reply outbox, so cancellation or interrupted replies cannot authorize
repeating a mutation. Reservations expire after 30 days; accepted commands
are limited to fresh self-to-self transcripts from the active worker session.
Old pending notes are cancelled under the same policy as app rule changes.
Invalid rules and save failures get fixed replies without reflecting private
errors or paths. All replies use the ordinary Note-to-Self-only delivery path.
