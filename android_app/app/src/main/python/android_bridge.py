"""Bridge module between the Android Java UI and v2ray_finder.

This file intentionally stays small.  Android still calls ``android_bridge`` for
backward compatibility, while the actual scan is delegated to
``android_bridge_balanced`` so source-balanced sampling is active even when the
Java UI has not been patched yet.
"""

from __future__ import annotations

import json
import os
from typing import Any

_real_check_enabled = False
_real_check_binary_path = ""
_real_check_limit = 50


def set_real_check(enabled: bool = False, binary_path: str = "", limit: int = 50) -> str:
    """Configure optional Android real validation through xray."""
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
    """Run the source-balanced Android scan.

    Importing inside the function avoids circular-import problems because
    ``android_bridge_balanced`` reads this module's real-check state.
    """
    from android_bridge_balanced import scan as balanced_scan

    return balanced_scan(limit, timeout, check_health, token)
