# GitHub Source Discovery Engine

The Source Discovery Engine searches GitHub for potential V2Ray/Xray config sources and evaluates them before they can enter the registry.

It is intentionally conservative:

```text
Discovery → onboarding → discovered candidate → manual review → candidate/trusted registry
```

Discovery never promotes a source directly to `trusted`.

## Files

```text
registry/discovery_queries.json
registry/discovered_sources.json
v2ray_finder/source_discovery.py
.github/workflows/source-discovery.yml
```

## Discovery queries

Queries live in `registry/discovery_queries.json`:

```json
{
  "id": "raw-vless-text",
  "type": "code",
  "query": "\"vless://\" path:*.txt NOT path:README",
  "tags": ["vless", "raw-uri"]
}
```

Supported query types:

| Type | Meaning |
|---|---|
| `code` | Uses GitHub Code Search to find files containing raw URIs or Clash YAML |
| `repo` | Uses GitHub Repository Search, then probes common subscription paths |

## What the engine does

1. Load discovery queries.
2. Search GitHub Code Search or Repository Search.
3. Convert GitHub file results into `raw.githubusercontent.com` URLs.
4. Deduplicate against:
   - `registry/sources.json`
   - `registry/candidate_sources.json`
   - `registry/discovered_sources.json`
5. Run `source_onboarding` on each raw URL.
6. Keep only candidates that:
   - fetch successfully
   - produce at least one unique config
   - are not recommended as `disabled`
   - pass the configured minimum onboarding score
7. Write:
   - `source-discovery-report.json`
   - `registry/discovered_sources.json`
   - GitHub Actions step summary

## Running locally

```bash
python -m v2ray_finder.source_discovery \
  --max-results-per-query 10 \
  --min-score 20 \
  --tcp-sample-size 30 \
  --max-candidates 50 \
  --json
```

If you have a GitHub token:

```bash
GITHUB_TOKEN=ghp_xxx python -m v2ray_finder.source_discovery --json
```

## Running in GitHub Actions

Go to:

```text
Actions → Source Discovery → Run workflow
```

Inputs:

```text
max_results_per_query   default 10
min_score               default 20
tcp_sample_size         default 30
max_candidates          default 50
```

The workflow also runs weekly on Monday morning.

## Output files

The workflow artifact is called:

```text
source-discovery-report
```

It contains:

```text
source-discovery-report.json
source-discovery-stdout.json
registry/discovered_sources.json
```

## Candidate record example

```json
{
  "id": "owner-repo-sub-txt",
  "label": "owner/repo — sub.txt",
  "url": "https://raw.githubusercontent.com/owner/repo/main/sub.txt",
  "source_type": "static_subscription",
  "trust": "low",
  "status": "candidate",
  "tags": ["discovered", "vless", "candidate"],
  "discovered_by": "raw-vless-text",
  "discovered_at": "2026-06-26",
  "discovery_score": 55.0,
  "onboarding_score": 63.5,
  "final_candidate_score": 61.0,
  "onboarding": {
    "fetch_ok": true,
    "unique_configs": 140,
    "tcp_success_rate": 0.22,
    "score": 63.5,
    "recommended_status": "candidate"
  }
}
```

## Scoring

The final candidate score is:

```text
70% onboarding_score
30% discovery_score
```

Onboarding is more important than GitHub metadata because the source must actually produce usable configs.

## Promotion policy

A discovered source should not be moved to `registry/sources.json` immediately.

Recommended promotion path:

```text
discovered_sources.json
→ candidate_sources.json
→ repeated onboarding / Real Validation v2 check
→ registry/sources.json with status trusted
```

A source should be promoted only when it repeatedly shows:

```text
fetch_ok = true
unique_configs > 30
tcp_success_rate > 0.10
score > 60
preferably real_validation_ok_count > 0
```

## Why this is separate from the Android app

Discovery uses GitHub Search APIs and can hit rate limits. It is better to run it in GitHub Actions instead of on the user's phone. The Android app should consume trusted registry data, not perform global GitHub discovery at runtime.
