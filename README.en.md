# v2ray-finder

[![PyPI version](https://badge.fury.io/py/v2ray-finder.svg)](https://badge.fury.io/py/v2ray-finder)
[![Python Versions](https://img.shields.io/pypi/pyversions/v2ray-finder.svg)](https://pypi.org/project/v2ray-finder/)
[![License: Apache 2.0](https://img.shields.io/badge/License-Apache%202.0-blue.svg)](https://opensource.org/licenses/Apache-2.0)

[فارسی](README.fa.md) | **English** | [Deutsch](README.de.md) | [📋 CHANGELOG](CHANGELOG.md)

---

`v2ray-finder` is a high-performance Python and Android tool for fetching, aggregating, deduplicating, validating, health-checking, real-testing and scoring public V2Ray/Xray server configs from GitHub and curated subscription sources.

It can produce clean lists of:

```text
vmess://
vless://
trojan://
ss://
ssr://
```

The repository now contains both the Python engine and a working native Android APK implementation.

---

## Highlights

- Real Python core package: `v2ray_finder/`
- Pipeline engine: discovery → fetch → dedup → health → score
- Async fetching with `httpx`
- TCP health checking and latency scoring
- Real Validation Engine v2 on Android with bundled `xray`, multi-probe checks, confidence scoring and stability signals
- Source Performance Engine for ranking which sources actually produce useful configs
- CLI, Rich CLI and PySide6 desktop GUI
- Native Android app with Chaquopy
- Persian / RTL Android UI designed for Iranian users
- GitHub Actions workflows for debug and signed release APK builds

---

## Android APK

The Android app was rebuilt after testing multiple approaches.

### What changed

The first mobile attempt used Kivy + Buildozer. The APK could be built, but Buildozer only packaged `main.pyc` and repeatedly failed to include the real `v2ray_finder` package. Because of that, the Android build path was migrated to a more reliable architecture:

```text
Native Android UI + Gradle + Chaquopy + real Python package
```

The obsolete Buildozer/Kivy Android entrypoint and `buildozer.spec` were removed from the Android build path.

### Current Android architecture

```text
v2ray_finder/                       # real Python core engine
android_app/
  settings.gradle
  build.gradle
  app/
    build.gradle                    # Android + Chaquopy configuration
    src/main/AndroidManifest.xml
    src/main/java/org/mehdimt/v2rayfinder/MainActivity.java
    src/main/java/org/mehdimt/v2rayfinder/DefaultHealthActivity.java
    src/main/python/android_bridge.py
scripts/
  prepare_android_xray_asset.py     # stages xray and patches Android build-time files
  patch_android_validation_ui.py    # optional UI patch for confidence/stability display
```

The GitHub Actions workflow copies the root `v2ray_finder/` package into:

```text
android_app/app/src/main/python/v2ray_finder/
```

Then Chaquopy packages the Python bridge, the real `Pipeline`, the Real Validation Engine v2, and the Python dependencies into the APK.

### Android UI features

- Native Android interface
- Persian and right-to-left layout
- GitHub token field
- result limit and timeout controls
- TCP health check, enabled by default
- optional Real Validation Engine v2 with bundled `xray`: slower, but much stricter
- fetched / unique / healthy / scored statistics
- result cards with rank, protocol, grade, score, latency and source URL
- validation metadata from the bridge: confidence score, confidence level, probe count and stability count
- search and protocol filter
- pagination for large result sets
- structured failed-source diagnostics
- Source Performance section showing the top effective sources after each scan
- copy all configs
- copy one config from each result card

### Real Validation Engine v2 on Android

The Android build can bundle the official Android arm64 `xray` binary during CI. The app starts `xray` locally, opens a SOCKS5 port, and validates whether the tested config can actually reach multiple lightweight HTTP endpoints through that proxy.

This is stricter than a simple TCP check:

```text
TCP check              → host:port is reachable
single Google-204      → one endpoint works through xray
Real Validation v2     → multiple probes + confidence + stability through xray
```

Real Validation v2 currently uses these probes:

```text
google_204       → clients3.google.com/generate_204
gstatic_204      → connectivitycheck.gstatic.com/generate_204
google_www_204   → www.google.com/generate_204
cloudflare_trace → one.one.one.one/cdn-cgi/trace
```

Each candidate receives:

```text
validation_ok
confidence_score
confidence_level
passed_probes / total_probes
stability_passes / stability_attempts
latency_ms
error diagnostics
```

Confidence is currently weighted as:

```text
50% probe success
25% stability
15% latency
10% Google-204 bonus
```

A config is accepted only when it is reachable, has at least one stability pass, and reaches the minimum confidence threshold. This makes the Android validator stricter than earlier one-shot Google-204 checking.

Important Android implementation details:

- `scripts/prepare_android_xray_asset.py` downloads the Android arm64 `xray` release asset during the build.
- The binary is staged as `android_app/app/src/main/jniLibs/arm64-v8a/libxray.so`.
- The build sets `doNotStrip "**/libxray.so"` so Gradle does not corrupt the executable.
- The Android activity uses `getApplicationInfo().nativeLibraryDir` to launch the bundled binary.
- The generated xray probe config is intentionally minimal and does not use `geoip.dat` or `geosite.dat`, because those data files are not bundled.
- The app captures xray startup errors and shows diagnostics when real validation fails.

### Source Performance Engine

The Source Performance Engine ranks subscription sources by actual usefulness in a scan run. It measures, per source:

```text
fetch status
TCP candidates
TCP OK count
real-validation checked count
real-validation OK count
average latency
best latency
trust
source score
error samples
```

When real validation results are available, source score is weighted toward validated success:

```text
55% real-validation success rate
20% TCP success rate
15% latency score
10% configured trust
```

Without real validation results, the engine falls back to TCP, latency and configured trust. See [`docs/SOURCE_PERFORMANCE_ENGINE.md`](docs/SOURCE_PERFORMANCE_ENGINE.md) for details.

### Android runtime dependencies

The Android module installs:

```gradle
install "requests>=2.31.0"
install "httpx>=0.24.0"
```

`httpx` is required because the real `Pipeline` uses async source fetching.

### Build debug APK with GitHub Actions

1. Go to **Actions** in GitHub.
2. Select **Build Android APK**.
3. Click **Run workflow** on `main`.
4. Download the artifact:

```text
v2ray-finder-chaquopy-debug-apk
```

### Build signed release APK with GitHub Actions

Use the release workflow for an installable signed APK:

```text
Build Signed Android Release APK
version_name: 1.0.10
create_github_release: true
```

Required repository secrets:

```text
ANDROID_KEYSTORE_BASE64
ANDROID_KEYSTORE_PASSWORD
ANDROID_KEY_ALIAS
ANDROID_KEY_PASSWORD
```

### Local Android build

For local builds, stage xray first if you want real validation:

```bash
python scripts/prepare_android_xray_asset.py
python scripts/patch_android_validation_ui.py
gradle -p android_app :app:assembleDebug
```

The debug APK will be generated under:

```text
android_app/app/build/outputs/apk/debug/
```

---

## Python installation

```bash
# Core
pip install v2ray-finder

# Async fetch support
pip install "v2ray-finder[async]"

# Everything
pip install "v2ray-finder[all]"
```

### From source

```bash
git clone https://github.com/mehdimt1980/v2ray-finder.git
cd v2ray-finder
python -m venv .venv
source .venv/bin/activate
pip install -e ".[all,dev]"
```

---

## Python API

```python
from v2ray_finder import Pipeline

pipeline = Pipeline(
    check_health=True,
    check_http_probe=False,
    check_google_204=False,
    limit=200,
)
result = pipeline.run()

print(result.stats)
for score in result.scores[:10]:
    print(score.grade, f"{score.total:.2f}", score.config[:80])
```

---

## CLI

```bash
v2ray-finder -o servers.txt
v2ray-finder -c --min-quality 60 -o healthy_servers.txt
```

Rich CLI:

```bash
pip install "v2ray-finder[cli-rich]"
v2ray-finder-rich
```

---

## Desktop GUI

```bash
pip install "v2ray-finder[gui]"
v2ray-finder-gui
```

The desktop GUI uses the same `Pipeline` engine as the CLI and Android bridge.

---

## Repository layout

```text
v2ray_finder/       # root Python package; moved out of src/ for Android compatibility
android_app/        # native Android + Chaquopy app
scripts/            # Android xray staging and build helpers
src/                # legacy compatibility placeholder only
docs/               # build notes and engine documentation
```

---

## License

Apache License 2.0 © 2026 Ali Sadeghi Aghili

This project is licensed under the **Apache License 2.0**. Any derivative work, port, or redistribution must retain the [`NOTICE`](NOTICE) file and credit the original author. See [`LICENSE`](LICENSE) for full terms.
