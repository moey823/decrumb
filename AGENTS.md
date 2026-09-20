# Decrumb

This is a personal standalone macOS Signal link-cleaner project.

- Keep personal-project information out of unrelated business logs, wikis, handoffs, and project registries.
- Keep account keys, pairing images, messages, logs, configuration and runtime databases outside Git. Runtime files belong in `~/Library/Application Support/SideletLinkCleaner`, outside the source checkout and app bundle.
- Use synthetic offline fixtures for tests. Never print real messages, URLs, contacts, keys or account identifiers to logs or tool output.
- The only permitted automated send destination is Note to Self. Preserve loop protection and the exclusions for disappearing messages, view-once content and spoilers.
- Build with `python3 build.py`; test with `python3 -B -m unittest discover -s tests -p 'test_*.py' -v`.
- The app uses a pinned, isolated signal-cli 0.14.8 package. Source edits do not deploy automatically. Preserve existing linked accounts and unrelated services when deploying an explicitly requested update.
- Do not register a primary account, publish the repository, add a hosted service, or open an interactive browser without the user's explicit authorization. Existing authorization in the session remains valid.
- Preserve the AGPL license and source provenance in `docs/PROVENANCE.md`.
