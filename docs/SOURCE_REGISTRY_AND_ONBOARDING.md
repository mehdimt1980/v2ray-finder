# Source Registry and Onboarding

The source registry is the runtime contract between the external source hunter and the app.

`v2ray-finder` no longer performs global source discovery. Discovery, crawling, scoring and registry generation are handled by the separate `v2ray-source-hunter` repository. This repository consumes the resulting trusted registry and uses it for fetching, validation and source-performance reporting.

The main idea is:

```text
v2ray-source-hunter
→ discovers and validates public sources
→ writes trusted source records
→ syncs registry/sources.json into v2ray-finder

v2ray-finder
→ loads registry/sources.json
→ fetches configs from enabled active sources
→ deduplicates configs
→ health-checks and real-validates configs
→ reports source performance
```

## Files

```text
registry/sources.json
registry/candidate_sources.json
v2ray_finder/source_registry.py
v2ray_finder/source_onboarding.py
scripts/patch_sources_registry_loader.py
```

`registry/sources.json` is the only active registry used by default scans. `registry/candidate_sources.json` is optional and remains for manual review/onboarding workflows only.

## Source statuses

| Status | Meaning | Used in default scan? |
|---|---|---|
| `official` | Maintained/approved by project maintainers | yes |
| `trusted` | Performs well enough to be active | yes |
| `candidate` | New or uncertain source under evaluation | no |
| `experimental` | Potentially useful but unstable | no |
| `quarantine` | Suspicious, noisy or repeatedly low quality | no |
| `disabled` | Broken or intentionally disabled | no |

## Source record format

```json
{
  "id": "example-source",
  "label": "Example Source",
  "url": "https://example.com/sub.txt",
  "source_type": "static_subscription",
  "trust": "low",
  "status": "candidate",
  "enabled": true,
  "tags": ["candidate", "vless"],
  "protocols": ["vless", "trojan"],
  "region": "global",
  "notes": "Submitted by user",
  "added_at": "2026-06-25"
}
```

## Onboarding a single source manually

The global discovery engine was removed from this repository, but the single-source onboarding evaluator remains useful for manual checks.

Run the evaluator:

```bash
python -m v2ray_finder.source_onboarding \
  --url https://example.com/sub.txt \
  --label "Example Source" \
  --tcp-sample-size 50 \
  --json
```

To append it to `registry/candidate_sources.json`:

```bash
python -m v2ray_finder.source_onboarding \
  --url https://example.com/sub.txt \
  --label "Example Source" \
  --append-candidate
```

With Real Validation v2, if an xray binary is available:

```bash
python -m v2ray_finder.source_onboarding \
  --url https://example.com/sub.txt \
  --label "Example Source" \
  --real-validation-sample-size 10 \
  --xray-binary /path/to/xray \
  --append-candidate
```

## What onboarding measures

The evaluator reports:

```text
fetch_ok
http_status
raw_configs
unique_configs
duplicate_ratio
protocol counts
TCP sample size
TCP OK count
TCP success rate
Real Validation sample size
Real Validation OK count
Real Validation success rate
score
recommended_status
notes
```

## Recommendation logic

The score is based on:

```text
with Real Validation:
45% real-validation success
25% TCP success
20% unique-count signal
10% duplicate-ratio signal

without Real Validation:
45% TCP success
35% unique-count signal
20% duplicate-ratio signal
```

A source can be recommended as:

```text
trusted
candidate
experimental
quarantine
disabled
```

Even if the recommendation is `trusted`, the automatic append operation still adds it as `candidate` first. A maintainer or the external hunter should decide whether it belongs in `registry/sources.json`.

## Runtime integration

`v2ray_finder/source_registry.py` contains the JSON loader. To switch `sources.py` from the older hard-coded list to the JSON-backed registry loader, run:

```bash
python scripts/patch_sources_registry_loader.py
```

After that, `get_enabled_sources()` reads active sources from the JSON registry. Candidate sources are excluded by default and are only returned when `include_candidates=True` is passed explicitly.

## Why this matters

Free public config sources become stale quickly. A source can have thousands of configs but still produce zero working servers. The registry/onboarding layer keeps source quality measurable while leaving global discovery to `v2ray-source-hunter`.
