#!/usr/bin/env python3
"""Download and stage Xray for the Android app build.

The Android app uses xray only for the optional Layer-3 Google-204 check.
No binary is committed to the repository; CI downloads it during the build.
"""

from __future__ import annotations

import json
import os
import shutil
import stat
import tempfile
import urllib.request
import zipfile
from pathlib import Path

REPO_API = "https://api.github.com/repos/XTLS/Xray-core/releases"
NATIVE_TARGET = Path("android_app/app/src/main/jniLibs/arm64-v8a/libxray.so")
LEGACY_ASSET_TARGET = Path("android_app/app/src/main/assets/xray/arm64-v8a/xray")
JAVA_ACTIVITY = Path("android_app/app/src/main/java/org/mehdimt/v2rayfinder/DefaultHealthActivity.java")
BUILD_GRADLE = Path("android_app/app/build.gradle")
PY_ROOT = Path("android_app/app/src/main/python")


def _request_json(url: str) -> dict:
    headers = {
        "Accept": "application/vnd.github+json",
        "User-Agent": "v2ray-finder-android-build/1.0",
    }
    token = os.environ.get("GITHUB_TOKEN") or os.environ.get("GH_TOKEN")
    if token:
        headers["Authorization"] = f"Bearer {token}"
    req = urllib.request.Request(url, headers=headers)
    with urllib.request.urlopen(req, timeout=30) as resp:  # noqa: S310 - fixed GitHub API URL.
        return json.loads(resp.read().decode("utf-8"))


def _download(url: str, dest: Path) -> None:
    req = urllib.request.Request(url, headers={"User-Agent": "v2ray-finder-android-build/1.0"})
    with urllib.request.urlopen(req, timeout=120) as resp, dest.open("wb") as fh:  # noqa: S310
        shutil.copyfileobj(resp, fh)


def _select_android_arm64_asset(release: dict) -> dict:
    candidates = []
    for asset in release.get("assets") or []:
        name = str(asset.get("name") or "")
        low = name.lower()
        if low.endswith(".zip") and "android" in low and "arm64" in low:
            candidates.append(asset)
    if not candidates:
        names = "\n".join(str(a.get("name")) for a in release.get("assets") or [])
        raise SystemExit("No Android arm64 Xray zip asset found. Available assets:\n" + names)
    candidates.sort(
        key=lambda a: (
            "arm64-v8a" in str(a.get("name", "")).lower(),
            "android" in str(a.get("name", "")).lower(),
        ),
        reverse=True,
    )
    return candidates[0]


def _find_binary(extract_dir: Path) -> Path:
    matches = [p for p in extract_dir.rglob("*") if p.is_file() and p.name.lower() in {"xray", "xray.exe"}]
    if not matches:
        files = "\n".join(str(p.relative_to(extract_dir)) for p in extract_dir.rglob("*") if p.is_file())
        raise SystemExit("Xray archive did not contain an xray binary. Files:\n" + files)
    matches.sort(key=lambda p: len(str(p)))
    return matches[0]


def _copy_executable(src: Path, dest: Path) -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(src, dest)
    dest.chmod(dest.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
    print(f"Staged: {dest} ({dest.stat().st_size} bytes)")


def _patch_android_activity() -> None:
    if not JAVA_ACTIVITY.exists():
        print(f"Java activity not found, skipping patch: {JAVA_ACTIVITY}")
        return
    text = JAVA_ACTIVITY.read_text(encoding="utf-8")
    text = text.replace("import java.io.FileOutputStream;\nimport java.io.InputStream;\n", "")
    text = text.replace(
        "چند کانفیگ برتر با xray و Google-204 واقعاً تست می‌شوند",
        "۲۰۰ کانفیگ برتر با xray و Google-204 واقعاً تست می‌شوند",
    )
    text = text.replace(
        'py.getModule("android_bridge").callAttr("set_real_check", enabled, xrayBinaryPath, 10);',
        'py.getModule("android_bridge").callAttr("set_real_check", enabled, xrayBinaryPath, 200);',
    )

    start = text.find("    private String prepareXrayBinary() {")
    end = text.find("\n    private int dpLocal", start)
    if start == -1 or end == -1:
        raise SystemExit("Could not locate prepareXrayBinary method for patching.")
    new_method = """    private String prepareXrayBinary() {
        File nativeLib = new File(getApplicationInfo().nativeLibraryDir, \"libxray.so\");
        if (nativeLib.isFile()) {
            return nativeLib.getAbsolutePath();
        }
        return \"\";
    }
"""
    text = text[:start] + new_method + text[end:]
    JAVA_ACTIVITY.write_text(text, encoding="utf-8")
    print("Patched DefaultHealthActivity to use nativeLibraryDir/libxray.so")


def _patch_build_gradle() -> None:
    if not BUILD_GRADLE.exists():
        print(f"Gradle file not found, skipping patch: {BUILD_GRADLE}")
        return
    text = BUILD_GRADLE.read_text(encoding="utf-8")
    text = text.replace('versionCode 9', 'versionCode 10')
    text = text.replace('versionName "1.0.8"', 'versionName "1.0.9"')
    if 'doNotStrip "**/libxray.so"' not in text:
        marker = "    signingConfigs {"
        block = "    packagingOptions {\n        doNotStrip \"**/libxray.so\"\n    }\n\n"
        if marker not in text:
            raise SystemExit("Could not locate signingConfigs marker in build.gradle")
        text = text.replace(marker, block + marker, 1)
    BUILD_GRADLE.write_text(text, encoding="utf-8")
    print("Patched build.gradle: version 1.0.9 and doNotStrip for libxray.so")


def _patch_xray_runner() -> None:
    path = PY_ROOT / "v2ray_finder/xray_runner.py"
    if not path.exists():
        print(f"xray_runner.py not found, skipping patch: {path}")
        return
    text = path.read_text(encoding="utf-8")
    text = text.replace(
        """        self._process = subprocess.Popen(
            [binary, \"run\", \"-c\", path],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )

        if not _wait_for_port(self.local_port):
            self.stop()
            raise RuntimeError(
                f\"xray did not open SOCKS5 port {self.local_port} \"
                f\"within {_STARTUP_TIMEOUT}s.\"
            )
""",
        """        self._process = subprocess.Popen(
            [binary, \"run\", \"-c\", path],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )

        if not _wait_for_port(self.local_port):
            output = self._collect_output()
            self.stop()
            detail = f\" Output: {output[:1000]}\" if output else \"\"
            raise RuntimeError(
                f\"xray did not open SOCKS5 port {self.local_port} \"
                f\"within {_STARTUP_TIMEOUT}s.\" + detail
            )
""",
    )
    marker = "    def stop(self) -> None:\n"
    if "def _collect_output" not in text:
        helper = """    def _collect_output(self) -> str:
        if not self._process:
            return \"\"
        try:
            if self._process.poll() is None:
                self._process.terminate()
            out, err = self._process.communicate(timeout=1)
            return ((out or \"\") + \" \" + (err or \"\")).strip()
        except Exception as exc:
            return f\"could not collect process output: {exc}\"

"""
        text = text.replace(marker, helper + marker, 1)
    path.write_text(text, encoding="utf-8")
    print("Patched xray_runner to capture xray startup output")


def _patch_reality_adapter() -> None:
    path = PY_ROOT / "v2ray_finder/xray_config_adapter.py"
    if not path.exists():
        print(f"xray_config_adapter.py not found, skipping patch: {path}")
        return
    text = path.read_text(encoding="utf-8")
    old = """    if security in (\"tls\", \"xtls\", \"reality\"):
        settings[\"security\"] = security
        sni = qs.get(\"sni\", [\"\"])[0] or (parsed.hostname or \"\")
        settings[\"tlsSettings\"] = {
            \"serverName\": sni,
            \"allowInsecure\": qs.get(\"allowInsecure\", [\"0\"])[0] == \"1\",
        }
"""
    new = """    if security == \"reality\":
        settings[\"security\"] = \"reality\"
        sni = qs.get(\"sni\", [\"\"])[0] or (parsed.hostname or \"\")
        reality = {
            \"serverName\": sni,
            \"fingerprint\": qs.get(\"fp\", [\"chrome\"])[0] or \"chrome\",
            \"publicKey\": qs.get(\"pbk\", [\"\"])[0],
            \"shortId\": qs.get(\"sid\", [\"\"])[0],
            \"spiderX\": qs.get(\"spx\", [\"/\"])[0] or \"/\",
        }
        settings[\"realitySettings\"] = {k: v for k, v in reality.items() if v != \"\"}
    elif security in (\"tls\", \"xtls\"):
        settings[\"security\"] = security
        sni = qs.get(\"sni\", [\"\"])[0] or (parsed.hostname or \"\")
        settings[\"tlsSettings\"] = {
            \"serverName\": sni,
            \"allowInsecure\": qs.get(\"allowInsecure\", [\"0\"])[0] == \"1\",
        }
"""
    if old not in text:
        print("Reality adapter block not found; it may already be patched.")
    else:
        text = text.replace(old, new, 1)
        path.write_text(text, encoding="utf-8")
        print("Patched VLESS/Trojan Reality stream settings")


def _patch_android_bridge() -> None:
    path = PY_ROOT / "android_bridge.py"
    if not path.exists():
        print(f"android_bridge.py not found, skipping patch: {path}")
        return
    text = path.read_text(encoding="utf-8")
    text = text.replace("_real_check_limit = 10", "_real_check_limit = 200")
    text = text.replace("limit: int = 10", "limit: int = 200")
    text = text.replace("min(int(limit or 10), 50)", "min(int(limit or 200), 200)")
    text = text.replace("max_workers=2", "max_workers=4")
    text = text.replace("timeout=max(timeout, 8.0)", "timeout=max(timeout, 6.0)")
    text = text.replace(
        """                real_map = {r.config: r for r in real_results}
                verified_items: list[dict[str, Any]] = []
""",
        """                real_map = {r.config: r for r in real_results}
                error_samples = []
                for r in real_results:
                    if not r.google_204_ok:
                        err = r.error or \"Google-204 did not return OK through proxy\"
                        error_samples.append(f\"{r.protocol}: {err}\")
                real_info[\"error_samples\"] = error_samples[:8]
                verified_items: list[dict[str, Any]] = []
""",
    )
    text = text.replace(
        """    failed_sources: list[dict[str, Any]] = []
    for url, error in result.failed_sources.items():
""",
        """    failed_sources: list[dict[str, Any]] = []
    if _real_check_enabled and real_info.get(\"checked\", 0) and real_info.get(\"ok\", 0) == 0:
        failed_sources.append(
            {
                \"url\": \"xray://layer3/google-204\",
                \"error_type\": \"xray_real_check_failed\",
                \"message\": real_info.get(\"message\", \"xray real check returned zero working configs\")
                + \" Samples: \"
                + \" | \".join(real_info.get(\"error_samples\", [])[:5]),
                \"details\": real_info,
            }
        )
    for url, error in result.failed_sources.items():
""",
    )
    path.write_text(text, encoding="utf-8")
    print("Patched android_bridge real-check diagnostics")


def main() -> int:
    tag = os.environ.get("XRAY_RELEASE_TAG", "latest").strip() or "latest"
    release_url = f"{REPO_API}/latest" if tag == "latest" else f"{REPO_API}/tags/{tag}"
    release = _request_json(release_url)
    asset = _select_android_arm64_asset(release)
    asset_name = asset["name"]
    download_url = asset["browser_download_url"]
    print(f"Selected Xray asset: {asset_name}")

    with tempfile.TemporaryDirectory(prefix="xray-android-") as tmp:
        tmpdir = Path(tmp)
        zip_path = tmpdir / asset_name
        _download(download_url, zip_path)
        extract_dir = tmpdir / "extract"
        extract_dir.mkdir()
        with zipfile.ZipFile(zip_path) as zf:
            zf.extractall(extract_dir)
        binary = _find_binary(extract_dir)
        _copy_executable(binary, NATIVE_TARGET)
        _copy_executable(binary, LEGACY_ASSET_TARGET)
        extra_target = os.environ.get("XRAY_ANDROID_TARGET")
        if extra_target:
            extra = Path(extra_target)
            if extra not in {NATIVE_TARGET, LEGACY_ASSET_TARGET}:
                _copy_executable(binary, extra)

    _patch_android_activity()
    _patch_build_gradle()
    _patch_xray_runner()
    _patch_reality_adapter()
    _patch_android_bridge()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
