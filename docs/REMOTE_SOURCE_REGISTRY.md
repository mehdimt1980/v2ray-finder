# Remote Source Registry

Remote Source Registry lets the Python pipeline and Android APK refresh the trusted source list from GitHub without rebuilding or reinstalling the app after every source update.

Default remote registry:

```text
https://raw.githubusercontent.com/mehdimt1980/v2ray-finder/main/registry/sources.json
```

## Resolution order

The loader uses this order:

```text
1. fresh local remote cache, if inside TTL
2. remote GitHub registry, if enabled and reachable
3. stale local remote cache, if remote is unavailable
4. bundled registry/sources.json packaged with the app/package
5. minimal legacy fallback sources
```

Only active records are used in normal scans:

```text
official
trusted
```

These statuses are ignored unless explicitly requested for special tools:

```text
candidate
experimental
quarantine
disabled
```

## Runtime files

```text
v2ray_finder/remote_source_registry.py
v2ray_finder/sources.py
registry/sources.json
```

`v2ray_finder/sources.py` now delegates `get_enabled_sources()` to the remote registry loader. The old hard-coded source list has become only an emergency fallback.

## Cache

Default cache TTL:

```text
24 hours
```

Default cache path:

```text
<tempdir>/v2ray-finder/remote_sources.json
```

The cache avoids hitting GitHub on every scan. A remote fetch happens when the cache is missing or older than the TTL.

## Environment variables

| Variable | Meaning |
|---|---|
| `V2RAY_FINDER_REMOTE_REGISTRY_URL` | Override the remote registry URL |
| `V2RAY_FINDER_REMOTE_REGISTRY_TTL` | TTL in seconds, default `86400` |
| `V2RAY_FINDER_REGISTRY_CACHE` | Exact cache file path |
| `V2RAY_FINDER_REGISTRY_CACHE_DIR` | Cache directory |
| `V2RAY_FINDER_DISABLE_REMOTE_REGISTRY=1` | Disable remote registry and use bundled/fallback sources |

Examples:

```bash
V2RAY_FINDER_REMOTE_REGISTRY_TTL=3600 python -m v2ray_finder.cli
```

```bash
V2RAY_FINDER_DISABLE_REMOTE_REGISTRY=1 python -m v2ray_finder.cli
```

## Android behavior

The signed Android release workflow packages both:

```text
v2ray_finder/
registry/
```

inside the Chaquopy Python payload.

At runtime, Android uses:

```text
remote GitHub registry → cache → bundled registry → fallback
```

This means:

```text
updating registry/sources.json on GitHub
→ app can pick it up after TTL or cache refresh
→ APK reinstall is not required for source-list changes
```

If GitHub is blocked or unavailable, the app still works using cached or bundled sources.

## Diagnostics

The Android bridge includes registry diagnostics in the scan payload:

```json
{
  "remote_source_registry": {
    "enabled": true,
    "url": "https://raw.githubusercontent.com/mehdimt1980/v2ray-finder/main/registry/sources.json",
    "cache_path": ".../remote_sources.json",
    "cache_exists": true,
    "cache_fresh": true,
    "cache_ttl_seconds": 86400
  }
}
```

The same diagnostic data is also available through:

```python
from v2ray_finder.remote_source_registry import get_remote_registry_diagnostics

print(get_remote_registry_diagnostics())
```

## Safety model

Remote registry does **not** mean every discovered source becomes active.

The source must first be present in the remote `registry/sources.json` with:

```text
status: trusted
```

or:

```text
status: official
```

Discovery and onboarding can still generate candidates, but candidate/experimental/quarantine/disabled records do not enter normal scans.
