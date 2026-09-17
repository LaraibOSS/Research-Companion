# Security Policy

## Supported versions

| Version | Status |
| --- | --- |
| `main` / source `0.8.0` | Actively maintained; security reports accepted |
| PyPI `0.5.14` | Legacy installable release; **not equivalent** to the current source |
| Releases older than `0.5.14` | Unsupported |

The source tree is at `0.8.0`, which is not yet published, so the latest PyPI
distribution remains `0.5.14`. **Security fixes are applied to `main` first.**
Users of the legacy PyPI release may need to install the corrected version from
source until `0.8.0` ships.

## Reporting a vulnerability

**Please do not open a public issue for security problems.** Report privately
through GitHub Security Advisories:

1. Go to the repository's **Security** tab.
2. Click **Report a vulnerability** ("Private vulnerability reporting").
3. Describe the issue, affected version, and steps to reproduce.

We aim to acknowledge a report within **7 days** and will coordinate a fix and
disclosure timeline with you.

## Scope and threat model

Research Companion is a **local-first, single-user** tool:

- The **Research Lab** web server binds to `127.0.0.1` only and is not intended to
  be exposed to a network. Do not run it on a public interface.
- API keys live only in a local `.env` file (never committed, never logged in
  plaintext). Rotate them if you suspect exposure.
- User-supplied download URLs (arXiv/DOI/coverage) pass through an application
  egress guard that rejects non-`http(s)` schemes, embedded credentials, and
  hosts resolving to non-global IPs. This is **best-effort** and not a substitute
  for network-level egress controls.

Findings that assume a multi-tenant hosted deployment are out of scope; findings
that affect the local user (path traversal, code execution, credential exposure,
XSS in the Lab from ingested content) are in scope and appreciated.
