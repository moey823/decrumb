# URL cleanup rules

The standalone worker uses `swift/SidecarURLCleaner.swift`, extracted from Sidelet with the
original default tracking rules plus the configurable overrides described below. Modes are `all`, `selected`, and `off`. Base domains include subdomains;
path prefixes match whole path boundaries. Unspecified ports match normal HTTP
and HTTPS ports. Only HTTP and HTTPS URLs are processed.

The worker sends only changed URLs to Note to Self; it does not edit the source
message or retain a copy of the original message body. See the main README for
message eligibility, delivery limits and privacy behavior.

The conservative global list contains Google's nine documented UTM campaign
keys, `gclid`, `msclkid`, and Mozilla's eight documented initial tracking keys.
Instagram links additionally lose `stkn`, `igsh`, and `igshid`; these sharing
identifiers are removed only on `instagram.com` and its subdomains. Parameters
such as `img_index` and `story_media_id` remain intact. Thus a reel link ending
in `?utm_source=ig_web_copy_link&stkn=abc==` becomes the plain reel URL.
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

## Extensible rules (macOS app)

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
