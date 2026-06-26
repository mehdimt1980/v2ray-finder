"""Resilient Source Discovery Engine.

This module avoids relying primarily on GitHub Code Search, which frequently
hits secondary rate limits.  It discovers candidates in this order:

1. Seed repositories from ``registry/discovery_seed_repos.json``.
2. GitHub repository search from ``registry/discovery_queries.json``.
3. Optional GitHub code search, disabled by default in CI.

The output format is compatible with ``source_discovery.py`` so the existing
report, artifact and auto-promotion flow continue to work.
"""

from __future__ import annotations

import argparse
import json
import os
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

from .source_discovery import (
    DEFAULT_REPORT,
    DISCOVERED_REGISTRY,
    DISCOVERY_QUERIES,
    COMMON_SUBSCRIPTION_PATHS,
    DiscoveredSource,
    PromotionPolicy,
    _discovery_score_for_repo,
    _raw_url_exists,
    auto_promote_sources,
    evaluate_candidates,
    existing_source_urls,
    load_discovery_queries,
    search_code,
    search_repos,
    write_outputs,
    write_step_summary,
)
from .source_registry import REGISTRY_ROOT, make_source_id

DISCOVERY_SEED_REPOS = REGISTRY_ROOT / "discovery_seed_repos.json"


@dataclass
class SeedRepo:
    id: str
    repository: str
    branch: str = "main"
    paths: List[str] = field(default_factory=list)
    tags: List[str] = field(default_factory=list)

    @classmethod
    def from_mapping(cls, data: Dict[str, Any]) -> "SeedRepo":
        return cls(
            id=str(data.get("id") or data.get("repository") or "seed"),
            repository=str(data.get("repository") or ""),
            branch=str(data.get("branch") or "main"),
            paths=[str(p) for p in data.get("paths", []) if str(p)],
            tags=[str(t) for t in data.get("tags", []) if str(t)],
        )


def _github_token(token: Optional[str] = None) -> Optional[str]:
    return token or os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN") or None


def load_seed_repos(path: Path = DISCOVERY_SEED_REPOS) -> List[SeedRepo]:
    if not path.exists():
        return []
    raw = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(raw, list):
        raise ValueError(f"Seed repo file must be a list: {path}")
    return [SeedRepo.from_mapping(item) for item in raw if isinstance(item, dict) and item.get("repository")]


def seed_repo_candidates(
    *,
    token: Optional[str],
    existing_urls: set[str],
    max_paths_per_repo: int = 20,
) -> List[DiscoveredSource]:
    out: List[DiscoveredSource] = []
    seen: set[str] = set()
    for seed in load_seed_repos():
        if not seed.repository:
            continue
        paths = list(seed.paths or COMMON_SUBSCRIPTION_PATHS)[:max_paths_per_repo]
        for path in paths:
            raw = f"https://raw.githubusercontent.com/{seed.repository}/{seed.branch}/{path}"
            if raw in existing_urls or raw in seen:
                continue
            if not _raw_url_exists(raw, token=token):
                continue
            seen.add(raw)
            label = f"{seed.repository} — {path}"
            out.append(
                DiscoveredSource(
                    id=make_source_id(label),
                    label=label,
                    url=raw,
                    tags=["discovered", "seed"] + list(seed.tags),
                    discovered_by=f"seed:{seed.id}",
                    discovered_at=datetime.now(timezone.utc).date().isoformat(),
                    html_url=f"https://github.com/{seed.repository}/blob/{seed.branch}/{path}",
                    repository=seed.repository,
                    path=path,
                    discovery_score=65.0,
                    notes=f"Discovered by seed repository probing: {seed.id}",
                )
            )
    return out


def _is_rate_limit_error(exc: Exception) -> bool:
    text = str(exc).lower()
    return "rate limit" in text or "abuse limit" in text or "secondary rate" in text


def discover_sources_resilient(
    *,
    max_results_per_query: int = 10,
    min_score: float = 20.0,
    tcp_sample_size: int = 30,
    max_candidates: int = 50,
    token: Optional[str] = None,
    include_code_search: bool = False,
    seed_only: bool = False,
    repo_search: bool = True,
    stop_code_search_on_rate_limit: bool = True,
) -> Dict[str, Any]:
    token = _github_token(token)
    queries = load_discovery_queries(DISCOVERY_QUERIES)
    existing = existing_source_urls()
    discovered: List[DiscoveredSource] = []
    errors: List[Dict[str, str]] = []
    counters: Dict[str, int] = {
        "seed_discovered": 0,
        "repo_discovered": 0,
        "code_discovered": 0,
        "code_search_skipped": 0,
    }

    seed_found = seed_repo_candidates(token=token, existing_urls=existing)
    discovered.extend(seed_found)
    counters["seed_discovered"] = len(seed_found)
    seen_urls = {item.url for item in discovered}

    if not seed_only and repo_search:
        for query in [q for q in queries if q.type == "repo"]:
            try:
                found = search_repos(query, max_results=max_results_per_query, token=token)
                kept = 0
                for item in found:
                    if item.url not in existing and item.url not in seen_urls:
                        discovered.append(item)
                        seen_urls.add(item.url)
                        kept += 1
                counters["repo_discovered"] += kept
            except Exception as exc:
                errors.append({"query_id": query.id, "query": query.query, "phase": "repo", "error": str(exc)})

    if not seed_only and include_code_search:
        for query in [q for q in queries if q.type != "repo"]:
            try:
                found = search_code(query, max_results=max_results_per_query, token=token)
                kept = 0
                for item in found:
                    if item.url not in existing and item.url not in seen_urls:
                        discovered.append(item)
                        seen_urls.add(item.url)
                        kept += 1
                counters["code_discovered"] += kept
            except Exception as exc:
                errors.append({"query_id": query.id, "query": query.query, "phase": "code", "error": str(exc)})
                if stop_code_search_on_rate_limit and _is_rate_limit_error(exc):
                    remaining = len([q for q in queries if q.type != "repo"])
                    counters["code_search_skipped"] = max(0, remaining - 1)
                    break

    evaluated = evaluate_candidates(
        discovered,
        min_score=min_score,
        tcp_sample_size=tcp_sample_size,
        max_candidates=max_candidates,
    )
    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "engine": "source_discovery_resilient",
        "query_count": len(queries),
        "seed_repo_count": len(load_seed_repos()),
        "raw_discovered_count": len(discovered),
        "kept_count": len(evaluated),
        "min_score": min_score,
        "tcp_sample_size": tcp_sample_size,
        "include_code_search": include_code_search,
        "seed_only": seed_only,
        "repo_search": repo_search,
        "counters": counters,
        "errors": errors,
        "sources": [c.to_dict() for c in evaluated],
        "promotion": {
            "enabled": False,
            "promoted_count": 0,
            "promoted_sources": [],
            "skipped_sources": [],
        },
    }


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Resiliently discover candidate V2Ray/Xray sources from GitHub.")
    parser.add_argument("--max-results-per-query", type=int, default=10)
    parser.add_argument("--min-score", type=float, default=20.0)
    parser.add_argument("--tcp-sample-size", type=int, default=30)
    parser.add_argument("--max-candidates", type=int, default=50)
    parser.add_argument("--report-path", default=str(DEFAULT_REPORT))
    parser.add_argument("--registry-path", default=str(DISCOVERED_REGISTRY))
    parser.add_argument("--token", default="", help="GitHub token; defaults to GITHUB_TOKEN/GH_TOKEN")
    parser.add_argument("--json", action="store_true", help="Print full JSON report to stdout")

    parser.add_argument("--include-code-search", action="store_true", help="Enable GitHub Code Search. Disabled by default to avoid rate limits.")
    parser.add_argument("--seed-only", action="store_true", help="Use only seed repository probing; no GitHub search API.")
    parser.add_argument("--disable-repo-search", action="store_true", help="Disable GitHub Repository Search.")

    parser.add_argument("--auto-promote", action="store_true", help="Append high-quality candidates to registry/sources.json")
    parser.add_argument("--promote-min-score", type=float, default=60.0)
    parser.add_argument("--promote-min-final-score", type=float, default=55.0)
    parser.add_argument("--promote-min-unique", type=int, default=30)
    parser.add_argument("--promote-min-tcp-rate", type=float, default=0.25)
    parser.add_argument("--promote-max-duplicate-ratio", type=float, default=0.50)
    parser.add_argument("--promote-max-count", type=int, default=5)
    args = parser.parse_args(argv)

    report = discover_sources_resilient(
        max_results_per_query=args.max_results_per_query,
        min_score=args.min_score,
        tcp_sample_size=args.tcp_sample_size,
        max_candidates=args.max_candidates,
        token=args.token or None,
        include_code_search=args.include_code_search,
        seed_only=args.seed_only,
        repo_search=not args.disable_repo_search,
    )

    if args.auto_promote:
        auto_promote_sources(
            report,
            policy=PromotionPolicy(
                min_onboarding_score=args.promote_min_score,
                min_final_score=args.promote_min_final_score,
                min_unique_configs=args.promote_min_unique,
                min_tcp_success_rate=args.promote_min_tcp_rate,
                max_duplicate_ratio=args.promote_max_duplicate_ratio,
                max_promotions=args.promote_max_count,
            ),
        )

    write_outputs(report, report_path=Path(args.report_path), registry_path=Path(args.registry_path))
    write_step_summary(report)
    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
    else:
        print(
            f"Discovery complete: raw={report['raw_discovered_count']} kept={report['kept_count']} "
            f"promoted={report.get('promotion', {}).get('promoted_count', 0)} report={args.report_path}"
        )
        if report.get("errors"):
            print(f"Errors: {len(report['errors'])}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
