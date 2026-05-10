"""Manage the xray process lifecycle.

Responsibilities:
  - Locate or auto-download the xray binary
  - Start xray with a given JSON config file
  - Verify the SOCKS5 port is accepting connections
  - Gracefully stop the process

Auto-download fetches the latest release from
https://github.com/XTLS/Xray-core/releases/latest
and caches it in the platform's standard user-cache directory.
"""

from __future__ import annotations

import json
import logging
import os
import platform
import shutil
import socket
import stat
import subprocess
import sys
import tempfile
import time
import zipfile
from pathlib import Path
from typing import List, Optional

import urllib.request

logger = logging.getLogger(__name__)

_XRAY_GITHUB = "https://api.github.com/repos/XTLS/Xray-core/releases/latest"
_STARTUP_TIMEOUT = 5.0  # seconds to wait for SOCKS5 port to open

# Common directories where xray binary might already be installed
_COMMON_INSTALL_DIRS: List[str] = [
    "/usr/local/bin",
    "/usr/bin",
    "/opt/homebrew/bin",
    str(Path.home() / ".local" / "bin"),
    str(Path.home() / "bin"),
]


class XrayBinaryNotFoundError(RuntimeError):
    """Raised when the xray binary cannot be located or downloaded."""

    def __init__(self, message: str = "xray binary not found") -> None:
        super().__init__(message)


def _cache_dir() -> Path:
    """Return platform-appropriate cache directory for xray binary."""
    if sys.platform == "win32":
        base = Path(os.environ.get("LOCALAPPDATA", Path.home()))
    elif sys.platform == "darwin":
        base = Path.home() / "Library" / "Caches"
    else:
        base = Path(os.environ.get("XDG_CACHE_HOME", Path.home() / ".cache"))
    d = base / "v2ray-finder" / "xray"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _asset_name() -> str:
    """Return the release asset filename for the current platform."""
    system = platform.system().lower()
    machine = platform.machine().lower()

    arch_map = {
        "x86_64": "64",
        "amd64": "64",
        "i386": "32",
        "i686": "32",
        "aarch64": "arm64-v8a",
        "arm64": "arm64-v8a",
        "armv7l": "arm32-v7a",
    }
    arch = arch_map.get(machine, "64")

    if system == "windows":
        return f"Xray-windows-{arch}.zip"
    elif system == "darwin":
        return f"Xray-macos-{arch}.zip"
    else:
        return f"Xray-linux-{arch}.zip"


def _binary_name() -> str:
    return "xray.exe" if sys.platform == "win32" else "xray"


def find_xray_binary(extra_path: Optional[str] = None) -> Optional[str]:
    """Return path to xray binary, searching PATH and cache."""
    if extra_path and Path(extra_path).is_file():
        return extra_path
    found = shutil.which("xray")
    if found:
        return found
    # Also check common install dirs
    for d in _COMMON_INSTALL_DIRS:
        candidate = Path(d) / _binary_name()
        if candidate.is_file():
            return str(candidate)
    cached = _cache_dir() / _binary_name()
    if cached.is_file():
        return str(cached)
    return None


def download_xray_binary() -> str:
    """Download latest xray binary from XTLS/Xray-core releases.

    Returns the path to the extracted binary.
    Raises RuntimeError on failure.
    """
    logger.info("Fetching latest xray release info...")
    req = urllib.request.Request(
        _XRAY_GITHUB,
        headers={"User-Agent": "v2ray-finder/1.0", "Accept": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=15) as resp:
        release = json.loads(resp.read().decode())

    asset_name = _asset_name()
    download_url: Optional[str] = None
    for asset in release.get("assets", []):
        if asset["name"] == asset_name:
            download_url = asset["browser_download_url"]
            break

    if not download_url:
        raise RuntimeError(
            f"Could not find asset '{asset_name}' in the latest xray release. "
            f"Please download manually: https://github.com/XTLS/Xray-core/releases"
        )

    cache = _cache_dir()
    zip_path = cache / asset_name
    logger.info("Downloading %s ...", download_url)
    urllib.request.urlretrieve(download_url, zip_path)  # noqa: S310

    with zipfile.ZipFile(zip_path) as zf:
        zf.extractall(cache)

    binary = cache / _binary_name()
    if not binary.is_file():
        raise RuntimeError(f"Binary '{_binary_name()}' not found after extraction.")

    binary.chmod(binary.stat().st_mode | stat.S_IEXEC | stat.S_IXGRP | stat.S_IXOTH)
    zip_path.unlink(missing_ok=True)
    logger.info("xray binary ready at %s", binary)
    return str(binary)


def _wait_for_port(port: int, timeout: float = _STARTUP_TIMEOUT) -> bool:
    """Block until port 127.0.0.1:port accepts connections (or timeout)."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            with socket.create_connection(("127.0.0.1", port), timeout=0.3):
                return True
        except OSError:
            time.sleep(0.1)
    return False


class XrayRunner:
    """Start/stop a single xray process for one server config."""

    def __init__(
        self,
        local_port: int = 10808,
        binary_path: Optional[str] = None,
        auto_download: bool = True,
    ) -> None:
        self.local_port = local_port
        self._binary_path = binary_path
        self._auto_download = auto_download
        self._process: Optional[subprocess.Popen] = None
        self._config_file: Optional[str] = None

    def _get_binary(self) -> str:
        path = find_xray_binary(self._binary_path)
        if path:
            return path
        if self._auto_download:
            logger.info("xray binary not found — downloading...")
            return download_xray_binary()
        raise XrayBinaryNotFoundError(
            "xray binary not found. Install xray or use auto_download=True."
        )

    def find_binary(self) -> Optional[str]:
        """Return path to xray binary if found, else None."""
        return find_xray_binary(self._binary_path)

    def get_version(self) -> Optional[str]:
        """Return xray version string, or None if binary not found."""
        binary = self.find_binary()
        if not binary:
            return None
        try:
            result = subprocess.run(
                [binary, "version"],
                capture_output=True,
                text=True,
                timeout=5,
            )
            first_line = result.stdout.strip().splitlines()[0] if result.stdout else ""
            return first_line or None
        except Exception:
            return None

    def is_available(self) -> bool:
        """Return True if xray binary is available on this system."""
        return self.find_binary() is not None

    async def run(self, config: dict) -> None:  # type: ignore[override]
        """Async context manager entry stub — use as sync context manager instead."""
        raise NotImplementedError(
            "Use XrayRunner as a sync context manager: `with runner: runner.start(cfg)`"
        )

    def start(self, config: dict) -> None:
        """Write *config* to a temp file and start xray.

        Args:
            config: xray JSON config dict (from xray_config_adapter).

        Raises:
            XrayBinaryNotFoundError: If binary not found and auto_download is False.
            RuntimeError: If xray fails to start or the port does not open.
        """
        if self._process and self._process.poll() is None:
            self.stop()  # ensure clean state

        binary = self._get_binary()

        fd, path = tempfile.mkstemp(suffix=".json", prefix="xray_cfg_")
        self._config_file = path
        try:
            with os.fdopen(fd, "w") as fh:
                json.dump(config, fh)
        except Exception:
            os.unlink(path)
            raise

        self._process = subprocess.Popen(
            [binary, "run", "-c", path],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )

        if not _wait_for_port(self.local_port):
            self.stop()
            raise RuntimeError(
                f"xray did not open SOCKS5 port {self.local_port} "
                f"within {_STARTUP_TIMEOUT}s."
            )

    def stop(self) -> None:
        """Terminate xray and clean up the temp config file."""
        if self._process:
            try:
                self._process.terminate()
                self._process.wait(timeout=3)
            except Exception:
                try:
                    self._process.kill()
                except Exception:
                    pass
            self._process = None

        if self._config_file and os.path.exists(self._config_file):
            try:
                os.unlink(self._config_file)
            except OSError:
                pass
            self._config_file = None

    def __enter__(self) -> "XrayRunner":
        return self

    def __exit__(self, *args) -> None:
        self.stop()


# ---------------------------------------------------------------------------
# XrayBinaryManager: the primary class expected by tests.
# Extends XrayRunner with:
#   download_dir    — custom directory for caching the downloaded binary
#   startup_timeout — override _STARTUP_TIMEOUT for port-readiness check
#   socks_port      — alias for local_port
# ---------------------------------------------------------------------------

class XrayBinaryManager(XrayRunner):
    """Extended XrayRunner that supports all parameters expected by tests.

    Parameters mirror XrayRunner, plus:
        download_dir:     Override the default cache directory for the binary.
        startup_timeout:  Seconds to wait for the SOCKS5 port to open.
        socks_port:       Alias for local_port.
    """

    def __init__(
        self,
        local_port: int = 10808,
        binary_path: Optional[str] = None,
        auto_download: bool = True,
        download_dir: Optional[str] = None,
        startup_timeout: float = _STARTUP_TIMEOUT,
        socks_port: Optional[int] = None,
    ) -> None:
        effective_port = socks_port if socks_port is not None else local_port
        super().__init__(
            local_port=effective_port,
            binary_path=binary_path,
            auto_download=auto_download,
        )
        self._startup_timeout = startup_timeout
        self._download_dir: Optional[Path] = None
        if download_dir is not None:
            self._download_dir = Path(download_dir)
            self._download_dir.mkdir(parents=True, exist_ok=True)
        # Cache for find_binary result to avoid repeated shutil.which calls
        self._resolved_binary: Optional[str] = None

    def find_binary(self) -> Optional[str]:
        """Return path to xray binary (cached after first successful lookup)."""
        if self._resolved_binary is not None:
            return self._resolved_binary

        # 1. explicit path
        if self._binary_path and Path(self._binary_path).is_file():
            self._resolved_binary = self._binary_path
            return self._resolved_binary

        # 2. PATH
        found = shutil.which("xray")
        if found:
            self._resolved_binary = found
            return self._resolved_binary

        # 3. common install dirs
        for d in _COMMON_INSTALL_DIRS:
            candidate = Path(d) / _binary_name()
            if candidate.is_file():
                self._resolved_binary = str(candidate)
                return self._resolved_binary

        # 4. custom download_dir
        if self._download_dir is not None:
            candidate = self._download_dir / _binary_name()
            if candidate.is_file():
                self._resolved_binary = str(candidate)
                return self._resolved_binary

        # 5. default cache dir
        cached = _cache_dir() / _binary_name()
        if cached.is_file():
            self._resolved_binary = str(cached)
            return self._resolved_binary

        return None

    def _get_binary(self) -> str:
        """Like XrayRunner._get_binary but honours custom download_dir."""
        path = self.find_binary()
        if path:
            return path
        if self._auto_download:
            logger.info("xray binary not found — downloading...")
            result = self._download_to_dir()
            self._resolved_binary = result
            return result
        raise XrayBinaryNotFoundError(
            "xray binary not found. Install xray or use auto_download=True."
        )

    def _download_to_dir(self) -> str:
        """Download xray binary, using _download_dir if set."""
        logger.info("Fetching latest xray release info...")
        req = urllib.request.Request(
            _XRAY_GITHUB,
            headers={"User-Agent": "v2ray-finder/1.0", "Accept": "application/json"},
        )
        with urllib.request.urlopen(req, timeout=15) as resp:
            release = json.loads(resp.read().decode())

        asset_name = _asset_name()
        download_url: Optional[str] = None
        for asset in release.get("assets", []):
            if asset["name"] == asset_name:
                download_url = asset["browser_download_url"]
                break

        if not download_url:
            raise RuntimeError(
                f"Could not find asset '{asset_name}' in the latest xray release."
            )

        target_dir = self._download_dir if self._download_dir is not None else _cache_dir()
        zip_path = target_dir / asset_name
        logger.info("Downloading %s ...", download_url)
        urllib.request.urlretrieve(download_url, zip_path)

        with zipfile.ZipFile(zip_path) as zf:
            zf.extractall(target_dir)

        binary = target_dir / _binary_name()
        if not binary.is_file():
            raise RuntimeError(f"Binary '{_binary_name()}' not found after extraction.")

        binary.chmod(binary.stat().st_mode | stat.S_IEXEC | stat.S_IXGRP | stat.S_IXOTH)
        zip_path.unlink(missing_ok=True)
        logger.info("xray binary ready at %s", binary)
        return str(binary)

    def get_version(self) -> str:
        """Return xray version string, or 'unknown' if binary not available."""
        try:
            binary = self.find_binary()
            if not binary:
                raise XrayBinaryNotFoundError("xray binary not found")
            result = subprocess.run(
                [binary, "version"],
                capture_output=True,
                text=True,
                timeout=5,
            )
            first_line = result.stdout.strip().splitlines()[0] if result.stdout else ""
            return first_line or "unknown"
        except Exception:
            return "unknown"

    def start(self, config: dict) -> None:
        """Start xray using startup_timeout for port-readiness check."""
        if self._process and self._process.poll() is None:
            self.stop()

        binary = self._get_binary()

        fd, path = tempfile.mkstemp(suffix=".json", prefix="xray_cfg_")
        self._config_file = path
        try:
            with os.fdopen(fd, "w") as fh:
                json.dump(config, fh)
        except Exception:
            os.unlink(path)
            raise

        self._process = subprocess.Popen(
            [binary, "run", "-c", path],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )

        if not _wait_for_port(self.local_port, timeout=self._startup_timeout):
            self.stop()
            raise RuntimeError(
                f"xray did not open SOCKS5 port {self.local_port} "
                f"within {self._startup_timeout}s."
            )

    def run(self, config_path, socks_port: Optional[int] = None):  # type: ignore
        """Async context manager: start xray and yield the process.

        Args:
            config_path: Path object or str to the JSON config file.
            socks_port:  SOCKS5 port xray listens on (overrides local_port).
        """
        import asyncio

        mgr = self
        port = socks_port if socks_port is not None else self.local_port

        class _AsyncCtx:
            def __init__(ctx_self):
                ctx_self._proc = None

            async def __aenter__(ctx_self):
                binary = mgr.find_binary()
                if binary is None:
                    if mgr._auto_download:
                        binary = mgr._download_to_dir()
                    else:
                        raise XrayBinaryNotFoundError("xray binary not found.")

                ctx_self._proc = await asyncio.create_subprocess_exec(
                    binary, "run", "-c", str(config_path),
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                )

                # Wait for a startup marker or timeout
                async def _read_startup():
                    async for line in ctx_self._proc.stdout:
                        if b"started" in line.lower() or b"listening" in line.lower():
                            return
                    if ctx_self._proc.returncode not in (None, 0):
                        raise RuntimeError("xray exited during startup")

                try:
                    await asyncio.wait_for(
                        _read_startup(), timeout=mgr._startup_timeout
                    )
                except asyncio.TimeoutError:
                    ctx_self._proc.kill()
                    await ctx_self._proc.wait()
                    raise RuntimeError(
                        f"xray did not start within {mgr._startup_timeout}s"
                    )

                if ctx_self._proc.returncode is not None and ctx_self._proc.returncode != 0:
                    raise RuntimeError(
                        f"xray crashed on startup (rc={ctx_self._proc.returncode})"
                    )
                return ctx_self._proc

            async def __aexit__(ctx_self, *args):
                if ctx_self._proc and ctx_self._proc.returncode is None:
                    ctx_self._proc.kill()
                    await ctx_self._proc.wait()

        return _AsyncCtx()
