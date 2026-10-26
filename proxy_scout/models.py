"""Small immutable data records shared by the scan pipeline."""

from __future__ import annotations

from dataclasses import dataclass

PROTOCOLS = ("http", "socks4", "socks5")


@dataclass(frozen=True, slots=True)
class FeedBatch:
    """Candidates that passed the feed parser and the scan cap."""

    by_protocol: dict[str, tuple[str, ...]]

    @property
    def candidate_count(self) -> int:
        return sum(len(items) for items in self.by_protocol.values())

    @property
    def counts(self) -> dict[str, int]:
        return {protocol: len(self.by_protocol.get(protocol, ())) for protocol in PROTOCOLS}


@dataclass(frozen=True, slots=True)
class ProxyRecord:
    """A verified proxy with fields safe to persist and send to Telegram."""

    protocol: str
    host: str
    port: int
    latency_ms: float
    exit_ip: str | None

    def to_dict(self) -> dict[str, str | int | float | None]:
        return {
            "protocol": self.protocol,
            "host": self.host,
            "port": self.port,
            "latency_ms": self.latency_ms,
            "exit_ip": self.exit_ip,
        }


@dataclass(frozen=True, slots=True)
class ScanSummary:
    """Persisted scan totals and its sanitized surviving proxies."""

    started_at: str
    completed_at: str
    duration_seconds: float
    collected_by_protocol: dict[str, int]
    results: tuple[ProxyRecord, ...]

    @property
    def candidate_count(self) -> int:
        return sum(self.collected_by_protocol.values())

    @property
    def working_by_protocol(self) -> dict[str, int]:
        counts = {protocol: 0 for protocol in PROTOCOLS}
        for proxy in self.results:
            counts[proxy.protocol] = counts.get(proxy.protocol, 0) + 1
        return counts

    @property
    def working_count(self) -> int:
        return len(self.results)

    def to_dict(self) -> dict[str, object]:
        return {
            "started_at": self.started_at,
            "completed_at": self.completed_at,
            "duration_seconds": self.duration_seconds,
            "collected_by_protocol": self.collected_by_protocol,
            "working_by_protocol": self.working_by_protocol,
            "candidate_count": self.candidate_count,
            "working_count": self.working_count,
            "results": [proxy.to_dict() for proxy in self.results],
        }
