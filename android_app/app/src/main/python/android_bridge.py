"""Bridge module between the Android Java UI and v2ray_finder."""

from __future__ import annotations

import json
import os
from typing import Any

from v2ray_finder import Pipeline

_real_check_enabled = False
_real_check_binary_path = ""
_real_check_limit = 200


def set_real_check(enabled: bool = False, binary_path: str = "", limit: int = 200) -> str:
    """Configure optional Android Layer-3 xray/Google-204 checking.

    Java calls this before ``scan``. The existing ``scan`` signature remains
    backward compatible for older UI code and tests.
    """
    global _real_check_enabled, _real_check_binary_path, _real_check_limit
    _real_check_enabled = bool(enabled)
    _real_check_binary_path = binary_path or ""
    _real_check_limit = max(1, min(int(limit or 200), 400))
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


def scan(limit: int = 200, timeout: float = 5.0, check_health: bool = False, token: str = "") -> str:
    """Run the real v2ray_finder Pipeline and return compact JSON for Android."""
    limit = max(1, min(int(limit or 200), 5000))
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

    items: list[dict[str, Any]] = []
    for score in result.scores[:200]:
        items.append(
            {
                "config": score.config,
                "protocol": score.protocol,
                "total": float(score.total),
                "grade": score.grade,
                "latency_ms": None if score.latency_ms is None else float(score.latency_ms),
                "source": getattr(score, "source", "") or "",
                "real_checked": False,
                "google_204_ok": None,
                "real_latency_ms": None,
                "real_error": None,
            }
        )

    configs = result.top_configs if result.scores else result.configs
    stats = dict(result.stats)

    real_info: dict[str, Any] = {
        "requested": bool(_real_check_enabled),
        "enabled": False,
        "available": False,
        "checked": 0,
        "ok": 0,
        "limit": _real_check_limit,
        "message": "",
    }

    if _real_check_enabled:
        binary_ok = bool(_real_check_binary_path and os.path.isfile(_real_check_binary_path))
        real_info["available"] = binary_ok
        if not binary_ok:
            real_info["message"] = "xray binary is not bundled in this APK build."
        elif not result.scores:
            real_info["message"] = "No scored configs available for real xray check."
        else:
            try:
                from v2ray_finder.xray_connectivity import check_real_connectivity_batch

                candidates = [s.config for s in result.scores[:_real_check_limit]]
                real_results = check_real_connectivity_batch(
                    candidates,
                    max_workers=4,
                    timeout=max(timeout, 6.0),
                    binary_path=_real_check_binary_path,
                    auto_download=False,
                )
                real_map = {r.config: r for r in real_results}
                verified_items: list[dict[str, Any]] = []
                for item in items:
                    rr = real_map.get(item["config"])
                    if rr is None:
                        continue
                    item["real_checked"] = True
                    item["google_204_ok"] = bool(rr.google_204_ok)
                    item["real_latency_ms"] = None if rr.latency_ms is None else float(rr.latency_ms)
                    item["real_error"] = rr.error
                    if rr.latency_ms is not None:
                        item["latency_ms"] = float(rr.latency_ms)
                    if rr.google_204_ok:
                        verified_items.append(item)

                items = verified_items
                configs = [item["config"] for item in items]
                real_info["enabled"] = True
                real_info["checked"] = len(real_results)
                real_info["ok"] = len(configs)
                real_info["message"] = (
                    f"xray Google-204 checked {len(real_results)} configs; {len(configs)} passed."
                )
                stats["real_checked"] = len(real_results)
                stats["real_ok"] = len(configs)
                stats["healthy"] = len(configs)
                stats["scored"] = len(configs)
            except Exception as exc:
                real_info["message"] = f"xray real check failed: {exc}"

    failed_sources: list[dict[str, Any]] = []
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
    }
    return json.dumps(payload, ensure_ascii=False)
