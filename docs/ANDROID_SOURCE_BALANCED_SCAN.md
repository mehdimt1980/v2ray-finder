# Android Source-Balanced Scan

Android used to pass the user limit directly into the core pipeline. When one large source produced thousands of configs, it could consume the entire candidate pool before other active sources had a chance to contribute.

Example problem:

```text
Remote registry active sources: 5
Epodonios source returns thousands of configs
Android limit: 145
Pipeline takes first 145 configs
Result source performance shows only 1 effective source
```

## New behavior

The Android release build now patches `MainActivity` to call:

```python
android_bridge_balanced.scan(...)
```

instead of:

```python
android_bridge.scan(...)
```

The balanced bridge keeps the same JSON output contract but changes the sampling strategy:

```text
active sources from Remote Source Registry
→ calculate per-source cap
→ fetch all active sources
→ cap each source before global health checking
→ health-check a mixed candidate pool
→ score all healthy configs
→ return top N results
```

## Android limits

For a user result limit `N` and `S` active sources:

```text
per_source_cap = ceil(N / S) + 20
minimum per_source_cap = 20
maximum per_source_cap = 250
candidate_pool_limit = max(N * 3, per_source_cap * S)
maximum candidate_pool_limit = 1200
```

This gives every active source a chance while keeping Android runtime bounded.

## Diagnostics

The scan JSON includes:

```json
{
  "stats": {
    "source_balancing": {
      "enabled": true,
      "active_sources": 5,
      "per_source_cap": 49,
      "candidate_pool_limit": 435,
      "result_limit": 145
    }
  }
}
```

The Android UI also appends a status message like:

```text
نمونه‌گیری متوازن از ۵ منبع فعال انجام شد؛ سقف هر منبع: ۴۹.
```

## Expected effect

Source Performance Engine should now show more than one analyzed source when multiple active sources actually produce healthy configs.

It is still possible to see only one effective source if:

```text
other sources fail to fetch
other sources produce zero parseable configs
other sources produce configs that fail TCP health check
all useful configs are duplicates attributed to a higher-trust source
```

But one large source should no longer dominate purely because it appears earlier in the registry.
