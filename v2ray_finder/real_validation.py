"""Real Validation Engine v2.

This module performs stricter real-world validation through a local xray SOCKS5
proxy.  It extends the older single Google-204 check with multiple lightweight
HTTP probes, a confidence score and a simple two-pass stability signal.

The implementation intentionally uses the same low-level socket probe helpers as
``xray_connectivity.py`` so it has no additional runtime dependencies on Android.
"""

from __future__ import annotations

import socket
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

from .probes import socks5_http_get
from .scoring_curves import latency_to_score_100
from .xray_config_adapter import config_to_xray
from .xray_runner import XrayRunner


@dataclass(frozen=True)
class ProbeSpec:
    """A lightweight HTTP endpoint to test through the xray SOCKS5 proxy."""

    name: str
    host: str
    port: int
    path: str
    success_statuses: Tuple[int, ...]
    weight: float = 1.0


@dataclass
class ProbeResult:
    """Result for one probe endpoint."""

    name: str
    ok: bool
    status: int = 0
    latency_ms: Optional[float] = None
    expected_statuses: Tuple[int, ...] = field(default_factory=tuple)
    error: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "name": self.name,
            "ok": self.ok,
            "status": self.status,
            "latency_ms": self.latency_ms,
            "expected_statuses": list(self.expected_statuses),
            "error": self.error,
        }


@dataclass
class RealValidationResult:
    """Real validation output for one config.

    The most important backward-compatible fields are ``config``, ``protocol``,
    ``reachable``, ``google_204_ok``, ``latency_ms`` and ``error``.  Android and
    source-performance code can additionally use ``validation_ok`` and
    ``confidence_score``.
    """

    config: str
    protocol: str
    reachable: bool = False
    validation_ok: bool = False
    google_204_ok: bool = False
    latency_ms: Optional[float] = None
    error: Optional[str] = None
    socks_port: Optional[int] = None
    xray_version: Optional[str] = None
    retried: bool = False
    check_methods: List[str] = field(default_factory=list)
    probe_results: List[Dict[str, Any]] = field(default_factory=list)
    passed_probes: int = 0
    total_probes: int = 0
    confidence_score: float = 0.0
    confidence_level: str = "none"
    stability_attempts: int = 0
    stability_passes: int = 0

    @property
    def quality_score(self) -> float:
        if not self.reachable or self.latency_ms is None:
            return 0.0
        return round(max(0.0, latency_to_score_100(self.latency_ms)), 1)


DEFAULT_PROBES: Tuple[ProbeSpec, ...] = (
    ProbeSpec(
        name="google_204",
        host="clients3.google.com",
        port=80,
        path="/generate_204",
        success_statuses=(204,),
        weight=1.2,
    ),
    ProbeSpec(
        name="gstatic_204",
        host="connectivitycheck.gstatic.com",
        port=80,
        path="/generate_204",
        success_statuses=(204,),
        weight=1.0,
    ),
    ProbeSpec(
        name="google_www_204",
        host="www.google.com",
        port=80,
        path="/generate_204",
        success_statuses=(204,),
        weight=0.9,
    ),
    ProbeSpec(
        name="cloudflare_trace",
        host="one.one.one.one",
        port=80,
        path="/cdn-cgi/trace",
        # 200 is ideal.  301/302/307/308 still prove the proxy can reach the
        # destination and get an HTTP response, so they are useful fallback
        # reachability signals when Google endpoints fail.
        success_statuses=(200, 301, 302, 307, 308),
        weight=0.8,
    ),
)


def find_free_port() -> int:
    """Return an available localhost TCP port."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("", 0))
        s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        return int(s.getsockname()[1])


def _probe_once(socks_port: int, spec: ProbeSpec, timeout: float) -> ProbeResult:
    try:
        raw_ok, status, latency = socks5_http_get(
            socks_host="127.0.0.1",
            socks_port=socks_port,
            target_host=spec.host,
            target_port=spec.port,
            path=spec.path,
            timeout=timeout,
        )
        ok = bool(raw_ok and status in spec.success_statuses)
        return ProbeResult(
            name=spec.name,
            ok=ok,
            status=int(status or 0),
            latency_ms=float(latency) if latency is not None else None,
            expected_statuses=spec.success_statuses,
            error=None if ok else f"unexpected status {status}",
        )
    except Exception as exc:
        return ProbeResult(
            name=spec.name,
            ok=False,
            status=0,
            latency_ms=None,
            expected_statuses=spec.success_statuses,
            error=str(exc),
        )


def _run_probe_set(
    socks_port: int,
    timeout: float,
    probes: Sequence[ProbeSpec] = DEFAULT_PROBES,
) -> List[ProbeResult]:
    return [_probe_once(socks_port, spec, timeout) for spec in probes]


def _attempt_passed(results: Sequence[ProbeResult]) -> bool:
    ok_count = sum(1 for r in results if r.ok)
    google_ok = any(r.ok and r.name in {"google_204", "gstatic_204", "google_www_204"} for r in results)
    return google_ok or ok_count >= 2


def _confidence_level(score: float) -> str:
    if score >= 85:
        return "very_high"
    if score >= 70:
        return "high"
    if score >= 55:
        return "medium"
    if score >= 35:
        return "low"
    return "none"


def _summarize(
    attempts: Sequence[Sequence[ProbeResult]],
    probes: Sequence[ProbeSpec] = DEFAULT_PROBES,
) -> Tuple[bool, bool, Optional[float], int, int, float, str, List[Dict[str, Any]], Optional[str]]:
    flat: List[ProbeResult] = [r for attempt in attempts for r in attempt]
    total = len(flat)
    passed = sum(1 for r in flat if r.ok)
    reachable = passed > 0
    google_204_ok = any(r.ok and r.name in {"google_204", "gstatic_204", "google_www_204"} for r in flat)
    latencies = [float(r.latency_ms) for r in flat if r.ok and r.latency_ms is not None]
    latency_ms = round(min(latencies), 1) if latencies else None
    stability_attempts = len(attempts)
    stability_passes = sum(1 for a in attempts if _attempt_passed(a))

    weighted_total = 0.0
    weighted_ok = 0.0
    weights = {p.name: p.weight for p in probes}
    for r in flat:
        w = float(weights.get(r.name, 1.0))
        weighted_total += w
        if r.ok:
            weighted_ok += w
    probe_score = weighted_ok / weighted_total if weighted_total else 0.0
    stability_score = stability_passes / stability_attempts if stability_attempts else 0.0
    latency_score = (latency_to_score_100(latency_ms) / 100.0) if latency_ms is not None else 0.0
    google_bonus = 1.0 if google_204_ok else 0.0

    confidence = (
        0.50 * probe_score
        + 0.25 * stability_score
        + 0.15 * latency_score
        + 0.10 * google_bonus
    ) * 100.0
    confidence = round(max(0.0, min(100.0, confidence)), 1)
    validation_ok = reachable and confidence >= 55.0 and stability_passes >= 1

    if not reachable:
        errors = [r.error or f"{r.name}: failed" for r in flat if not r.ok]
        error = "; ".join(errors[:3]) if errors else "all probes failed"
    elif not validation_ok:
        error = f"low confidence: {confidence:.1f}%"
    else:
        error = None

    return (
        reachable,
        validation_ok,
        latency_ms,
        passed,
        total,
        confidence,
        _confidence_level(confidence),
        [r.to_dict() for r in flat],
        error,
    )


def validate_one(
    uri: str,
    local_port: int = 10900,
    timeout: float = 8.0,
    binary_path: Optional[str] = None,
    auto_download: bool = True,
    stability_attempts: int = 2,
    stability_delay: float = 0.35,
    probes: Sequence[ProbeSpec] = DEFAULT_PROBES,
) -> RealValidationResult:
    """Start xray for one URI and run multi-probe real validation."""
    if "://" not in uri:
        return RealValidationResult(config=uri, protocol="unknown", error="Not a valid URI")

    protocol = uri.split("://", 1)[0].lower()
    retried = False

    def _build_and_start(port: int) -> Tuple[Optional[str], Optional[XrayRunner]]:
        try:
            cfg = config_to_xray(uri, local_port=port)
            runner = XrayRunner(local_port=port, binary_path=binary_path, auto_download=auto_download)
            runner.start(cfg)
            return None, runner
        except Exception as exc:
            try:
                runner.stop()  # type: ignore[name-defined]
            except Exception:
                pass
            return str(exc), None

    err, runner = _build_and_start(local_port)
    if err is not None:
        retry_port = find_free_port()
        retry_err, runner = _build_and_start(retry_port)
        retried = True
        if retry_err is not None:
            return RealValidationResult(
                config=uri,
                protocol=protocol,
                error=f"xray start failed: {err} (retry: {retry_err})",
                retried=True,
            )
        local_port = retry_port

    assert runner is not None
    try:
        attempts: List[List[ProbeResult]] = []
        first = _run_probe_set(local_port, timeout, probes=probes)
        attempts.append(first)
        if _attempt_passed(first):
            for _ in range(max(0, stability_attempts - 1)):
                time.sleep(max(0.0, stability_delay))
                attempts.append(_run_probe_set(local_port, timeout, probes=probes))

        (
            reachable,
            validation_ok,
            latency_ms,
            passed,
            total,
            confidence,
            level,
            probe_dicts,
            error,
        ) = _summarize(attempts, probes=probes)

        return RealValidationResult(
            config=uri,
            protocol=protocol,
            reachable=reachable,
            validation_ok=validation_ok,
            google_204_ok=any(
                p.get("ok") and p.get("name") in {"google_204", "gstatic_204", "google_www_204"}
                for p in probe_dicts
            ),
            latency_ms=latency_ms,
            error=error,
            socks_port=local_port,
            retried=retried,
            check_methods=["xray_start", "socks5_probe", "multi_probe", "confidence", "stability"],
            probe_results=probe_dicts,
            passed_probes=passed,
            total_probes=total,
            confidence_score=confidence,
            confidence_level=level,
            stability_attempts=len(attempts),
            stability_passes=sum(1 for a in attempts if _attempt_passed(a)),
        )
    finally:
        runner.stop()


def check_real_validation_batch(
    uris: List[str],
    max_workers: int = 4,
    local_port_base: int = 10900,
    timeout: float = 8.0,
    binary_path: Optional[str] = None,
    auto_download: bool = True,
    stability_attempts: int = 2,
) -> List[RealValidationResult]:
    """Run Real Validation Engine v2 on a batch of configs."""
    import threading

    results: List[RealValidationResult] = []
    port_lock = threading.Lock()
    port_counter = [local_port_base]

    def _get_port() -> int:
        with port_lock:
            p = port_counter[0]
            port_counter[0] += 1
            return p

    def _worker(uri: str) -> RealValidationResult:
        return validate_one(
            uri,
            local_port=_get_port(),
            timeout=timeout,
            binary_path=binary_path,
            auto_download=auto_download,
            stability_attempts=stability_attempts,
        )

    with ThreadPoolExecutor(max_workers=max_workers) as pool:
        futures = {pool.submit(_worker, u): u for u in uris}
        for fut in as_completed(futures):
            uri = futures[fut]
            try:
                results.append(fut.result())
            except Exception as exc:
                results.append(
                    RealValidationResult(
                        config=uri,
                        protocol=uri.split("://", 1)[0] if "://" in uri else "unknown",
                        error=str(exc),
                    )
                )

    results.sort(
        key=lambda r: (
            not r.validation_ok,
            -r.confidence_score,
            r.latency_ms if r.latency_ms is not None else 999999.0,
        )
    )
    return results
