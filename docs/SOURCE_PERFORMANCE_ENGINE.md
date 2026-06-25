# Source Performance Engine

The Source Performance Engine ranks subscription sources by how useful they are in a real scan run.

## What it measures in the MVP

For every source with activity or an error, the engine reports:

- `url`
- `label`
- `trust`
- `tags`
- `source_type`
- `fetch_ok`
- `fetch_error_type`
- `fetch_error_message`
- `tcp_candidates`
- `tcp_ok_count`
- `scored_count`
- `xray_checked_count`
- `xray_ok_count`
- `avg_latency_ms`
- `best_latency_ms`
- `tcp_success_rate`
- `xray_success_rate`
- `source_score`
- `error_samples`

## Scoring

When xray / Google-204 results are available, source score is weighted toward real proxy success:

```text
55% xray success rate
20% TCP success rate
15% latency score
10% configured trust
```

When xray results are not available, the score falls back to softer signals:

```text
60% TCP success rate
20% latency score
20% configured trust
```

Penalties are applied for failed fetches, no activity, and xray-checked sources with zero working configs.

## Android integration

`android_bridge.scan()` now returns source performance in two places:

```json
{
  "stats": {
    "source_performance": []
  },
  "source_performance": []
}
```

The Android bridge also fixes source attribution for result cards by mapping each scored config back to `result.health_dicts[].source_url`.

## Next steps

1. Render top sources in the Android UI.
2. Persist source history in app storage.
3. Use rolling scores to prioritize good sources and skip broken sources.
4. Add dynamic GitHub discovery after the source ranking is stable.
