# Decrumb product directions

Ranked for usefulness across an always-on Mac and Raspberry Pi, 2026-09-20.

1. **Phone commands — shipped in RC4.** Opt in locally, then send
   `/decrumb help`, `/decrumb status`, or `/decrumb clean <link>` to Note to Self.
   This provides on-demand cleaning for a link copied from any app and an easy
   check that a headless helper is responding. Commands use the same local rules,
   bounded outbox and receipt tracking. They never fetch links, run shell commands,
   open files, change settings, or call an AI provider. The helper must already be
   running and online; old commands are not replayed when it starts. Only fresh,
   authenticated self-to-self sent transcripts qualify. Disappearing messages,
   view-once content, spoilers and unknown styles remain excluded. Off by default.
2. **A device health snapshot.** A future explicit command could return uptime,
   low-disk warnings and helper state, without hostnames, IP addresses or paths.
   Useful for a Pi out of sight; requires separate platform-specific validation.
3. **Simple privacy presets.** Group existing sender-attribution and note-lifetime
   controls with a configurable local queue lifetime. Describe each retained data
   category honestly; no preset can promise deletion from backups or all devices.
4. **Recovery alerts.** An optional, rate-limited note after connectivity returns
   could report downtime and aggregate queue losses. It cannot notify a phone
   while the host is offline, and must avoid a stream of repetitive messages.
5. **Explicit AI requests.** Later, a user could deliberately submit pasted text
   for summarization through opt-in OpenRouter. This needs model and spending
   controls, clear disclosure of which text leaves the device, and a separate
   review. Passive analysis of all messages and automatic website fetching are
   excluded. AI-driven machine actions and arbitrary remote shell access are
   outside the initial command feature.

The first feature provides a useful phone-to-helper interface with a small,
reviewable permission boundary. Machine control should grow only through named,
separately reviewed capabilities with explicit local opt-in, never through
interpreting unrestricted chat as instructions.
