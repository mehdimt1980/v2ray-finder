# GitHub Source Discovery Engine

The Source Discovery Engine searches GitHub for potential V2Ray/Xray config sources and evaluates them before they can enter the registry.

It is conservative by default:

```text
Discovery → onboarding → discovered candidate → optional auto-promotion → trusted registry
```

Discovery never promotes a source unless `--auto-promote` is explicitly enabled and strict thresholds are met.

## Files

```text
registry/discovery_queries.json
registry/discovered_sources.json
registry/sources.json
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
8. If auto-promotion is enabled, append high-quality candidates to `registry/sources.json` with `status: trusted`.

## Running locally

```bash
python -m v2ray_finder.source_discovery \
  --max-results-per-query 10 \
  --min-score 20 \
  --tcp-sample-size 30 \
  --max-candidates 50 \
  --json
```

With automatic promotion:

```bash
python -m v2ray_finder.source_discovery \
  --max-results-per-query 10 \
  --min-score 20 \
  --tcp-sample-size 30 \
  --max-candidates 50 \
  --auto-promote \
  --promote-min-score 60 \
  --promote-min-final-score 55 \
  --promote-min-unique 30 \
  --promote-min-tcp-rate 0.25 \
  --promote-max-duplicate-ratio 0.50 \
  --promote-max-count 5 \
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
max_results_per_query        default 10
min_score                    default 20
tcp_sample_size              default 30
max_candidates               default 50
auto_promote_to_sources      default true
promote_min_score            default 60
promote_min_final_score      default 55
promote_min_unique           default 30
promote_min_tcp_rate         default 0.25
promote_max_duplicate_ratio  default 0.50
promote_max_count            default 5
```

When `auto_promote_to_sources=true`, the workflow commits changes to:

```text
registry/sources.json
registry/discovered_sources.json
```

and pushes them back to `main` using `github-actions[bot]`.

The scheduled weekly run does **not** auto-promote by default, because scheduled events do not provide the manual input. Automatic promotion is intended for manual runs where the maintainer can control the thresholds.

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
registry/sources.json
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

## Auto-promotion policy

A source is automatically appended to `registry/sources.json` only when all default conditions are met:

```text
fetch_ok = true
unique_configs >= 30
tcp_success_rate >= 0.25
onboarding score >= 60
final_candidate_score >= 55
duplicate_ratio <= 0.50
recommended_status is candidate or trusted
not already present in registry/sources.json
```

Promoted records are written with:

```text
status: trusted
trust: medium if tcp_success_rate >= 0.50, otherwise low
tags include auto-promoted and trusted
```

The default policy promotes at most 5 sources per run.

## Why this is separate from the Android app

Discovery uses GitHub Search APIs and can hit rate limits. It is better to run it in GitHub Actions instead of on the user's phone. The Android app should consume trusted registry data, not perform global GitHub discovery at runtime.
