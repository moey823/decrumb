# Decrumb

This is a personal Signal link-cleaner project for macOS and Raspberry Pi.

- Keep personal-project information out of unrelated business logs, wikis, handoffs, and project registries.
- Keep account keys, pairing images, messages, logs, configuration and runtime databases outside Git. Mac runtime files belong in `~/Library/Application Support/Decrumb`; Linux uses `${XDG_STATE_HOME:-~/.local/state}/decrumb`. Keep both outside the source checkout and installed code.
- Use synthetic offline fixtures for tests. Never print real messages, URLs, contacts, keys or account identifiers to logs or tool output.
- The only permitted automated send destination is Note to Self. Process disappearing messages under the same cleaning rules as ordinary messages; generated notes use the Note to Self timer and configured note-cleanup policy, not the source chat's timer. Preserve loop protection and the exclusions for view-once content and spoilers.
- Phone commands are optional and off by default. Accept only authenticated self-to-self sync transcripts, with bounded freshness and durable replay protection. Never execute shell commands, read arbitrary files, or fetch submitted URLs.
- Build with `python3 build.py`; test with `python3 -B -m unittest discover -s tests -p 'test_*.py' -v`.
- The app uses a pinned, isolated signal-cli 0.14.8 package. Source edits do not deploy automatically. Preserve existing linked accounts and unrelated services when deploying an explicitly requested update.
- Do not register a primary account, publish the repository, add a hosted service, or open an interactive browser without the user's explicit authorization. Existing authorization in the session remains valid.
- Preserve the AGPL license and source provenance in `docs/PROVENANCE.md`.
