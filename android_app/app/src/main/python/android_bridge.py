"""Bridge module between the Android Java UI and v2ray_finder."""

from __future__ import annotations

import json
import os
from typing import Any

from v2ray_finder import Pipeline
from v2ray_finder.real_validation import check_real_validation_batch
from v2ray_finder.source_performance import build_source_performance
from v2ray_finder.sources import get_enabled_sources

_real_check_enabled = False
_real_check_binary_path = ""
_real_check_limit = 50


def set_real_check(enabled: bool = False, binary_path: str = "", limit: int = 50) -> str:
    """Configure optional Android real validation through xray.

    Java calls this before ``scan``. The existing ``scan`` signature remains
    backward compatible for older UI code and tests.
    """
    global _real_check_enabled, _real_check_binary_path, _real_check_limit
    _real_check_enabled = bool(enabled)
    _real_check_binary_path = binary_path or ""
    _real_check_limit = max(1, min(int(limit or 50), 200))
    available = bool(_real_check_binary_path and os.path.isfile(_real_check_binary_path))
    return json.dumps(
        {
            "requested": _real_check_enabled,
            "available": available,
            "binary_path": _real_check_binary_path if available else "",
            "limit": _real_check_limit,
        },
        ensure_ascii=False,
    )


def _validation_error_summary(rr: Any) -> str:
    err = getattr(rr, "error", None)
    if err:
        return str(err)
    probes = getattr(rr, "probe_results", []) or []
    failed = []
    for p in probes:
        if isinstance(p, dict) and not p.get("ok"):
            failed.append(f"{p.get('name', '?')}:{p.get('status', 0)}")
    return "failed probes: " + ", ".join(failed[:4]) if failed else "real validation failed"


def scan(limit: int = 200, timeout: float = 5.0, check_health: bool = False, token: str = "") -> str:
    """Run the real v2ray_finder Pipeline and return compact JSON for Android."""
    limit = max(1, min(int(limit or 50), 200))
    timeout = max(1.0, min(float(timeout or 5.0), 60.0))
    token = token or None

    pipeline = Pipeline(
        check_health=bool(check_health),
        check_http_probe=False,
        check_google_204=False,
        timeout=timeout,
        limit=limit,
        github_token=token,
        fetch_concurrency=4,
        health_batch_size=50,
        max_total_configs=limit,
    )
    result = pipeline.run()

    health_by_config: dict[str, dict[str, Any]] = {
        str(h.get("config", "")): h for h in result.health_dicts if h.get("config")
    }

    items: list[dict[str, Any]] = []
    for score in result.scores[:200]:
        health = health_by_config.get(score.config, {})
        source_url = health.get("source_url", "") or ""
        items.append(
            {
                "config": score.config,
                "protocol": score.protocol,
                "total": float(score.total),
                "grade": score.grade,
                "latency_ms": None if score.latency_ms is None else float(score.latency_ms),
                "source": source_url,
                "source_trust": int(health.get("source_trust", 0) or 0),
                "real_checked": False,
                "validation_ok": None,
                "google_204_ok": None,
                "confidence_score": None,
                "confidence_level": None,
                "passed_probes": None,
                "total_probes": None,
                "stability_passes": None,
                "stability_attempts": None,
                "real_latency_ms": None,
                "real_error": None,
            }
        )

    configs = result.top_configs if result.scores else result.configs
    stats = dict(result.stats)
    real_results = []

    real_info: dict[str, Any] = {
        "requested": bool(_real_check_enabled),
        "enabled": False,
        "available": False,
        "checked": 0,
        "ok": 0,
        "limit": _real_check_limit,
        "message": "",
        "engine": "real_validation_v2",
        "probes": ["google_204", "gstatic_204", "google_www_204", "cloudflare_trace"],
    }

    if _real_check_enabled:
        binary_ok = bool(_real_check_binary_path and os.path.isfile(_real_check_binary_path))
        real_info["available"] = binary_ok
        if not binary_ok:
            real_info["message"] = "xray binary is not bundled in this APK build."
        elif not result.scores:
            real_info["message"] = "No scored configs available for real validation."
        else:
            try:
                candidates = [s.config for s in result.scores[:_real_check_limit]]
                real_results = check_real_validation_batch(
                    candidates,
                    max_workers=4,
                    timeout=max(timeout, 6.0),
                    binary_path=_real_check_binary_path,
                    auto_download=False,
                    stability_attempts=2,
                )
                real_map = {r.config: r for r in real_results}
                error_samples = []
                for r in real_results:
                    if not getattr(r, "validation_ok", False):
                        error_samples.append(f"{r.protocol}: {_validation_error_summary(r)}")
                real_info["error_samples"] = error_samples[:8]

                verified_items: list[dict[str, Any]] = []
                for item in items:
                    rr = real_map.get(item["config"])
                    if rr is None:
                        continue
                    item["real_checked"] = True
                    item["validation_ok"] = bool(rr.validation_ok)
                    item["google_204_ok"] = bool(rr.google_204_ok)
                    item["confidence_score"] = float(rr.confidence_score)
                    item["confidence_level"] = rr.confidence_level
                    item["passed_probes"] = int(rr.passed_probes)
                    item["total_probes"] = int(rr.total_probes)
                    item["stability_passes"] = int(rr.stability_passes)
                    item["stability_attempts"] = int(rr.stability_attempts)
                    item["real_latency_ms"] = None if rr.latency_ms is None else float(rr.latency_ms)
                    item["real_error"] = rr.error
                    if rr.latency_ms is not None:
                        item["latency_ms"] = float(rr.latency_ms)
                    if rr.validation_ok:
                        verified_items.append(item)

                items = verified_items
                configs = [item["config"] for item in items]
                real_info["enabled"] = True
                real_info["checked"] = len(real_results)
                real_info["ok"] = len(configs)
                real_info["message"] = (
                    f"Real Validation v2 checked {len(real_results)} configs; {len(configs)} passed."
                )
                stats["real_checked"] = len(real_results)
                stats["real_ok"] = len(configs)
                stats["healthy"] = len(configs)
                stats["scored"] = len(configs)
            except Exception as exc:
                real_info["message"] = f"real validation failed: {exc}"

    source_performance = build_source_performance(
        sources=get_enabled_sources(),
        health_dicts=result.health_dicts,
        fetch_errors=result.failed_sources,
        real_results=real_results,
    )
    stats["source_performance"] = source_performance

    failed_sources: list[dict[str, Any]] = []
    if _real_check_enabled and real_info.get("checked", 0) and real_info.get("ok", 0) == 0:
        failed_sources.append(
            {
                "url": "xray://real-validation-v2",
                "error_type": "real_validation_failed",
                "message": real_info.get("message", "real validation returned zero working configs")
                + " Samples: "
                + " | ".join(real_info.get("error_samples", [])[:5]),
                "details": real_info,
            }
        )
    for url, error in result.failed_sources.items():
        details = error.get("details") if isinstance(error, dict) else {}
        failed_sources.append(
            {
                "url": url,
                "error_type": error.get("error_type", "unknown_error") if isinstance(error, dict) else "unknown_error",
                "message": error.get("message", str(error)) if isinstance(error, dict) else str(error),
                "details": details if isinstance(details, dict) else {},
            }
        )

    payload = {
        "stats": stats,
        "configs": configs[:limit],
        "items": items,
        "failed_sources": failed_sources,
        "real_check": real_info,
        "source_performance": source_performance,
    }
    return json.dumps(payload, ensure_ascii=False)
