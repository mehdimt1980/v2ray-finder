"""Bridge module between the Android Java UI and v2ray_finder."""

from __future__ import annotations

import json
from typing import Any

from v2ray_finder import Pipeline


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
            }
        )

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

    configs = result.top_configs if result.scores else result.configs
    payload = {
        "stats": result.stats,
        "configs": configs[:limit],
        "items": items,
        "failed_sources": failed_sources,
    }
    return json.dumps(payload, ensure_ascii=False)
