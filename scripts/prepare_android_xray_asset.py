#!/usr/bin/env python3
"""Download and stage Xray for the Android app build.

The Android app runs xray only for the optional Layer-3 Google-204 check.
We stage the official XTLS/Xray-core Android arm64 binary as a native library
named ``libxray.so`` so Android extracts it to an executable nativeLibraryDir.

No binary is committed to the repository; CI downloads it during the build.
"""

from __future__ import annotations

import json
import os
import shutil
import stat
import sys
import tempfile
import urllib.request
import zipfile
from pathlib import Path

REPO_API = "https://api.github.com/repos/XTLS/Xray-core/releases"
DEFAULT_TARGET = Path("android_app/app/src/main/jniLibs/arm64-v8a/libxray.so")


def _request_json(url: str) -> dict:
    headers = {
        "Accept": "application/vnd.github+json",
        "User-Agent": "v2ray-finder-android-build/1.0",
    }
    token = os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN")
    if token:
        headers["Authorization"] = f"Bearer {token}"
    req = urllib.request.Request(url, headers=headers)
    with urllib.request.urlopen(req, timeout=30) as resp:  # noqa: S310 - GitHub API URL is fixed.
        return json.loads(resp.read().decode("utf-8"))


def _download(url: str, dest: Path) -> None:
    headers = {"User-Agent": "v2ray-finder-android-build/1.0"}
    req = urllib.request.Request(url, headers=headers)
    with urllib.request.urlopen(req, timeout=120) as resp, dest.open("wb") as fh:  # noqa: S310
        shutil.copyfileobj(resp, fh)


def _asset_score(name: str) -> tuple[int, int, int]:
    low = name.lower()
    return (
        1 if "arm64-v8a" in low else 0,
        1 if "android" in low else 0,
        1 if low.endswith(".zip") else 0,
    )


def _select_android_arm64_asset(release: dict) -> dict:
    assets = release.get("assets") or []
    candidates: list[dict] = []
    for asset in assets:
        name = str(asset.get("name") or "")
        low = name.lower()
        if not low.endswith(".zip"):
            continue
        if "android" not in low:
            continue
        if "arm64" not in low:
            continue
        candidates.append(asset)

    if not candidates:
        names = "\n".join(str(a.get("name")) for a in assets)
        raise SystemExit(
            "Could not find an Xray Android arm64 zip asset in the selected release.\n"
            f"Available assets:\n{names}"
        )

    candidates.sort(key=lambda a: _asset_score(str(a.get("name") or "")), reverse=True)
    return candidates[0]


def _find_xray_binary(extract_dir: Path) -> Path:
    matches = []
    for path in extract_dir.rglob("*"):
        if not path.is_file():
            continue
        name = path.name.lower()
        if name == "xray" or name == "xray.exe":
            matches.append(path)
    if not matches:
        files = "\n".join(str(p.relative_to(extract_dir)) for p in extract_dir.rglob("*") if p.is_file())
        raise SystemExit(f"Downloaded Xray archive did not contain an xray binary. Files:\n{files}")
    matches.sort(key=lambda p: len(str(p)))
    return matches[0]


def main() -> int:
    tag = os.environ.get("XRAY_RELEASE_TAG", "latest").strip() or "latest"
    target = Path(os.environ.get("XRAY_ANDROID_TARGET", str(DEFAULT_TARGET)))

    release_url = f"{REPO_API}/latest" if tag == "latest" else f"{REPO_API}/tags/{tag}"
    print(f"Fetching Xray release metadata: {release_url}")
    release = _request_json(release_url)
    asset = _select_android_arm64_asset(release)
    asset_name = asset["name"]
    download_url = asset["browser_download_url"]
    print(f"Selected Xray asset: {asset_name}")
    print(f"Release tag: {release.get('tag_name', tag)}")

    with tempfile.TemporaryDirectory(prefix="xray-android-") as tmp:
        tmpdir = Path(tmp)
        zip_path = tmpdir / asset_name
        print(f"Downloading Xray asset to {zip_path}")
        _download(download_url, zip_path)
        if zip_path.stat().st_size <= 0:
            raise SystemExit("Downloaded Xray archive is empty.")

        extract_dir = tmpdir / "extract"
        extract_dir.mkdir()
        with zipfile.ZipFile(zip_path) as zf:
            zf.extractall(extract_dir)

        binary = _find_xray_binary(extract_dir)
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(binary, target)
        target.chmod(target.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)

    print(f"Staged Xray binary: {target}")
    print(f"Size: {target.stat().st_size} bytes")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
