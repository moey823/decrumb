# Security reports

Report suspected vulnerabilities through
[GitHub private vulnerability reporting](https://github.com/moey823/decrumb/security/advisories/new).
Include the affected source revision, impact, and a minimal reproduction using
invented data. Do not include Signal account files, keys, pairing codes, private
messages, or another person's data.

Decrumb is currently prerelease software. Release candidates and their source
are published on [GitHub Releases](https://github.com/moey823/decrumb/releases).
Fixes are developed on `main`; use the latest candidate for your platform and
follow the [update instructions](docs/DISTRIBUTION.md).

Optional phone commands accept only self-to-self Signal sync transcripts and
reply only to Note to Self. They cannot execute commands on the host, read files,
or fetch URLs. Authentication, replay protection, privacy-filter bypasses, and
dependency verification failures are security issues; report them privately.

The experimental Umbrel dashboard adds a private HTTP surface behind Umbrel's
login proxy, with a separate generated app password and authenticated APIs.
Unauthorized access to its pairing QR, controls, or persistent account state is
a security issue. Mac and Pi command-line releases do not expose this listener.
See the [Umbrel guide](docs/UMBREL.md) for network and storage boundaries.

Ordinary bugs and feature suggestions belong in
[GitHub Issues](https://github.com/moey823/decrumb/issues).
