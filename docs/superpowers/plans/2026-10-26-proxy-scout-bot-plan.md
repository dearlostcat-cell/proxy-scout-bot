# ProxyScout Telegram Bot Implementation Plan

> **For agentic workers:** Implement the tasks in order in this session. The user delegated implementation choices, so proceed with the selected design. The user did not request automated tests; do not add or run a test suite.

**Goal:** Deliver a self-hosted, private Telegram bot that collects and verifies a bounded set of public IPv4 HTTP/SOCKS4/SOCKS5 proxies using the pinned Rust checker.

**Architecture:** Python 3.11+ standard-library modules handle Telegram long polling, feed collection, candidate filtering, and sanitized result persistence. The pinned `proxy-scraper-checker` `build-3880` binary runs as a child process with a local-file input config and JSON output.

**Tech Stack:** Python 3.11+ standard library, Telegram Bot API over HTTPS, `monosans/proxy-scraper-checker` release `build-3880`.

**Spec:** `docs/superpowers/specs/2026-10-26-proxy-scout-bot-design.md`

## Global Constraints

- Python 3.11 or newer.
- Use the exact `build-3880` Rust checker release; do not download or upgrade binaries automatically at runtime.
- Accept only configured HTTPS feeds; reject redirects and candidates that are not globally routable IPv4 with a port in `1..65535`.
- Deduplicate candidates and cap a scan at 2,000 unique candidates.
- Configure 64 concurrent checks and stop a scan after five minutes.
- Permit bot commands only in private chats and only for IDs in `TELEGRAM_ALLOWED_USER_IDS`; `/id` is the setup exception.
- Run at most one scan at a time and enforce a five-minute per-user scan cooldown.
- Drop any engine result containing authentication credentials; persist only sanitized successful results.
- Use no runtime Python packages. Do not add automated tests or run test commands.
- Keep IPv6 endpoints, proxy serving, arbitrary Telegram-supplied source URLs, scheduled scans and comparative performance claims out of this version.

## Review Focus

- A feed has a non-HTTPS URL, redirect, timeout or oversized response: skip it without following the redirect or hanging the scan.
- A feed contains malformed ports, private/special IPv4 addresses, repeated endpoints, or too many candidates: reject invalid entries and cap the deduplicated set at 2,000.
- The checker is missing, exits non-zero, exceeds five minutes, or writes malformed JSON: report a scan failure and keep the last successful sanitized result.
- The checker output contains `username` or `password`: exclude that proxy from persisted and Telegram output.
- A caller is unauthorized or sends a command in a group: allow only `/id`; do not disclose scan status or results.

---

### Task 1: Configuration and safe feed collection

**Files:**
- Create: `proxy_scout/__init__.py`
- Create: `proxy_scout/config.py`
- Create: `proxy_scout/models.py`
- Create: `proxy_scout/feeds.py`
- Create: `config/sources.json`

**Interfaces:**
- Produces `Settings` from environment variables, including token, allowlist, binary path, scan limits and project paths.
- Produces `FeedBatch` with per-protocol candidate lists and a total collected count.
- Reads the pinned release's source catalog, but does not execute instructions from upstream files.

- [ ] Add `Settings` and `FeedBatch` dataclasses, fixed protocol names, and environment parsing in `proxy_scout/config.py` and `proxy_scout/models.py`.
- [ ] Add all directly parseable, protocol-classified HTTPS feed URLs from the three supplied scraper projects to `config/sources.json`; current catalog target: 72 unique feeds (37 HTTP, 10 SOCKS4, 25 SOCKS5), with attribution planned for Task 4.
- [ ] Implement concurrent feed retrieval with a 10-second per-feed timeout, a 2 MiB response cap, and redirect rejection in `proxy_scout/feeds.py`.
- [ ] Parse IPv4 `address:port` candidates with `ipaddress`; reject non-global IPs and invalid ports, keep at most 2,000 per feed, deduplicate by protocol/IP/port, and apply the 2,000-candidate cap fairly across protocols.
- [ ] Write bounded `input/http.txt`, `input/socks4.txt`, and `input/socks5.txt` files for the Rust checker.
- [ ] Run `python -m py_compile proxy_scout/config.py proxy_scout/models.py proxy_scout/feeds.py` and inspect accepted/rejected input paths manually.

### Task 2: Checker process and sanitized result store

**Files:**
- Create: `config/checker.toml`
- Create: `proxy_scout/checker.py`
- Create: `proxy_scout/storage.py`

**Interfaces:**
- `async run_scan(settings: Settings) -> ScanSummary` collects inputs, runs the configured binary, parses its JSON, persists a sanitized successful result, and returns aggregate counts and duration.
- `load_latest(settings: Settings) -> ScanSummary | None` returns the latest successfully persisted run.

- [ ] Configure JSON-only output, verified HTTPS IP checking, 64 concurrent checks, 8-second request timeout, 3-second connect timeout, and the three local input files in `config/checker.toml`.
- [ ] Implement the child-process call with `PROXY_SCRAPER_BINARY`, the checker config environment variable, and the five-minute hard timeout in `proxy_scout/checker.py`.
- [ ] Parse the engine's `proxies.json` array; accept only entries with valid protocol, public IPv4 host, valid port and numeric latency; omit entries with credentials.
- [ ] Persist `data/latest.json` atomically only after a successful engine run; preserve the previous successful file on failure.
- [ ] Return candidate count, verified survivor count, per-protocol counts, UTC completion time and elapsed seconds; do not claim a checked count.
- [ ] Run `python -m py_compile proxy_scout/checker.py proxy_scout/storage.py` and inspect error, timeout and credential-handling paths manually.

### Task 3: Private Telegram bot commands

**Files:**
- Create: `proxy_scout/telegram_api.py`
- Create: `proxy_scout/bot.py`
- Create: `proxy_scout/__main__.py`

**Interfaces:**
- Telegram client supports `get_updates(offset, timeout)` and `send_message(chat_id, text)` through the Bot API.
- Bot command handlers consume `Settings` and use `run_scan` / `load_latest` from Task 2.

- [ ] Implement Telegram Bot API JSON requests over HTTPS using the standard library; keep the token out of logs and use long polling for messages only.
- [ ] Add private-chat routing, `/id`, `/help`, `/scan`, `/status`, and `/list [protocol]`; permit non-allowlisted users to use only `/id`.
- [ ] Enforce one active scan, the five-minute per-user cooldown, plain-text result formatting, and a ten-proxy list limit.
- [ ] Run scans in a worker thread/task so long polling and status replies continue while the checker is active.
- [ ] Add bounded retry/backoff for Bot API transport errors without logging request URLs containing the token.
- [ ] Run `python -m py_compile proxy_scout/telegram_api.py proxy_scout/bot.py proxy_scout/__main__.py` and inspect authorization, polling offset and scan-lock paths manually.

### Task 4: Install and operate the deliverable

**Files:**
- Create: `README.md`
- Create: `THIRD_PARTY_NOTICES.md`
- Create: `LICENSE`
- Create: `.gitignore`
- Create: `install_engine.ps1`

**Interfaces:**
- `python -m proxy_scout` starts the bot after the owner installs the pinned checker and sets `TELEGRAM_BOT_TOKEN` and `TELEGRAM_ALLOWED_USER_IDS`.
- Setup docs explain `/id`, environment setup, feed editing, scan limits and IPv4-first scope.

- [ ] Add attribution and license references for source URL metadata derived from `monosans/proxy-scraper-checker`, `proxybroker2`, and `proxy_pool`.
- [ ] Add a Windows PowerShell installer that downloads and extracts only the pinned `build-3880` x64 Windows release after the owner invokes it; document manual binary setup for other platforms.
- [ ] Document starting BotFather, setting environment variables, discovering the user ID with `/id`, authorizing that ID, running the bot, and its private-only commands.
- [ ] Document that public proxies are untrusted and short-lived, and that the bot does not run a relay or guarantee anonymity.
- [ ] Add ignore rules for secrets, generated inputs, checker output and `data/latest.json`.
- [ ] Run `python -m py_compile proxy_scout/*.py` and inspect the README commands and installer URL against the selected tag; do not contact Telegram or run a public scan without credentials.

---

## Self-Review

- **Spec coverage:** Goals and constraints map to Tasks 1–4. The design's success criteria are covered by environment parsing, scan bounds, authorization, single-job state, sanitized persistence and operation docs.
- **Step clarity:** Each task has named files and explicit interfaces; validation steps use syntax compilation and manual inspection because automated testing was not requested.
- **Type consistency:** `Settings`, `FeedBatch`, and `ScanSummary` are shared across the feed, checker, storage and bot tasks.
- **Review focus:** All five high-risk input and failure cases appear in the owning task steps.
- **Proportion:** The plan describes four deliverables and avoids prescribing implementation bodies beyond values and interfaces fixed by the design.
