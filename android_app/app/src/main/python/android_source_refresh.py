"""Android bridge for manual Remote Source Registry refresh."""

from __future__ import annotations

import json

from v2ray_finder.remote_source_registry import refresh_remote_registry_now


def refresh_sources_now() -> str:
    """Force-refresh the remote source registry and return JSON for Java UI."""
    result = refresh_remote_registry_now(timeout=12.0)
    return json.dumps(result, ensure_ascii=False)
