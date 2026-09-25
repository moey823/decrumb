# Decrumb 1.1.1 release checklist

Candidate: **1.1.1**, build **8**. This release delivers X/Twitter `s`/`t`
share-parameter cleanup and the version/build in `/decrumb status` to Mac users.
Publication is pending. Checkboxes below are planned work, not completed evidence.

- [ ] Verify the shared release metadata and generated platform versions.
- [ ] Build the candidate and run the offline Python and Mac status tests.
- [ ] Prepare corresponding sources and notices from the final source checkout.
- [ ] Build and verify the Developer ID signed app; run packaged synthetic smoke.
- [ ] Notarize and staple the Mac artifacts; retain the release receipt, checksums,
  and signed Sparkle archive/feed with the matching corresponding-source archive.
- [ ] Publish immutable release assets, then deploy the signed update feed.
- [ ] Verify published asset hashes and that the public feed advertises build 8.
- [ ] Record the published source commit, asset evidence and update-feed result
  in the release record and update the candidate status in the release docs.

The existing linked account and runtime are outside the app bundle. Release
verification uses synthetic fixtures and isolated account state. Pi, Umbrel and
Windows publication or live-device acceptance must be recorded separately if done.
