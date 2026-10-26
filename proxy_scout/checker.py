"""Run the pinned Rust checker and persist only verified public proxies."""

from __future__ import annotations

import asyncio
import ipaddress
import json
import logging
import math
import os
import time
from datetime import datetime, timezone
from pathlib import Path

from .config import Settings, ensure_runtime_directories
from .feeds import collect_candidates
from .models import PROTOCOLS, ProxyRecord, ScanSummary
from .storage import save_latest

LOGGER = logging.getLogger(__name__)


class ScanError(RuntimeError):
    """Raised when feed collection or the checker cannot complete a scan."""


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _utc_text(value: datetime) -> str:
    return value.isoformat(timespec="seconds").replace("+00:00", "Z")


def _parse_verified_results(path: Path) -> tuple[ProxyRecord, ...]:
    try:
        raw_results = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ScanError("checker did not produce valid JSON results") from exc
    if not isinstance(raw_results, list):
        raise ScanError("checker JSON results were not a list")

    results: list[ProxyRecord] = []
    for value in raw_results:
        if not isinstance(value, dict):
            continue
        if value.get("username") not in (None, "") or value.get("password") not in (None, ""):
            continue
        protocol = value.get("protocol")
        host = value.get("host")
        port = value.get("port")
        timeout = value.get("timeout")
        exit_ip = value.get("exit_ip")
        if (
            not isinstance(protocol, str)
            or protocol.lower() not in PROTOCOLS
            or not isinstance(host, str)
            or type(port) is not int
            or not 1 <= port <= 65535
            or not isinstance(timeout, (int, float))
            or isinstance(timeout, bool)
            or not math.isfinite(float(timeout))
            or float(timeout) < 0
        ):
            continue
        try:
            address = ipaddress.IPv4Address(host)
        except ipaddress.AddressValueError:
            continue
        if not address.is_global:
            continue
        normalized_exit_ip: str | None = None
        if isinstance(exit_ip, str):
            try:
                exit_address = ipaddress.IPv4Address(exit_ip)
                if exit_address.is_global:
                    normalized_exit_ip = str(exit_address)
            except ipaddress.AddressValueError:
                pass
        results.append(
            ProxyRecord(
                protocol=protocol.lower(),
                host=str(address),
                port=port,
                latency_ms=round(float(timeout) * 1000, 2),
                exit_ip=normalized_exit_ip,
            )
        )

    return tuple(sorted(results, key=lambda proxy: proxy.latency_ms))


async def _run_engine(settings: Settings, timeout_seconds: float) -> None:
    if not settings.checker_config.is_file():
        raise ScanError(f"checker config is missing: {settings.checker_config}")
    if not settings.checker_binary.is_file():
        raise ScanError(f"checker executable is missing: {settings.checker_binary}")

    output_path = settings.output_dir / "proxies.json"
    try:
        output_path.unlink()
    except FileNotFoundError:
        pass

    environment = os.environ.copy()
    environment["PROXY_SCRAPER_CHECKER_CONFIG"] = str(settings.checker_config)
    try:
        process = await asyncio.create_subprocess_exec(
            str(settings.checker_binary),
            cwd=str(settings.root_dir),
            env=environment,
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.PIPE,
        )
    except OSError as exc:
        raise ScanError("could not start proxy-scraper-checker") from exc

    try:
        _, stderr = await asyncio.wait_for(process.communicate(), timeout=timeout_seconds)
    except asyncio.TimeoutError as exc:
        try:
            process.kill()
        except ProcessLookupError:
            pass
        await process.communicate()
        raise ScanError(
            f"checker exceeded the remaining scan time ({timeout_seconds:.0f} seconds)"
        ) from exc
    except asyncio.CancelledError:
        try:
            process.kill()
        except ProcessLookupError:
            pass
        await process.communicate()
        raise

    if process.returncode != 0:
        detail = (stderr or b"").decode("utf-8", errors="replace")[-1200:]
        LOGGER.error("Checker exited with code %s: %s", process.returncode, detail)
        raise ScanError(f"checker exited with code {process.returncode}")


async def run_scan(settings: Settings) -> ScanSummary:
    """Collect candidates, run the checker, and save the successful result."""

    ensure_runtime_directories(settings)
    started = _utc_now()
    monotonic_start = time.monotonic()
    raw_output_path = settings.output_dir / "proxies.json"

    try:
        batch = await asyncio.wait_for(
            collect_candidates(settings), timeout=settings.scan_timeout_seconds
        )
        if batch.candidate_count == 0:
            results: tuple[ProxyRecord, ...] = ()
        else:
            remaining = settings.scan_timeout_seconds - (time.monotonic() - monotonic_start)
            if remaining <= 0:
                raise ScanError(
                    f"scan exceeded the {settings.scan_timeout_seconds}-second limit"
                )
            await _run_engine(settings, remaining)
            results = _parse_verified_results(raw_output_path)
    except asyncio.TimeoutError as exc:
        raise ScanError(
            f"feed collection exceeded the {settings.scan_timeout_seconds}-second scan limit"
        ) from exc
    except ScanError:
        raise
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        raise ScanError(f"scan setup failed ({type(exc).__name__})") from exc
    finally:
        try:
            raw_output_path.unlink()
        except FileNotFoundError:
            pass
        except OSError as exc:
            LOGGER.error("Could not remove transient checker output (%s)", type(exc).__name__)
            raise ScanError("could not remove transient checker output") from exc

    completed = _utc_now()
    summary = ScanSummary(
        started_at=_utc_text(started),
        completed_at=_utc_text(completed),
        duration_seconds=round(time.monotonic() - monotonic_start, 2),
        collected_by_protocol=batch.counts,
        results=results,
    )
    save_latest(settings, summary)
    return summary
