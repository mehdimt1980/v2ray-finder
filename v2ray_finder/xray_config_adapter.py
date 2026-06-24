"""Build xray JSON configuration from proxy URI strings.

Supported URI schemes: vmess, vless, trojan, ss (Shadowsocks).

The generated config uses a SOCKS5 inbound on 127.0.0.1:<socks_port>
and routes normal traffic through the proxy outbound.
"""

from __future__ import annotations

import base64
import contextlib
import json
import os
import tempfile
from typing import Any, Dict
from urllib.parse import parse_qs, unquote, urlparse


class UnsupportedProtocolError(ValueError):
    """Raised when a URI scheme is not supported by the adapter."""

    def __init__(self, scheme: str) -> None:
        super().__init__(f"Unsupported protocol: {scheme!r}")
        self.scheme = scheme


class ConfigAdapter:
    """Convert proxy URI strings to xray JSON config dicts."""

    SUPPORTED = frozenset({"vmess", "vless", "trojan", "ss"})

    def __init__(self, log_level: str = "warning") -> None:
        self.log_level = log_level

    def build_config(self, uri: str, socks_port: int = 10808) -> Dict[str, Any]:
        """Convert *uri* to an xray config dict."""
        scheme = uri.split("://", 1)[0].lower() if "://" in uri else ""
        if scheme not in self.SUPPORTED:
            raise UnsupportedProtocolError(scheme)
        cfg = config_to_xray(uri, local_port=socks_port)
        if "log" not in cfg:
            cfg["log"] = {}
        cfg["log"]["loglevel"] = self.log_level
        return cfg

    @contextlib.contextmanager
    def build_config_file(self, uri: str, socks_port: int = 10808):
        """Context manager: yield path to a temporary xray config file."""
        cfg = self.build_config(uri, socks_port=socks_port)
        fd, path = tempfile.mkstemp(suffix=".json", prefix="xray_cfg_")
        try:
            with os.fdopen(fd, "w") as fh:
                json.dump(cfg, fh)
            yield path
        finally:
            try:
                os.unlink(path)
            except OSError:
                pass


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _socks_inbound(local_port: int) -> Dict:
    return {
        "listen": "127.0.0.1",
        "port": local_port,
        "protocol": "socks",
        "settings": {"auth": "noauth", "udp": True},
        "sniffing": {"enabled": True, "destOverride": ["http", "tls"]},
    }


def _base_config(outbound: Dict, local_port: int) -> Dict:
    """Return a complete minimal xray config.

    Important: routing rules below reference both ``proxy`` and ``direct`` tags,
    so both outbounds must exist.  Earlier builds referenced ``direct`` without
    defining it, which can make xray fail before opening the local SOCKS port.
    """
    outbound = dict(outbound)
    outbound.setdefault("tag", "proxy")
    return {
        "inbounds": [_socks_inbound(local_port)],
        "outbounds": [
            outbound,
            {"tag": "direct", "protocol": "freedom"},
            {"tag": "block", "protocol": "blackhole"},
        ],
        "routing": {
            "domainStrategy": "IPIfNonMatch",
            "rules": [
                {"type": "field", "outboundTag": "direct", "ip": ["geoip:private"]},
                {"type": "field", "outboundTag": "proxy", "network": "tcp,udp"},
            ],
        },
    }


def _stream_settings_vmess(info: dict) -> Dict:
    network = info.get("net", "tcp")
    tls = info.get("tls", "")
    settings: Dict[str, Any] = {"network": network}
    if tls in ("tls", "xtls"):
        settings["security"] = tls
        settings["tlsSettings"] = {
            "serverName": info.get("sni") or info.get("host", ""),
            "allowInsecure": False,
        }
    if network == "ws":
        settings["wsSettings"] = {
            "path": info.get("path", "/"),
            "headers": {"Host": info.get("host", "")},
        }
    elif network == "grpc":
        settings["grpcSettings"] = {"serviceName": info.get("path", "")}
    elif network in ("http", "h2"):
        settings["httpSettings"] = {
            "host": [info.get("host", "")],
            "path": info.get("path", "/"),
        }
    return settings


def _stream_settings_qs(qs: dict, parsed: Any) -> Dict:
    network = qs.get("type", ["tcp"])[0]
    security = qs.get("security", ["none"])[0]
    settings: Dict[str, Any] = {"network": network}

    if security == "reality":
        settings["security"] = "reality"
        sni = qs.get("sni", [""])[0] or (parsed.hostname or "")
        reality = {
            "serverName": sni,
            "fingerprint": qs.get("fp", ["chrome"])[0] or "chrome",
            "publicKey": qs.get("pbk", [""])[0],
            "shortId": qs.get("sid", [""])[0],
            "spiderX": qs.get("spx", ["/"])[0] or "/",
        }
        settings["realitySettings"] = {k: v for k, v in reality.items() if v != ""}
    elif security in ("tls", "xtls"):
        settings["security"] = security
        sni = qs.get("sni", [""])[0] or (parsed.hostname or "")
        settings["tlsSettings"] = {
            "serverName": sni,
            "allowInsecure": qs.get("allowInsecure", ["0"])[0] == "1",
        }

    if network == "ws":
        settings["wsSettings"] = {
            "path": qs.get("path", ["/"])[0],
            "headers": {"Host": qs.get("host", [""])[0]},
        }
    elif network == "grpc":
        settings["grpcSettings"] = {"serviceName": qs.get("serviceName", [""])[0]}
    elif network in ("http", "h2"):
        settings["httpSettings"] = {
            "host": [qs.get("host", [""])[0]],
            "path": qs.get("path", ["/"])[0],
        }
    return settings


def _build_vmess(uri: str, local_port: int) -> Dict:
    encoded = uri[len("vmess://") :]
    padded = encoded + "=" * (-len(encoded) % 4)
    info = json.loads(base64.urlsafe_b64decode(padded))
    outbound = {
        "protocol": "vmess",
        "settings": {
            "vnext": [
                {
                    "address": info.get("add") or info.get("addr", ""),
                    "port": int(info.get("port", 443)),
                    "users": [
                        {
                            "id": info.get("id", ""),
                            "alterId": int(info.get("aid", 0)),
                            "security": info.get("scy", "auto"),
                        }
                    ],
                }
            ]
        },
        "streamSettings": _stream_settings_vmess(info),
    }
    return _base_config(outbound, local_port)


def _build_vless(uri: str, local_port: int) -> Dict:
    parsed = urlparse(uri)
    qs = parse_qs(parsed.query)
    outbound = {
        "protocol": "vless",
        "settings": {
            "vnext": [
                {
                    "address": parsed.hostname or "",
                    "port": parsed.port or 443,
                    "users": [
                        {
                            "id": parsed.username or "",
                            "encryption": qs.get("encryption", ["none"])[0],
                            "flow": qs.get("flow", [""])[0],
                        }
                    ],
                }
            ]
        },
        "streamSettings": _stream_settings_qs(qs, parsed),
    }
    return _base_config(outbound, local_port)


def _build_trojan(uri: str, local_port: int) -> Dict:
    parsed = urlparse(uri)
    qs = parse_qs(parsed.query)
    outbound = {
        "protocol": "trojan",
        "settings": {
            "servers": [
                {
                    "address": parsed.hostname or "",
                    "port": parsed.port or 443,
                    "password": unquote(parsed.username or ""),
                }
            ]
        },
        "streamSettings": _stream_settings_qs(qs, parsed),
    }
    return _base_config(outbound, local_port)


def _build_ss(uri: str, local_port: int) -> Dict:
    rest = uri[len("ss://") :]
    if "#" in rest:
        rest = rest.split("#", 1)[0]

    if "@" in rest:
        userinfo, hostinfo = rest.rsplit("@", 1)
        try:
            decoded = base64.b64decode(userinfo + "=" * (-len(userinfo) % 4)).decode()
            method, password = (
                decoded.split(":", 1) if ":" in decoded else (decoded, "")
            )
        except Exception:
            method, password = (
                userinfo.split(":", 1) if ":" in userinfo else (userinfo, "")
            )
    else:
        try:
            decoded = base64.b64decode(rest + "=" * (-len(rest) % 4)).decode()
        except Exception:
            raise ValueError(f"Cannot decode Shadowsocks URI: {uri!r}")
        if "@" in decoded:
            userinfo, hostinfo = decoded.rsplit("@", 1)
            method, password = (
                userinfo.split(":", 1) if ":" in userinfo else (userinfo, "")
            )
        else:
            raise ValueError(f"Cannot parse Shadowsocks URI: {uri!r}")

    host, port_s = hostinfo.rsplit(":", 1) if ":" in hostinfo else (hostinfo, "8388")
    outbound = {
        "protocol": "shadowsocks",
        "settings": {
            "servers": [
                {
                    "address": host,
                    "port": int(port_s),
                    "method": method,
                    "password": password,
                }
            ]
        },
        "streamSettings": {"network": "tcp"},
    }
    return _base_config(outbound, local_port)


_BUILDERS = {
    "vmess": _build_vmess,
    "vless": _build_vless,
    "trojan": _build_trojan,
    "ss": _build_ss,
}


def config_to_xray(uri: str, local_port: int = 10808) -> Dict[str, Any]:
    """Low-level helper: convert a proxy URI to an xray config dict."""
    scheme = uri.split("://", 1)[0].lower() if "://" in uri else ""
    builder = _BUILDERS.get(scheme)
    if builder is None:
        raise UnsupportedProtocolError(scheme)
    return builder(uri, local_port)
