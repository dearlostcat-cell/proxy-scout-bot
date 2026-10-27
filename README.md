# ProxyScout Telegram Bot

ProxyScout is a small, self-hosted Telegram bot for collecting and checking public HTTP, SOCKS4 and SOCKS5 proxy candidates. It uses the Rust checker from the pinned [`build-3880` release](https://github.com/monosans/proxy-scraper-checker/releases/tag/build-3880) and keeps Telegram access private to configured user IDs.

The bot prefetches the configured HTTPS feeds, keeps only unique public IPv4 `address:port` candidates, then asks the Rust engine to verify each candidate by fetching a complete TLS-verified HTTPS response. The latest successful scan stores response latency and observed exit IP, without proxy credentials.

## Requirements

- Python 3.11 or newer. The bot uses only the Python standard library.
- The `proxy-scraper-checker` executable from release `build-3880`.
- A Telegram bot token from [BotFather](https://core.telegram.org/bots#botfather).

## Install the checker on Windows x64

From this folder, run:

```powershell
.\install_engine.ps1
```

The script downloads and extracts the pinned x64 Windows executable into `engine/`. It does not run the executable. For other platforms, download the matching archive from the [pinned release page](https://github.com/monosans/proxy-scraper-checker/releases/tag/build-3880), extract it, and set `PROXY_SCRAPER_BINARY` to the executable path.

## Start the bot

In PowerShell, set your token and start the bot:

```powershell
$env:TELEGRAM_BOT_TOKEN = "your-token-from-botfather"
$env:TELEGRAM_ALLOWED_USER_IDS = ""
python -m proxy_scout
```

## Deploy to Railway

The repository includes a Dockerfile for Railway. It downloads the pinned x86-64 Linux checker during the image build and verifies its SHA-256 digest. Railway automatically builds a repository with a Dockerfile; this Telegram long-polling worker does not need a public domain or inbound port.

1. Push this project to a GitHub repository and connect that repository from a new Railway service.
2. In the Railway service's Variables, add `TELEGRAM_BOT_TOKEN` with the token from BotFather. Keep this value in Railway only; do not commit it to GitHub.
3. Deploy the service. With `TELEGRAM_ALLOWED_USER_IDS` unset, send `/id` to the bot in a private Telegram chat.
4. Add the returned numeric ID as `TELEGRAM_ALLOWED_USER_IDS` in Railway Variables, then redeploy. Separate multiple IDs with commas.

Railway's container filesystem is temporary across deployments. To retain the latest scan results, attach a Railway volume at `/app/data`. Railway mounts volumes as root, so set the service variable `RAILWAY_RUN_UID=0` when using that volume; without a volume, `/status` and `/list` start empty after a redeploy.

In a private Telegram chat, send `/id`. Add the returned numeric user ID to the allowlist, stop the process with Ctrl+C, and restart:

```powershell
$env:TELEGRAM_ALLOWED_USER_IDS = "123456789"
python -m proxy_scout
```

Separate multiple authorized user IDs with commas. Until an ID is allowlisted, the bot answers only `/id`. Commands sent in groups are ignored.

If the checker is somewhere else, set its path before starting:

```powershell
$env:PROXY_SCRAPER_BINARY = "C:\path\to\proxy-scraper-checker.exe"
```

Linux/macOS shell example:

```sh
export TELEGRAM_BOT_TOKEN='your-token-from-botfather'
export TELEGRAM_ALLOWED_USER_IDS='123456789'
export PROXY_SCRAPER_BINARY="$PWD/engine/proxy-scraper-checker"
python3 -m proxy_scout
```

## Commands

- `/id` — show your Telegram user ID for setup.
- `/help` — show available commands.
- `/scan` — fetch the configured feeds and start a scan.
- `/status` — show the latest successful scan.
- `/list` — show up to ten fastest results from the latest scan.
- `/list http`, `/list socks4`, or `/list socks5` — filter the list by protocol.

Only one scan runs at a time. Each scan collects at most 2,000 candidates and has a five-minute hard limit. The checker uses 64 concurrent checks, an eight-second request timeout and a three-second connect timeout. Scan results report candidates sent to the engine and verified survivors; the engine does not report a reliable count of every attempted candidate.

## Feeds and results

The catalog currently contains 72 distinct HTTPS feeds: 37 HTTP-proxy feeds, 10 SOCKS4 feeds, and 25 SOCKS5 feeds. Each scan attempts the configured feeds with up to 16 fetches in parallel; failed feeds are skipped. The catalog combines directly parseable feeds from the three supplied scraper projects. It omits HTTP-only, mixed-protocol, dynamically discovered, and obfuscated sources that this fixed HTTPS text/HTML collector cannot classify or parse reliably. Edit `config/sources.json` to change the catalog. Each feed has a 10-second total deadline, redirects are rejected, and each response is capped at 2 MiB. Telegram users cannot submit feed URLs.

`config/checker.toml` controls the engine's HTTPS check URL and concurrency. The bot stores the latest successful sanitized scan in `data/latest.json`. Generated inputs are under `input/`; the engine's raw JSON is transient under `out/` and removed after every scan, including failed scans.

This version checks IPv4 endpoints only. It does not provide a proxy relay, scheduled scans, or IPv6 endpoint support. It does not claim a benchmarked speed or accuracy advantage over the upstream projects; it reports measured latency and scan counts for its own runs.

## Important

Public proxies are untrusted and short-lived. Their operators may observe or change traffic, and a proxy that works now may fail moments later. Do not send passwords, tokens, personal data or other sensitive traffic through them. ProxyScout does not guarantee anonymity or availability.

## License and notices

ProxyScout is MIT-licensed. See [`THIRD_PARTY_NOTICES.md`](THIRD_PARTY_NOTICES.md) for the upstream checker attribution and license.

