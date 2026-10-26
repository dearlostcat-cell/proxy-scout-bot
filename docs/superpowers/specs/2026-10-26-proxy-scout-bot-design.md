# ProxyScout Telegram Bot Design

## Intent

Build a self-hosted Telegram bot that can collect public HTTP, SOCKS4 and SOCKS5 proxy candidates, verify them, and return a small, measured list to its owner. The user asked for a faster, more accurate result than the supplied proxy scraper projects and delegated the technology choices.

## Goals

- Use the supplied `monosans/proxy-scraper-checker` release `build-3872` as the checking engine.
- Fetch configured HTTPS proxy feeds concurrently, normalize and deduplicate IPv4 `address:port` candidates, and discard non-public addresses before checking. The initial catalog has 72 distinct feeds drawn from the three supplied scraper projects: 37 HTTP, 10 SOCKS4 and 25 SOCKS5.
- Verify candidates by fetching the full body of a TLS-verified HTTPS IP-check endpoint; retain the measured response time and observed exit IP.
- Provide private-chat commands: `/id`, `/help`, `/scan`, `/status`, and `/list [http|socks4|socks5]`.
- Restrict scan and result commands to configured Telegram user IDs, allow one scan at a time, enforce a per-user cooldown, and persist only the latest sanitized result set.
- Keep checker concurrency configurable and modest by default, and keep Telegram messages short enough for the Bot API.
- Bound each run to 2,000 unique candidates and five minutes; report actual scan duration, collected candidate count and verified working count rather than promise a fixed speed or success rate.

## Non-goals

- Modify or claim to close issues in the three upstream repositories.
- Guarantee that public proxies remain online, anonymous, safe, or suitable for sensitive traffic.
- Run a proxy relay/server, accept arbitrary user-provided source URLs, or expose a public proxy-list service.
- Schedule unattended scans or deploy the bot to a hosting provider.
- Support IPv6 proxy endpoints in this first version. The selected `build-3872` checker stores exit-IP metadata as IPv4; IPv6 support needs a separate engine change.

## Constraints and assumptions

- The workspace contains no checked-out Git repository. The deliverable will be a new project under `outputs/proxy-scout-bot/`.
- No Telegram token, allowlist, or hosting target was supplied. The project will be runnable after the owner adds those values; `/id` will report the caller's numeric Telegram user ID for setup.
- The bot will use Python 3.11+ standard-library HTTP/asyncio code for Telegram polling, avoiding a large framework dependency.
- The Rust checker is a pinned external executable selected by `PROXY_SCRAPER_BINARY`; installation instructions will link to the requested release. The bot will not auto-download or silently upgrade executable code.
- The tagged checker config supports JSON output. Its JSON includes optional username/password fields, so the bot must omit authenticated entries and never send credentials to Telegram.
- Only preconfigured HTTPS feeds are fetched. Redirects are rejected. Only globally routable IPv4 endpoints are passed to the checker, reducing the chance that a bad feed causes checks against loopback or private network services.
- Each feed has a 10-second total network deadline and a 2 MiB response limit; parsing keeps at most 2,000 candidates per feed before the global 2,000-candidate cap. Up to 16 feeds are fetched at once. Catalog entries are static HTTPS endpoints the collector can parse directly; HTTP-only, mixed-protocol, dynamically discovered and obfuscated sources are omitted.
- Default checker concurrency is 64. A scan may check at most 2,000 unique candidates and is stopped after five minutes. These are conservative starting limits; the owner can tune them for their host and network.
- The checker source catalog is MIT-licensed. The additional ProxyBroker2 and ProxyPool-derived feed URL metadata retains upstream attribution and license references in `THIRD_PARTY_NOTICES.md`; no upstream Python implementation is copied.

## Approaches considered

1. **Modernize `proxy_pool` and add a bot.** This preserves its familiar pool/API shape, but starts from synchronous requests, old pinned dependencies, Flask/Redis deployment and a scheduler that is more machinery than the requested bot needs.
2. **Repair `proxybroker2` and add a bot.** This reuses its asynchronous Python provider and IPv6 work, but duplicates substantial checking logic and requires a wider maintenance pass before the bot can rely on it.
3. **Wrap the Rust checker with a small private bot (selected).** The tagged engine already performs asynchronous HTTP/SOCKS checks, reads the full HTTPS response, deduplicates candidates, and writes JSON with latency and exit-IP metadata. A small wrapper can add Telegram access control, source filtering, result retention and bounded scans without forking the engine. The tradeoff is that the first version inherits the tag's IPv4 limitation and requires the external executable.

## Product behavior

- `/id` is available to any private chat and reports the caller's numeric user ID; all other commands require that ID in `TELEGRAM_ALLOWED_USER_IDS`.
- `/scan` fetches all configured feeds and starts one scan. A duplicate request while scanning or within the user's cooldown receives a short status reply.
- `/status` reports the latest run time, collected candidate count, verified working count, counts by protocol, and scan duration.
- `/list` returns the fastest ten entries from the latest run. An optional protocol narrows the displayed list.
- Results store protocol, host, port, latency and exit IP only. Credentials, raw feed contents and failed candidates are not retained in the latest result file; the checker's raw JSON output is deleted after each scan, including failure paths.
- The bot runs in long-polling mode and requires no inbound server port. It does not use webhooks.

## Success criteria

- The bot starts only with a valid Telegram token and a resolvable checker executable; missing setup produces a clear message.
- Unauthorized users cannot start scans or read results.
- Two scan requests cannot run the checker concurrently.
- Feed parsing rejects invalid ports, malformed IPv4 addresses, private/loopback/link-local/reserved addresses, and non-HTTPS feed URLs.
- A completed scan produces a sanitized `data/latest.json` and Telegram summaries with per-protocol collected/working counts and fastest results. The bot distinguishes candidates sent to the engine from verified survivors; it does not infer a checked count the engine does not report.
- The project includes setup, configuration, operational and attribution documentation.
- The project makes no comparative performance claim without a repeatable workload and baseline run for each upstream tool; it reports measurements from each scan instead.

## Builder decisions

- Use `asyncio.open_connection` with TLS for feed requests so one deadline covers connection, headers, and body reads; use `urllib.request` through worker threads for Telegram Bot API calls, plus `asyncio` for polling and task coordination.
- Run the Rust checker as a child process with a fixed config and JSON output, using its config path from the environment.
- Use a fixed source catalog combining direct HTTPS feed URLs from the requested checker tag, ProxyBroker2 and ProxyPool; source entries remain editable in the project config, but Telegram users cannot add URLs.
- Keep only the latest sanitized run; no Redis or database is required for this single-user, on-demand bot.
- Deliver source and setup scripts only. Actual Telegram activation requires the owner's token and user ID.
