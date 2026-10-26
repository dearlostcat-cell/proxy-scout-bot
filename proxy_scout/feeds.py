"""Fetch configured proxy feeds and keep only public IPv4 endpoints."""

from __future__ import annotations

import asyncio
import ipaddress
import json
import logging
import re
import ssl
from pathlib import Path
from urllib.parse import urlsplit

from .config import MAX_CANDIDATES, Settings, ensure_runtime_directories
from .models import FeedBatch, PROTOCOLS

LOGGER = logging.getLogger(__name__)
FEED_TIMEOUT_SECONDS = 10
MAX_FEED_BYTES = 2 * 1024 * 1024
MAX_FEED_CONCURRENCY = 16
MAX_HTTP_LINE_BYTES = 8 * 1024
MAX_HTTP_HEADER_BYTES = 64 * 1024
USER_AGENT = "ProxyScout/0.1 (+https://github.com/)"
PROXY_PATTERN = re.compile(
    r"(?<![A-Za-z0-9_.:])(?P<host>(?:[0-9]{1,3}\.){3}[0-9]{1,3})"
    r"\s*:\s*(?P<port>[0-9]{1,5})(?![A-Za-z0-9_.:_-])"
)


def _catalog_urls(path: Path) -> dict[str, list[str]]:
    with path.open("r", encoding="utf-8") as source_file:
        catalog = json.load(source_file)
    if not isinstance(catalog, dict):
        raise ValueError("source catalog must be an object keyed by protocol")

    result: dict[str, list[str]] = {}
    for protocol in PROTOCOLS:
        urls = catalog.get(protocol, [])
        if not isinstance(urls, list):
            raise ValueError(f"source catalog entry {protocol!r} must be a list")
        valid_urls: list[str] = []
        for url in urls:
            if not isinstance(url, str):
                continue
            try:
                parsed = urlsplit(url)
            except ValueError:
                LOGGER.warning("Ignoring a malformed %s feed URL", protocol)
                continue
            if (
                parsed.scheme == "https"
                and parsed.hostname
                and not parsed.username
                and not parsed.password
                and not parsed.fragment
            ):
                valid_urls.append(url)
            else:
                LOGGER.warning("Ignoring a non-HTTPS or malformed %s feed", protocol)
        result[protocol] = valid_urls
    return result


async def _read_headers(reader: asyncio.StreamReader) -> dict[str, list[str]]:
    headers: dict[str, list[str]] = {}
    total_bytes = 0
    while True:
        line = await reader.readline()
        total_bytes += len(line)
        if not line or len(line) > MAX_HTTP_LINE_BYTES or total_bytes > MAX_HTTP_HEADER_BYTES:
            raise ValueError("feed returned invalid or oversized HTTP headers")
        if line == b"\r\n":
            return headers
        if not line.endswith(b"\r\n") or line[:1] in (b" ", b"\t"):
            raise ValueError("feed returned a malformed HTTP header")
        name, separator, value = line[:-2].partition(b":")
        if not separator or not re.fullmatch(rb"[!#$%&'*+.^_`|~0-9A-Za-z-]+", name):
            raise ValueError("feed returned a malformed HTTP header")
        key = name.decode("ascii").lower()
        headers.setdefault(key, []).append(value.strip().decode("latin-1"))


async def _read_chunked_body(reader: asyncio.StreamReader) -> bytes:
    body = bytearray()
    trailer_bytes = 0
    while True:
        line = await reader.readline()
        if not line or len(line) > MAX_HTTP_LINE_BYTES or not line.endswith(b"\r\n"):
            raise ValueError("feed returned a malformed chunked body")
        size_text = line[:-2].partition(b";")[0].strip()
        if not size_text or not re.fullmatch(rb"[0-9A-Fa-f]+", size_text):
            raise ValueError("feed returned an invalid chunk size")
        chunk_size = int(size_text, 16)
        if chunk_size == 0:
            while True:
                trailer = await reader.readline()
                trailer_bytes += len(trailer)
                if (
                    not trailer
                    or len(trailer) > MAX_HTTP_LINE_BYTES
                    or trailer_bytes > MAX_HTTP_HEADER_BYTES
                    or not trailer.endswith(b"\r\n")
                ):
                    raise ValueError("feed returned invalid chunk trailers")
                if trailer == b"\r\n":
                    return bytes(body)
                if b":" not in trailer:
                    raise ValueError("feed returned invalid chunk trailers")
        if len(body) + chunk_size > MAX_FEED_BYTES:
            raise ValueError("feed exceeded the 2 MiB response limit")
        body.extend(await reader.readexactly(chunk_size))
        if await reader.readexactly(2) != b"\r\n":
            raise ValueError("feed returned a malformed chunked body")


async def _read_body(
    reader: asyncio.StreamReader, headers: dict[str, list[str]]
) -> bytes:
    transfer_encoding = [
        token.strip().lower()
        for value in headers.get("transfer-encoding", [])
        for token in value.split(",")
        if token.strip()
    ]
    content_lengths = [
        token.strip()
        for value in headers.get("content-length", [])
        for token in value.split(",")
    ]
    if transfer_encoding and content_lengths:
        raise ValueError("feed returned ambiguous HTTP body framing")
    if transfer_encoding:
        if transfer_encoding != ["chunked"]:
            raise ValueError("feed uses an unsupported transfer encoding")
        return await _read_chunked_body(reader)
    if content_lengths:
        if (
            any(not value.isdecimal() for value in content_lengths)
            or len(set(content_lengths)) != 1
        ):
            raise ValueError("feed returned an invalid content length")
        content_length = int(content_lengths[0])
        if content_length > MAX_FEED_BYTES:
            raise ValueError("feed exceeded the 2 MiB response limit")
        return await reader.readexactly(content_length)

    body = bytearray()
    while len(body) <= MAX_FEED_BYTES:
        chunk = await reader.read(min(64 * 1024, MAX_FEED_BYTES + 1 - len(body)))
        if not chunk:
            return bytes(body)
        body.extend(chunk)
    raise ValueError("feed exceeded the 2 MiB response limit")


async def _fetch_text(url: str) -> str:
    parsed = urlsplit(url)
    if (
        parsed.scheme != "https"
        or not parsed.hostname
        or parsed.username
        or parsed.password
        or parsed.fragment
    ):
        raise ValueError("feed URL must be HTTPS and contain no credentials")
    try:
        parsed_port = parsed.port
        port = 443 if parsed_port is None else parsed_port
        host = parsed.hostname.encode("idna").decode("ascii")
    except (UnicodeError, ValueError) as exc:
        raise ValueError("feed URL has an invalid host or port") from exc
    if not 1 <= port <= 65535:
        raise ValueError("feed URL has an invalid port")
    target = parsed.path or "/"
    if parsed.query:
        target += f"?{parsed.query}"
    try:
        target.encode("ascii")
    except UnicodeEncodeError as exc:
        raise ValueError("feed URL path must be URL-encoded") from exc
    if "\r" in target or "\n" in target:
        raise ValueError("feed URL path is malformed")

    host_header = f"[{host}]" if ":" in host else host
    if port != 443:
        host_header += f":{port}"

    writer: asyncio.StreamWriter | None = None
    async with asyncio.timeout(FEED_TIMEOUT_SECONDS):
        try:
            reader, writer = await asyncio.open_connection(
                host,
                port,
                ssl=ssl.create_default_context(),
                server_hostname=host,
                limit=MAX_HTTP_LINE_BYTES,
            )
            request = (
                f"GET {target} HTTP/1.1\r\n"
                f"Host: {host_header}\r\n"
                f"User-Agent: {USER_AGENT}\r\n"
                "Accept-Encoding: identity\r\n"
                "Connection: close\r\n\r\n"
            ).encode("ascii")
            writer.write(request)
            await writer.drain()

            status_line = await reader.readline()
            if not status_line or len(status_line) > MAX_HTTP_LINE_BYTES:
                raise ValueError("feed returned an invalid HTTP status line")
            try:
                status_parts = status_line.decode("latin-1").strip().split(None, 2)
                status = int(status_parts[1])
            except (IndexError, ValueError) as exc:
                raise ValueError("feed returned an invalid HTTP status line") from exc
            if (
                len(status_parts) < 2
                or status_parts[0] not in ("HTTP/1.0", "HTTP/1.1")
                or status != 200
            ):
                raise ValueError(f"feed returned HTTP {status}")

            headers = await _read_headers(reader)
            content_encoding = [
                value.strip().lower() for value in headers.get("content-encoding", [])
            ]
            if any(value not in ("", "identity") for value in content_encoding):
                raise ValueError("feed returned an unsupported content encoding")
            body = await _read_body(reader, headers)
        finally:
            if writer is not None:
                writer.transport.abort()
    return body.decode("utf-8", errors="replace")


def _parse_candidates(text: str, limit: int = MAX_CANDIDATES) -> list[str]:
    candidates: list[str] = []
    seen: set[str] = set()
    for match in PROXY_PATTERN.finditer(text):
        host = match.group("host")
        port_text = match.group("port")
        try:
            address = ipaddress.IPv4Address(host)
            port = int(port_text)
        except (ipaddress.AddressValueError, ValueError):
            continue
        if (
            not address.is_global
            or address.is_multicast
            or address.is_reserved
            or address.is_unspecified
            or not 1 <= port <= 65535
        ):
            continue
        candidate = f"{address}:{port}"
        if candidate not in seen:
            seen.add(candidate)
            candidates.append(candidate)
            if len(candidates) >= limit:
                break
    return candidates


async def _fetch_source(url: str, semaphore: asyncio.Semaphore) -> list[str]:
    async with semaphore:
        try:
            text = await _fetch_text(url)
            return _parse_candidates(text)
        except (TimeoutError, OSError, EOFError, ValueError) as exc:
            try:
                hostname = urlsplit(url).hostname or "unknown host"
            except ValueError:
                hostname = "unknown host"
            LOGGER.debug("Skipping %s feed (%s)", hostname, type(exc).__name__)
            return []


def _round_robin_sources(source_lists: list[list[str]]) -> list[str]:
    positions = [0] * len(source_lists)
    seen: set[str] = set()
    ordered: list[str] = []
    while True:
        advanced = False
        for index, source_list in enumerate(source_lists):
            while positions[index] < len(source_list):
                candidate = source_list[positions[index]]
                positions[index] += 1
                advanced = True
                if candidate not in seen:
                    seen.add(candidate)
                    ordered.append(candidate)
                    break
        if not advanced:
            return ordered


def _cap_protocols(by_protocol: dict[str, list[str]], limit: int) -> dict[str, tuple[str, ...]]:
    selected = {protocol: [] for protocol in PROTOCOLS}
    positions = {protocol: 0 for protocol in PROTOCOLS}
    count = 0
    while count < limit:
        advanced = False
        for protocol in PROTOCOLS:
            candidates = by_protocol.get(protocol, [])
            position = positions[protocol]
            if position < len(candidates):
                selected[protocol].append(candidates[position])
                positions[protocol] += 1
                count += 1
                advanced = True
                if count == limit:
                    break
        if not advanced:
            break
    return {protocol: tuple(selected[protocol]) for protocol in PROTOCOLS}


async def collect_candidates(settings: Settings) -> FeedBatch:
    """Fetch feeds concurrently, fairly cap unique candidates, and write inputs."""

    ensure_runtime_directories(settings)
    catalog = _catalog_urls(settings.source_catalog)
    semaphore = asyncio.Semaphore(MAX_FEED_CONCURRENCY)
    tasks: list[tuple[str, asyncio.Task[list[str]]]] = []
    for protocol in PROTOCOLS:
        for url in catalog[protocol]:
            tasks.append(
                (protocol, asyncio.create_task(_fetch_source(url, semaphore)))
            )

    by_protocol_sources: dict[str, list[list[str]]] = {protocol: [] for protocol in PROTOCOLS}
    if tasks:
        fetched = await asyncio.gather(*(task for _, task in tasks))
        for (protocol, _), candidates in zip(tasks, fetched, strict=True):
            by_protocol_sources[protocol].append(candidates)

    unique_by_protocol = {
        protocol: _round_robin_sources(by_protocol_sources[protocol])
        for protocol in PROTOCOLS
    }
    batch = FeedBatch(_cap_protocols(unique_by_protocol, settings.max_candidates))

    for protocol in PROTOCOLS:
        input_path = settings.input_dir / f"{protocol}.txt"
        temporary_path = input_path.with_suffix(".tmp")
        text = "\n".join(batch.by_protocol[protocol])
        temporary_path.write_text(text, encoding="utf-8")
        temporary_path.replace(input_path)

    return batch
