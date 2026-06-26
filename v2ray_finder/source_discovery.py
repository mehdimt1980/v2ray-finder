"""GitHub Source Discovery Engine.

This module searches GitHub for potential public V2Ray/Xray subscription
sources, converts file results into raw URLs, evaluates them through the existing
source onboarding pipeline, and writes a JSON report.

Discovery is intentionally conservative:

- It never promotes a source to trusted.
- It deduplicates against trusted, candidate and previously discovered sources.
- It keeps only sources that produce at least one config and are not disabled.
- Promotion remains a manual review step.

Example:

    python -m v2ray_finder.source_discovery --max-results-per-query 10 --min-score 30
"""

from __future__ import annotations

import argparse
import json
import os
import time
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence
from urllib.parse import quote

import requests

from .source_onboarding import OnboardingReport, evaluate_source
from .source_registry import (
    CANDIDATE_REGISTRY,
    REGISTRY_ROOT,
    TRUSTED_REGISTRY,
    SourceRecord,
    load_json_records,
    make_source_id,
    save_records,
)

DISCOVERY_QUERIES = REGISTRY_ROOT / "discovery_queries.json"
DISCOVERED_REGISTRY = REGISTRY_ROOT / "discovered_sources.json"
DEFAULT_REPORT = Path("source-discovery-report.json")

COMMON_SUBSCRIPTION_PATHS: Sequence[str] = (
    "sub.txt",
    "sub",
    "subscription.txt",
    "subscriptions.txt",
    "all.txt",
    "All_Configs_Sub.txt",
    "Eternity.txt",
    "v2ray.txt",
    "V2Ray.txt",
    "vless.txt",
    "vmess.txt",
    "trojan.txt",
    "ss.txt",
    "clash.yaml",
    "clash.yml",
    "config.yaml",
    "config.yml",
)


@dataclass
class DiscoveryQuery:
    id: str
    type: str
    query: str
    tags: List[str] = field(default_factory=list)

    @classmethod
    def from_mapping(cls, data: Dict[str, Any]) -> "DiscoveryQuery":
        return cls(
            id=str(data.get("id") or "query"),
            type=str(data.get("type") or "code").lower(),
            query=str(data.get("query") or ""),
            tags=[str(t) for t in data.get("tags", []) if str(t)],
        )


@dataclass
class DiscoveredSource:
    id: str
    label: str
    url: str
    source_type: str = "static_subscription"
    trust: str = "low"
    status: str = "candidate"
    enabled: bool = True
    tags: List[str] = field(default_factory=list)
    discovered_by: str = ""
    discovered_at: str = ""
    html_url: str = ""
    repository: str = ""
    path: str = ""
    discovery_score: float = 0.0
    onboarding_score: float = 0.0
    final_candidate_score: float = 0.0
    onboarding: Dict[str, Any] = field(default_factory=dict)
    notes: str = ""

    def to_record(self) -> SourceRecord:
        return SourceRecord(
            id=self.id,
            label=self.label,
            url=self.url,
            source_type=self.source_type,
            trust=self.trust,
            status=self.status,
            enabled=self.enabled,
            tags=list(self.tags),
            notes=self.notes,
            protocols=list((self.onboarding.get("protocols") or {}).keys()),
            added_at=self.discovered_at,
        )

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


def _github_headers(token: Optional[str] = None) -> Dict[str, str]:
    headers = {
        "Accept": "application/vnd.github+json",
        "User-Agent": "v2ray-finder-source-discovery/1.0",
        "X-GitHub-Api-Version": "2022-11-28",
    }
    token = token or os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN")
    if token:
        headers["Authorization"] = f"Bearer {token}"
    return headers


def _github_get(url: str, *, params: Optional[Dict[str, Any]] = None, token: Optional[str] = None) -> Dict[str, Any]:
    response = requests.get(url, params=params, headers=_github_headers(token), timeout=30)
    if response.status_code in {403, 429}:
        reset = response.headers.get("X-RateLimit-Reset")
        raise RuntimeError(f"GitHub rate limit or abuse limit hit for {url}; reset={reset}; body={response.text[:300]}")
    response.raise_for_status()
    return response.json()


def load_discovery_queries(path: Path = DISCOVERY_QUERIES) -> List[DiscoveryQuery]:
    raw = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(raw, list):
        raise ValueError(f"Discovery query file must be a list: {path}")
    return [DiscoveryQuery.from_mapping(item) for item in raw if isinstance(item, dict) and item.get("query")]


def existing_source_urls() -> set[str]:
    urls: set[str] = set()
    for path in (TRUSTED_REGISTRY, CANDIDATE_REGISTRY, DISCOVERED_REGISTRY):
        for rec in load_json_records(path):
            urls.add(rec.url)
    return urls


def code_result_to_raw_url(item: Dict[str, Any]) -> str:
    repo = item.get("repository") or {}
    full_name = repo.get("full_name") or ""
    branch = repo.get("default_branch") or "main"
    path = item.get("path") or ""
    if not full_name or not path:
        return ""
    return f"https://raw.githubusercontent.com/{full_name}/{branch}/{path}"


def code_result_to_candidate(item: Dict[str, Any], query: DiscoveryQuery) -> Optional[DiscoveredSource]:
    raw_url = code_result_to_raw_url(item)
    if not raw_url:
        return None
    repo = item.get("repository") or {}
    full_name = repo.get("full_name") or ""
    path = item.get("path") or ""
    label = f"{full_name} — {path}" if full_name and path else raw_url
    return DiscoveredSource(
        id=make_source_id(label),
        label=label,
        url=raw_url,
        tags=["discovered"] + list(query.tags),
        discovered_by=query.id,
        discovered_at=datetime.now(timezone.utc).date().isoformat(),
        html_url=item.get("html_url") or "",
        repository=full_name,
        path=path,
        discovery_score=_discovery_score_for_code(item),
        notes=f"Discovered by GitHub code search query: {query.id}",
    )


def _discovery_score_for_code(item: Dict[str, Any]) -> float:
    repo = item.get("repository") or {}
    score = 30.0
    if not repo.get("archived"):
        score += 10.0
    if not repo.get("fork"):
        score += 10.0
    stars = int(repo.get("stargazers_count") or 0)
    forks = int(repo.get("forks_count") or 0)
    score += min(stars, 100) * 0.2
    score += min(forks, 50) * 0.1
    path = str(item.get("path") or "").lower()
    if any(name in path for name in ["sub", "subscription", "all", "clash", "config", "eternity"]):
        score += 15.0
    if "readme" in path:
        score -= 25.0
    return round(max(0.0, min(100.0, score)), 1)


def _discovery_score_for_repo(repo: Dict[str, Any], path: str) -> float:
    score = 20.0
    if not repo.get("archived"):
        score += 10.0
    if not repo.get("fork"):
        score += 10.0
    stars = int(repo.get("stargazers_count") or 0)
    forks = int(repo.get("forks_count") or 0)
    score += min(stars, 200) * 0.15
    score += min(forks, 80) * 0.1
    low_path = path.lower()
    if any(name in low_path for name in ["sub", "subscription", "all", "clash", "config", "eternity"]):
        score += 15.0
    return round(max(0.0, min(100.0, score)), 1)


def search_code(query: DiscoveryQuery, *, max_results: int, token: Optional[str]) -> List[DiscoveredSource]:
    payload = _github_get(
        "https://api.github.com/search/code",
        params={"q": query.query, "per_page": min(max_results, 100)},
        token=token,
    )
    out: List[DiscoveredSource] = []
    for item in payload.get("items", []):
        candidate = code_result_to_candidate(item, query)
        if candidate:
            out.append(candidate)
    return out


def _raw_url_exists(url: str, *, token: Optional[str]) -> bool:
    try:
        response = requests.get(url, headers=_github_headers(token), timeout=12)
        return bool(response.ok and response.text.strip())
    except Exception:
        return False


def search_repos(query: DiscoveryQuery, *, max_results: int, token: Optional[str]) -> List[DiscoveredSource]:
    payload = _github_get(
        "https://api.github.com/search/repositories",
        params={"q": query.query, "sort": "updated", "order": "desc", "per_page": min(max_results, 100)},
        token=token,
    )
    out: List[DiscoveredSource] = []
    for repo in payload.get("items", []):
        full_name = repo.get("full_name") or ""
        branch = repo.get("default_branch") or "main"
        if not full_name:
            continue
        for path in COMMON_SUBSCRIPTION_PATHS:
            raw = f"https://raw.githubusercontent.com/{full_name}/{branch}/{path}"
            if not _raw_url_exists(raw, token=token):
                continue
            label = f"{full_name} — {path}"
            out.append(
                DiscoveredSource(
                    id=make_source_id(label),
                    label=label,
                    url=raw,
                    tags=["discovered"] + list(query.tags),
                    discovered_by=query.id,
                    discovered_at=datetime.now(timezone.utc).date().isoformat(),
                    html_url=f"https://github.com/{full_name}/blob/{branch}/{path}",
                    repository=full_name,
                    path=path,
                    discovery_score=_discovery_score_for_repo(repo, path),
                    notes=f"Discovered by GitHub repository search query: {query.id}",
                )
            )
    return out


def _final_score(onboarding_score: float, discovery_score: float) -> float:
    return round((0.70 * onboarding_score) + (0.30 * discovery_score), 1)


def _keep_report(report: OnboardingReport, *, min_score: float) -> bool:
    if not report.fetch_ok:
        return False
    if report.unique_configs <= 0:
        return False
    if report.recommended_status == "disabled":
        return False
    return report.score >= min_score


def evaluate_candidates(
    candidates: Iterable[DiscoveredSource],
    *,
    min_score: float,
    tcp_sample_size: int,
    max_candidates: int,
) -> List[DiscoveredSource]:
    out: List[DiscoveredSource] = []
    seen: set[str] = set()
    for candidate in candidates:
        if candidate.url in seen:
            continue
        seen.add(candidate.url)
        if len(out) >= max_candidates:
            break
        report = evaluate_source(
            candidate.url,
            label=candidate.label,
            tcp_sample_size=tcp_sample_size,
            real_validation_sample_size=0,
        )
        if not _keep_report(report, min_score=min_score):
            continue
        candidate.onboarding = report.to_dict()
        candidate.onboarding_score = float(report.score)
        candidate.final_candidate_score = _final_score(candidate.onboarding_score, candidate.discovery_score)
        candidate.status = "candidate"
        candidate.trust = "low"
        protocols = list(report.protocols.keys())
        candidate.tags = list(dict.fromkeys(candidate.tags + protocols + [report.recommended_status]))
        candidate.notes = (
            f"{candidate.notes}; onboarding score={report.score}; "
            f"unique={report.unique_configs}; tcp_ok={report.tcp_ok_count}/{report.tcp_sample_size}; "
            f"recommended={report.recommended_status}"
        )
        out.append(candidate)
    out.sort(key=lambda c: (-c.final_candidate_score, -c.onboarding_score, -c.discovery_score, c.label))
    return out


def discover_sources(
    *,
    max_results_per_query: int = 10,
    min_score: float = 20.0,
    tcp_sample_size: int = 30,
    max_candidates: int = 50,
    token: Optional[str] = None,
) -> Dict[str, Any]:
    queries = load_discovery_queries()
    existing = existing_source_urls()
    discovered: List[DiscoveredSource] = []
    errors: List[Dict[str, str]] = []

    for query in queries:
        try:
            if query.type == "repo":
                found = search_repos(query, max_results=max_results_per_query, token=token)
            else:
                found = search_code(query, max_results=max_results_per_query, token=token)
            for item in found:
                if item.url not in existing:
                    discovered.append(item)
        except Exception as exc:
            errors.append({"query_id": query.id, "query": query.query, "error": str(exc)})

    evaluated = evaluate_candidates(
        discovered,
        min_score=min_score,
        tcp_sample_size=tcp_sample_size,
        max_candidates=max_candidates,
    )
    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "query_count": len(queries),
        "raw_discovered_count": len(discovered),
        "kept_count": len(evaluated),
        "min_score": min_score,
        "tcp_sample_size": tcp_sample_size,
        "errors": errors,
        "sources": [c.to_dict() for c in evaluated],
    }


def write_outputs(report: Dict[str, Any], *, report_path: Path, registry_path: Path) -> None:
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    records = [DiscoveredSource(**item).to_record() for item in report.get("sources", [])]
    save_records(registry_path, records)


def write_step_summary(report: Dict[str, Any]) -> None:
    summary_path = os.environ.get("GITHUB_STEP_SUMMARY")
    if not summary_path:
        return
    lines = [
        "# Source Discovery Report",
        "",
        f"Generated at: `{report.get('generated_at')}`",
        f"Queries: **{report.get('query_count')}**",
        f"Raw discovered: **{report.get('raw_discovered_count')}**",
        f"Kept candidates: **{report.get('kept_count')}**",
        "",
        "| Score | Onboarding | Source | URL |",
        "|---:|---:|---|---|",
    ]
    for item in report.get("sources", [])[:20]:
        label = str(item.get("label") or "")[:80]
        url = str(item.get("url") or "")
        lines.append(
            f"| {item.get('final_candidate_score', 0)} | {item.get('onboarding_score', 0)} | {label} | {url} |"
        )
    if report.get("errors"):
        lines.extend(["", "## Errors"])
        for err in report["errors"]:
            lines.append(f"- `{err.get('query_id')}`: {err.get('error')}")
    Path(summary_path).write_text("\n".join(lines) + "\n", encoding="utf-8")


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Discover candidate V2Ray/Xray sources from GitHub.")
    parser.add_argument("--max-results-per-query", type=int, default=10)
    parser.add_argument("--min-score", type=float, default=20.0)
    parser.add_argument("--tcp-sample-size", type=int, default=30)
    parser.add_argument("--max-candidates", type=int, default=50)
    parser.add_argument("--report-path", default=str(DEFAULT_REPORT))
    parser.add_argument("--registry-path", default=str(DISCOVERED_REGISTRY))
    parser.add_argument("--token", default="", help="GitHub token; defaults to GITHUB_TOKEN/GH_TOKEN")
    parser.add_argument("--json", action="store_true", help="Print full JSON report to stdout")
    args = parser.parse_args(argv)

    report = discover_sources(
        max_results_per_query=args.max_results_per_query,
        min_score=args.min_score,
        tcp_sample_size=args.tcp_sample_size,
        max_candidates=args.max_candidates,
        token=args.token or None,
    )
    write_outputs(report, report_path=Path(args.report_path), registry_path=Path(args.registry_path))
    write_step_summary(report)
    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
    else:
        print(
            f"Discovery complete: raw={report['raw_discovered_count']} kept={report['kept_count']} "
            f"report={args.report_path}"
        )
        if report.get("errors"):
            print(f"Errors: {len(report['errors'])}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
