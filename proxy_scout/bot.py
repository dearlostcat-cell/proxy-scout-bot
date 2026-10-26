"""Private Telegram command router and scan lifecycle."""

from __future__ import annotations

import asyncio
import logging
import math
import time
from .checker import ScanError, run_scan
from .config import ConfigurationError, Settings, load_settings
from .models import PROTOCOLS, ProxyRecord, ScanSummary
from .storage import load_latest
from .telegram_api import TelegramApiError, TelegramClient

LOGGER = logging.getLogger(__name__)
SCAN_COOLDOWN_SECONDS = 300
MAX_LIST_ITEMS = 10
SEND_RETRIES = 3


class ProxyScoutBot:
    """Run private Telegram commands and one bounded scan at a time."""

    def __init__(self, settings: Settings) -> None:
        self.settings = settings
        self.telegram = TelegramClient(settings.bot_token)
        self._scan_task: asyncio.Task[None] | None = None
        self._last_scan_started: dict[int, float] = {}

    async def _send(self, chat_id: int, text: str) -> None:
        delay = 1
        for attempt in range(SEND_RETRIES):
            try:
                await self.telegram.send_message(chat_id, text)
                return
            except TelegramApiError as exc:
                if not exc.retryable or attempt == SEND_RETRIES - 1:
                    LOGGER.warning("Could not send Telegram message (%s)", exc)
                    return
                wait = exc.retry_after or delay
                await asyncio.sleep(min(max(wait, 1), 30))
                delay = min(delay * 2, 8)

    async def _perform_scan(self, chat_id: int, user_id: int) -> None:
        try:
            summary = await run_scan(self.settings)
            await self._send(chat_id, self._format_summary(summary, heading="Scan complete"))
        except ScanError as exc:
            LOGGER.warning("Scan failed (%s)", exc)
            await self._send(chat_id, f"Scan failed: {exc}")
        except Exception as exc:
            LOGGER.exception("Unexpected scan failure")
            await self._send(
                chat_id,
                f"Scan failed unexpectedly ({type(exc).__name__}). Check the bot log on the host.",
            )
        finally:
            if self._scan_task is asyncio.current_task():
                self._scan_task = None

    def _format_summary(self, summary: ScanSummary, heading: str) -> str:
        lines = [
            heading,
            f"Finished: {summary.completed_at}",
            f"Candidates sent: {summary.candidate_count}",
            f"Verified working: {summary.working_count}",
            f"Duration: {summary.duration_seconds:.1f}s",
            "",
        ]
        for protocol in PROTOCOLS:
            lines.append(
                f"{protocol.upper()}: {summary.collected_by_protocol.get(protocol, 0)} candidates, "
                f"{summary.working_by_protocol.get(protocol, 0)} working"
            )
        lines.append("Use /list [http|socks4|socks5] for the fastest results.")
        return "\n".join(lines)

    @staticmethod
    def _format_proxy(proxy: ProxyRecord) -> str:
        exit_ip = f"; exit {proxy.exit_ip}" if proxy.exit_ip else ""
        return (
            f"{proxy.protocol}://{proxy.host}:{proxy.port} — "
            f"{proxy.latency_ms:.0f} ms{exit_ip}"
        )

    async def _handle_scan(self, chat_id: int, user_id: int, args: list[str]) -> None:
        if args:
            await self._send(chat_id, "Usage: /scan")
            return
        if self._scan_task is not None and not self._scan_task.done():
            await self._send(chat_id, "A scan is already running. Use /status after it finishes.")
            return

        now = time.monotonic()
        previous = self._last_scan_started.get(user_id)
        if previous is not None:
            remaining = SCAN_COOLDOWN_SECONDS - (now - previous)
            if remaining > 0:
                await self._send(
                    chat_id,
                    f"Please wait about {math.ceil(remaining)} seconds before starting another scan.",
                )
                return

        self._last_scan_started[user_id] = now
        self._scan_task = asyncio.create_task(self._perform_scan(chat_id, user_id))
        await self._send(
            chat_id,
            "Scan started. It checks up to 2,000 public IPv4 candidates and stops after five minutes.",
        )

    async def _handle_command(self, message: dict[str, object]) -> None:
        chat = message.get("chat")
        user = message.get("from")
        text = message.get("text")
        if not isinstance(chat, dict) or not isinstance(user, dict) or not isinstance(text, str):
            return
        if chat.get("type") != "private":
            return
        chat_id = chat.get("id")
        user_id = user.get("id")
        if type(chat_id) is not int or type(user_id) is not int:
            return

        parts = text.strip().split()
        if not parts or not parts[0].startswith("/"):
            return
        command = parts[0].split("@", 1)[0].lower()
        args = parts[1:]

        if command == "/id":
            await self._send(
                chat_id,
                f"Your Telegram user ID is {user_id}. Add it to TELEGRAM_ALLOWED_USER_IDS, then restart the bot.",
            )
            return
        if user_id not in self.settings.allowed_user_ids:
            return

        if command in ("/help", "/start"):
            await self._send(
                chat_id,
                "ProxyScout commands:\n"
                "/scan — collect and check configured feeds\n"
                "/status — show the latest successful scan\n"
                "/list [http|socks4|socks5] — show up to 10 fastest results\n"
                "/id — show your Telegram user ID\n\n"
                "Public proxies are untrusted and may stop working at any time. Do not use them for sensitive traffic.",
            )
        elif command == "/scan":
            await self._handle_scan(chat_id, user_id, args)
        elif command == "/status":
            await self._handle_status(chat_id, args)
        elif command == "/list":
            await self._handle_list(chat_id, args)

    async def _handle_status(self, chat_id: int, args: list[str]) -> None:
        if args:
            await self._send(chat_id, "Usage: /status")
            return
        if self._scan_task is not None and not self._scan_task.done():
            await self._send(chat_id, "A scan is running. Results will arrive when it completes.")
        latest = load_latest(self.settings)
        if latest is None:
            if self._scan_task is None or self._scan_task.done():
                await self._send(chat_id, "No successful scan has been saved yet. Use /scan to start one.")
            return
        await self._send(chat_id, self._format_summary(latest, heading="Latest successful scan"))

    async def _handle_list(self, chat_id: int, args: list[str]) -> None:
        if len(args) > 1:
            await self._send(chat_id, "Usage: /list [http|socks4|socks5]")
            return
        protocol = args[0].lower() if args else None
        if protocol is not None and protocol not in PROTOCOLS:
            await self._send(chat_id, "Choose one protocol: http, socks4, or socks5.")
            return
        latest = load_latest(self.settings)
        if latest is None:
            await self._send(chat_id, "No successful scan has been saved yet. Use /scan to start one.")
            return
        proxies = [proxy for proxy in latest.results if protocol is None or proxy.protocol == protocol]
        if not proxies:
            label = f" for {protocol.upper()}" if protocol else ""
            await self._send(chat_id, f"No working proxies{label} in the latest scan.")
            return
        label = f"{protocol.upper()} " if protocol else ""
        lines = [f"Fastest {label}proxies from {latest.completed_at}:"]
        lines.extend(self._format_proxy(proxy) for proxy in proxies[:MAX_LIST_ITEMS])
        await self._send(chat_id, "\n".join(lines))

    async def run(self) -> None:
        identity = await self.telegram.get_me()
        LOGGER.info("Starting Telegram bot @%s", identity.get("username", "unknown"))
        offset = 0
        delay = 1
        while True:
            try:
                updates = await self.telegram.get_updates(offset)
            except TelegramApiError as exc:
                LOGGER.warning("Telegram polling failed (%s)", exc)
                await asyncio.sleep(min(delay, 30))
                delay = min(delay * 2, 30)
                continue
            delay = 1
            for update in updates:
                update_id = update.get("update_id")
                if type(update_id) is int:
                    offset = max(offset, update_id + 1)
                message = update.get("message")
                if isinstance(message, dict):
                    try:
                        await self._handle_command(message)
                    except TelegramApiError as exc:
                        LOGGER.warning("Telegram command response failed (%s)", exc)


def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    try:
        settings = load_settings()
    except ConfigurationError as exc:
        raise SystemExit(f"Configuration error: {exc}") from None
    bot = ProxyScoutBot(settings)
    try:
        asyncio.run(bot.run())
    except KeyboardInterrupt:
        LOGGER.info("Bot stopped")
    except TelegramApiError as exc:
        raise SystemExit(f"Telegram startup failed: {exc}") from None
