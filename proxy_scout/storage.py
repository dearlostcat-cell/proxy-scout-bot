"""Atomic persistence for the latest successful sanitized scan."""

from __future__ import annotations

import json
import ipaddress
import logging
import math
import os
from pathlib import Path

from .config import Settings, ensure_runtime_directories
from .models import PROTOCOLS, ProxyRecord, ScanSummary

LOGGER = logging.getLogger(__name__)


def save_latest(settings: Settings, summary: ScanSummary) -> None:
    """Replace the latest result only after a complete successful scan."""

    ensure_runtime_directories(settings)
    temporary = settings.latest_results.with_suffix(".json.tmp")
    payload = json.dumps(summary.to_dict(), ensure_ascii=True, indent=2) + "\n"
    temporary.write_text(payload, encoding="utf-8")
    os.replace(temporary, settings.latest_results)


def _load_proxy(value: object) -> ProxyRecord | None:
    if not isinstance(value, dict):
        return None
    try:
        protocol = value["protocol"]
        host = value["host"]
        port = value["port"]
        latency_ms = value["latency_ms"]
        exit_ip = value.get("exit_ip")
        if (
            protocol not in PROTOCOLS
            or not isinstance(host, str)
            or type(port) is not int
            or not 1 <= port <= 65535
            or not isinstance(latency_ms, (int, float))
            or isinstance(latency_ms, bool)
            or not math.isfinite(float(latency_ms))
            or float(latency_ms) < 0
            or (exit_ip is not None and not isinstance(exit_ip, str))
        ):
            return None
        address = ipaddress.IPv4Address(host)
        if not address.is_global:
            return None
        if exit_ip is not None and not ipaddress.IPv4Address(exit_ip).is_global:
            exit_ip = None
        return ProxyRecord(protocol, host, port, float(latency_ms), exit_ip)
    except (KeyError, TypeError, ValueError, ipaddress.AddressValueError):
        return None


def load_latest(settings: Settings) -> ScanSummary | None:
    """Read the most recent successful sanitized scan, if one exists."""

    path = settings.latest_results
    if not path.is_file():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(payload, dict):
            return None
        started_at = payload["started_at"]
        completed_at = payload["completed_at"]
        duration_seconds = payload["duration_seconds"]
        collected = payload["collected_by_protocol"]
        raw_results = payload["results"]
        if (
            not isinstance(started_at, str)
            or not isinstance(completed_at, str)
            or not isinstance(duration_seconds, (int, float))
            or isinstance(duration_seconds, bool)
            or not math.isfinite(float(duration_seconds))
            or not isinstance(collected, dict)
            or not isinstance(raw_results, list)
        ):
            return None
        collected_by_protocol = {
            protocol: int(collected.get(protocol, 0))
            for protocol in PROTOCOLS
        }
        if any(value < 0 for value in collected_by_protocol.values()):
            return None
        results = tuple(
            record
            for value in raw_results
            if (record := _load_proxy(value)) is not None
        )
        return ScanSummary(
            started_at=started_at,
            completed_at=completed_at,
            duration_seconds=float(duration_seconds),
            collected_by_protocol=collected_by_protocol,
            results=results,
        )
    except (OSError, json.JSONDecodeError, KeyError, TypeError, ValueError) as exc:
        LOGGER.warning("Could not read the latest scan file (%s)", type(exc).__name__)
        return None
