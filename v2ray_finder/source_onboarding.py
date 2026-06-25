"""Source onboarding evaluator.

Use this module to test a new subscription source before it becomes trusted.
A candidate is fetched, parsed, deduplicated, lightly TCP-checked and optionally
validated with Real Validation Engine v2.

Example:

    python -m v2ray_finder.source_onboarding --url https://example/sub.txt --append-candidate
"""

from __future__ import annotations

import argparse
import base64
import json
import re
import socket
import time
from dataclasses import asdict, dataclass, field
from typing import Dict, List, Optional, Tuple
from urllib.parse import urlparse

import requests

from .clash_parser import extract_clash_proxy_uris
from .source_registry import SourceRecord, append_candidate, make_source_id

_PROTO_RE = re.compile(
    r"(?:vmess|vless|trojan|ss|ssr)://[A-Za-z0-9+/=_\-@:.?&#%]+",
    re.IGNORECASE,
)


@dataclass
class OnboardingReport:
    url: str
    label: str
    fetch_ok: bool = False
    fetch_error: str = ""
    http_status: Optional[int] = None
    raw_configs: int = 0
    unique_configs: int = 0
    duplicate_ratio: float = 0.0
    protocols: Dict[str, int] = field(default_factory=dict)
    tcp_sample_size: int = 0
    tcp_ok_count: int = 0
    tcp_success_rate: float = 0.0
    real_validation_sample_size: int = 0
    real_validation_ok_count: int = 0
    real_validation_success_rate: float = 0.0
    score: float = 0.0
    recommended_status: str = "candidate"
    notes: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict:
        return asdict(self)


def _try_base64_decode(text: str) -> str:
    compact = "".join((text or "").split())
    if len(compact) < 16:
        return ""
    try:
        padded = compact + "=" * (-len(compact) % 4)
        decoded = base64.b64decode(padded, validate=False).decode("utf-8", errors="ignore")
        if "://" in decoded:
            return decoded
    except Exception:
        pass
    return ""


def extract_configs(text: str) -> List[str]:
    """Extract config URIs from raw text, base64 subscriptions and Clash YAML."""
    text = text or ""
    found: List[str] = []
    found.extend(_PROTO_RE.findall(text))
    decoded = _try_base64_decode(text)
    if decoded:
        found.extend(_PROTO_RE.findall(decoded))
    if "proxies:" in text and "type:" in text:
        found.extend(extract_clash_proxy_uris(text))
    return list(dict.fromkeys(found))


def _vmess_endpoint(uri: str) -> Tuple[str, int]:
    raw = uri.split("://", 1)[1]
    try:
        decoded = base64.urlsafe_b64decode(raw + "=" * (-len(raw) % 4)).decode("utf-8", errors="ignore")
        data = json.loads(decoded)
        return str(data.get("add") or ""), int(data.get("port") or 443)
    except Exception:
        return "", 0


def _ss_endpoint(uri: str) -> Tuple[str, int]:
    parsed = urlparse(uri)
    if parsed.hostname:
        return parsed.hostname, parsed.port or 443
    return "", 0


def _endpoint_from_uri(uri: str) -> Tuple[str, int]:
    if uri.startswith("vmess://"):
        return _vmess_endpoint(uri)
    if uri.startswith("ss://"):
        return _ss_endpoint(uri)
    parsed = urlparse(uri)
    if not parsed.hostname:
        return "", 0
    return parsed.hostname, parsed.port or 443


def _tcp_probe(host: str, port: int, timeout: float) -> bool:
    if not host or not port:
        return False
    try:
        with socket.create_connection((host, int(port)), timeout=timeout):
            return True
    except Exception:
        return False


def _protocol_counts(configs: List[str]) -> Dict[str, int]:
    counts: Dict[str, int] = {}
    for cfg in configs:
        proto = cfg.split("://", 1)[0].lower() if "://" in cfg else "unknown"
        counts[proto] = counts.get(proto, 0) + 1
    return dict(sorted(counts.items(), key=lambda kv: (-kv[1], kv[0])))


def _score(report: OnboardingReport) -> None:
    unique_signal = min(report.unique_configs / 300.0, 1.0) if report.unique_configs else 0.0
    duplicate_signal = max(0.0, 1.0 - report.duplicate_ratio)
    tcp_signal = report.tcp_success_rate
    rv_signal = report.real_validation_success_rate

    if report.real_validation_sample_size > 0:
        score = 45 * rv_signal + 25 * tcp_signal + 20 * unique_signal + 10 * duplicate_signal
    else:
        score = 45 * tcp_signal + 35 * unique_signal + 20 * duplicate_signal

    if not report.fetch_ok:
        score = 0.0
    if report.unique_configs == 0:
        score = min(score, 10.0)
    report.score = round(max(0.0, min(100.0, score)), 1)

    if not report.fetch_ok or report.unique_configs == 0:
        report.recommended_status = "disabled"
    elif report.real_validation_sample_size > 0 and report.real_validation_success_rate >= 0.08:
        report.recommended_status = "trusted"
    elif report.score >= 60:
        report.recommended_status = "candidate"
    elif report.score >= 30:
        report.recommended_status = "experimental"
    else:
        report.recommended_status = "quarantine"


def evaluate_source(
    url: str,
    *,
    label: str = "",
    timeout: float = 10.0,
    tcp_sample_size: int = 50,
    real_validation_sample_size: int = 0,
    xray_binary: str = "",
) -> OnboardingReport:
    label = label or url
    report = OnboardingReport(url=url, label=label)
    try:
        response = requests.get(url, timeout=timeout, headers={"User-Agent": "v2ray-finder-onboarding/1.0"})
        report.http_status = int(response.status_code)
        response.raise_for_status()
        report.fetch_ok = True
        configs = extract_configs(response.text)
        if configs and "proxies:" in response.text:
            report.notes.append("Parsed Clash YAML proxies in addition to raw URI links.")
    except Exception as exc:
        report.fetch_error = str(exc)
        report.notes.append("Fetch failed; keep this source disabled or quarantined.")
        _score(report)
        return report

    unique = list(dict.fromkeys(configs))
    report.raw_configs = len(configs)
    report.unique_configs = len(unique)
    report.duplicate_ratio = round(1.0 - (len(unique) / len(configs)), 4) if configs else 0.0
    report.protocols = _protocol_counts(unique)

    sample = unique[: max(0, tcp_sample_size)]
    report.tcp_sample_size = len(sample)
    tcp_ok = 0
    for cfg in sample:
        host, port = _endpoint_from_uri(cfg)
        if _tcp_probe(host, port, timeout=min(timeout, 5.0)):
            tcp_ok += 1
    report.tcp_ok_count = tcp_ok
    report.tcp_success_rate = round(tcp_ok / len(sample), 4) if sample else 0.0

    if real_validation_sample_size > 0 and xray_binary:
        try:
            from .real_validation import check_real_validation_batch

            rv_sample = unique[:real_validation_sample_size]
            rv_results = check_real_validation_batch(
                rv_sample,
                max_workers=2,
                timeout=max(timeout, 6.0),
                binary_path=xray_binary,
                auto_download=False,
                stability_attempts=1,
            )
            ok = sum(1 for r in rv_results if getattr(r, "validation_ok", False))
            report.real_validation_sample_size = len(rv_results)
            report.real_validation_ok_count = ok
            report.real_validation_success_rate = round(ok / len(rv_results), 4) if rv_results else 0.0
        except Exception as exc:
            report.notes.append(f"Real validation failed during onboarding: {exc}")

    if report.duplicate_ratio > 0.8:
        report.notes.append("High duplicate ratio; this source may mostly mirror other aggregators.")
    if report.tcp_success_rate == 0 and report.tcp_sample_size:
        report.notes.append("TCP sample produced zero reachable endpoints.")
    if report.real_validation_sample_size and report.real_validation_ok_count == 0:
        report.notes.append("Real validation produced zero working configs in the sample.")

    _score(report)
    return report


def report_to_candidate_record(report: OnboardingReport) -> SourceRecord:
    protocols = list(report.protocols.keys())
    tags = ["candidate", "onboarded"] + protocols[:4]
    return SourceRecord(
        id=make_source_id(report.label or report.url),
        label=report.label,
        url=report.url,
        source_type="static_subscription",
        trust="low" if report.recommended_status != "trusted" else "medium",
        status="candidate" if report.recommended_status == "trusted" else report.recommended_status,
        enabled=True,
        tags=tags,
        notes=(
            f"Onboarding score={report.score}; unique={report.unique_configs}; "
            f"tcp_ok={report.tcp_ok_count}/{report.tcp_sample_size}; "
            f"real_ok={report.real_validation_ok_count}/{report.real_validation_sample_size}"
        ),
        protocols=protocols,
        added_at=time.strftime("%Y-%m-%d"),
    )


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Evaluate a candidate V2Ray/Xray subscription source.")
    parser.add_argument("--url", required=True, help="Subscription/raw URL to evaluate")
    parser.add_argument("--label", default="", help="Human-readable source label")
    parser.add_argument("--timeout", type=float, default=10.0)
    parser.add_argument("--tcp-sample-size", type=int, default=50)
    parser.add_argument("--real-validation-sample-size", type=int, default=0)
    parser.add_argument("--xray-binary", default="", help="Optional xray binary path for Real Validation v2")
    parser.add_argument("--append-candidate", action="store_true", help="Append evaluated source to registry/candidate_sources.json")
    parser.add_argument("--json", action="store_true", help="Print JSON only")
    args = parser.parse_args(argv)

    report = evaluate_source(
        args.url,
        label=args.label,
        timeout=args.timeout,
        tcp_sample_size=args.tcp_sample_size,
        real_validation_sample_size=args.real_validation_sample_size,
        xray_binary=args.xray_binary,
    )

    if args.append_candidate:
        changed = append_candidate(report_to_candidate_record(report))
        report.notes.append("Appended to candidate registry." if changed else "URL already exists in candidate registry.")

    if args.json:
        print(json.dumps(report.to_dict(), ensure_ascii=False, indent=2))
    else:
        print(json.dumps(report.to_dict(), ensure_ascii=False, indent=2))
        print("\nRecommendation:", report.recommended_status, "score=", report.score)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
