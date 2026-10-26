"""Minimal Telegram Bot API client with token-safe errors."""

from __future__ import annotations

import asyncio
import json
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Any


@dataclass(slots=True)
class TelegramApiError(RuntimeError):
    """A Bot API error that never includes the token-bearing request URL."""

    message: str
    retryable: bool = False
    retry_after: int | None = None

    def __str__(self) -> str:
        return self.message


class TelegramClient:
    """Call the small subset of Telegram methods used by ProxyScout."""

    def __init__(self, token: str) -> None:
        self._token = token

    def _request_sync(
        self, method: str, payload: dict[str, object], timeout: float
    ) -> Any:
        url = f"https://api.telegram.org/bot{self._token}/{method}"
        request = urllib.request.Request(
            url,
            data=json.dumps(payload).encode("utf-8"),
            headers={"Content-Type": "application/json", "User-Agent": "ProxyScout/0.1"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:
                body = response.read(2 * 1024 * 1024 + 1)
        except urllib.error.HTTPError as exc:
            retry_after = None
            try:
                error_payload = json.loads(exc.read(64 * 1024).decode("utf-8"))
                retry_after = error_payload.get("parameters", {}).get("retry_after")
            except (AttributeError, UnicodeDecodeError, json.JSONDecodeError):
                pass
            retryable = exc.code == 429 or exc.code >= 500
            raise TelegramApiError(
                f"Telegram API returned HTTP {exc.code}",
                retryable=retryable,
                retry_after=retry_after if isinstance(retry_after, int) else None,
            ) from None
        except (OSError, TimeoutError, urllib.error.URLError):
            raise TelegramApiError("Telegram API transport failed", retryable=True) from None

        if len(body) > 2 * 1024 * 1024:
            raise TelegramApiError("Telegram API response exceeded 2 MiB")
        try:
            result = json.loads(body.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            raise TelegramApiError("Telegram API returned invalid JSON") from None
        if not isinstance(result, dict):
            raise TelegramApiError("Telegram API returned an invalid response")
        if result.get("ok") is not True:
            code = result.get("error_code")
            parameters = result.get("parameters")
            retry_after = (
                parameters.get("retry_after") if isinstance(parameters, dict) else None
            )
            retryable = code == 429 or (isinstance(code, int) and code >= 500)
            raise TelegramApiError(
                f"Telegram API request failed (code {code})",
                retryable=retryable,
                retry_after=retry_after if isinstance(retry_after, int) else None,
            )
        return result.get("result")

    async def call(
        self, method: str, payload: dict[str, object], timeout: float = 35.0
    ) -> Any:
        return await asyncio.to_thread(self._request_sync, method, payload, timeout)

    async def get_me(self) -> dict[str, object]:
        result = await self.call("getMe", {}, timeout=15.0)
        if not isinstance(result, dict):
            raise TelegramApiError("Telegram API returned an invalid bot identity")
        return result

    async def get_updates(self, offset: int, timeout: int = 25) -> list[dict[str, object]]:
        result = await self.call(
            "getUpdates",
            {"offset": offset, "timeout": timeout, "allowed_updates": ["message"]},
            timeout=float(timeout + 10),
        )
        if not isinstance(result, list):
            raise TelegramApiError("Telegram API returned invalid updates")
        return [update for update in result if isinstance(update, dict)]

    async def send_message(self, chat_id: int, text: str) -> None:
        safe_text = text if len(text) <= 4000 else text[:3997] + "..."
        await self.call(
            "sendMessage",
            {"chat_id": chat_id, "text": safe_text, "disable_web_page_preview": True},
            timeout=15.0,
        )
