# v2ray-finder

[![PyPI version](https://badge.fury.io/py/v2ray-finder.svg)](https://badge.fury.io/py/v2ray-finder)
[![Python Versions](https://img.shields.io/pypi/pyversions/v2ray-finder.svg)](https://pypi.org/project/v2ray-finder/)
[![License: Apache 2.0](https://img.shields.io/badge/License-Apache%202.0-blue.svg)](https://opensource.org/licenses/Apache-2.0)

[فارسی](README.fa.md) | [English](README.en.md) | [Deutsch](README.de.md) | [📋 CHANGELOG](CHANGELOG.md)

---

A high-performance Python and Android tool to fetch, aggregate, deduplicate, validate, health-check, real-test and score public V2Ray/Xray server configs from a trusted source registry.

Source discovery is intentionally no longer part of this repository. Discovery, source hunting and registry generation are handled by the separate `v2ray-source-hunter` repository. This app consumes `registry/sources.json` as its source of truth.

The project includes both a Python engine and a working native Android APK workflow.

**Built with love for eternal freedom ❤️**

---

## What is included

- Python package: `v2ray_finder/`
- Registry-driven pipeline: source registry → fetch → dedup → health → score
- TCP health check and latency scoring
- Real Validation Engine v2 on Android with bundled `xray`
- Multi-probe validation, confidence scoring and two-pass stability signals
- Source Performance Engine for ranking which trusted sources actually produce working configs
- Source Registry and optional Source Onboarding tools
- CLI and Rich CLI
- PySide6 desktop GUI
- Native Android app under `android_app/`
- GitHub Actions workflows for debug and signed release APKs

---

## Source ownership

`v2ray-finder` is now the app/runtime repository. It does not run GitHub source discovery, Telegram source discovery, source hunting, or auto-promotion workflows.

```text
v2ray-source-hunter
→ discovers, validates, scores and exports trusted source registries
→ syncs registry/sources.json into v2ray-finder

v2ray-finder
→ consumes registry/sources.json
→ fetches configs
→ deduplicates configs
→ health-checks and real-validates configs
→ ranks configs and reports source performance
```

This separation prevents two different discovery engines from mutating `registry/sources.json` at the same time.

---

## Android APK

The Android implementation was rebuilt from the ground up. The earlier Buildozer/Kivy route was removed from the APK build path because it only packaged `main.pyc` and did not reliably include the `v2ray_finder` package.

The current Android architecture is:

```text
v2ray_finder/                       # real Python core engine
android_app/
  settings.gradle
  build.gradle
  app/
    build.gradle                    # Android + Chaquopy config
    src/main/java/.../MainActivity.java
    src/main/java/.../DefaultHealthActivity.java
    src/main/python/android_bridge.py
scripts/
  prepare_android_xray_asset.py     # stages xray and build-time Android patches
  patch_android_validation_ui.py    # optional UI patch for validation metadata
```

### Android features

- Native Android UI
- Persian / RTL interface designed for Iranian users
- GitHub token input
- result limit and timeout controls
- TCP health check, enabled by default
- optional Real Validation Engine v2 with bundled `xray`
- fetched / unique / healthy / scored statistics
- scored server cards with protocol, grade, score, latency and source URL
- validation metadata from the bridge: confidence score, probe count and stability count
- search, protocol filter and pagination
- structured failed-source diagnostics
- Source Performance section showing top effective sources
- copy all configs or copy a single config
- runs the real `v2ray_finder.Pipeline` through Chaquopy

### Real Validation Engine v2

The Android build can bundle the official Android arm64 `xray` binary. The app starts `xray` locally, opens a SOCKS5 port and validates whether a candidate config can reach multiple lightweight HTTP endpoints through that proxy.

```text
TCP check              → host:port is reachable
single Google-204      → one endpoint works through xray
Real Validation v2     → multiple probes + confidence + stability through xray
```

Current probes:

```text
google_204       → clients3.google.com/generate_204
gstatic_204      → connectivitycheck.gstatic.com/generate_204
google_www_204   → www.google.com/generate_204
cloudflare_trace → one.one.one.one/cdn-cgi/trace
```

For every candidate the bridge can return:

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

The xray binary is staged as:

```text
android_app/app/src/main/jniLibs/arm64-v8a/libxray.so
```

The xray probe config is intentionally minimal and does not use `geoip.dat` or `geosite.dat`, because those data files are not bundled in the APK.

### Source Performance Engine

The engine reports which trusted registry sources actually produce useful configs. It measures per source:

```text
fetch status
TCP candidates / TCP OK
real-validation checked / real-validation OK
latency
trust
source score
error samples
```

See [`docs/SOURCE_PERFORMANCE_ENGINE.md`](docs/SOURCE_PERFORMANCE_ENGINE.md) for details.

### Source Registry and Onboarding

The app reads active sources from:

```text
registry/sources.json
```

Candidate onboarding remains available for manual review/testing of a single source, but global source discovery has been removed from this repository. See:

```text
docs/SOURCE_REGISTRY_AND_ONBOARDING.md
```

### Build debug APK with GitHub Actions

1. Open **Actions** in GitHub.
2. Select **Build Android APK**.
3. Click **Run workflow** on `main`.
4. Download the artifact:

```text
v2ray-finder-chaquopy-debug-apk
```

### Build signed release APK

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

```bash
python scripts/prepare_android_xray_asset.py
python scripts/patch_android_validation_ui.py
gradle -p android_app :app:assembleDebug
```

The APK is generated under:

```text
android_app/app/build/outputs/apk/debug/
```

---

## Python install

```bash
pip install v2ray-finder
pip install "v2ray-finder[async]"
pip install "v2ray-finder[all]"
```

---

## Python API

```python
from v2ray_finder import Pipeline

pipeline = Pipeline(check_health=True, limit=200)
result = pipeline.run()

print(result.stats)
for score in result.scores[:10]:
    print(score.grade, score.total, score.config[:80])
```

---

## Repository layout

```text
v2ray_finder/       # root Python package; moved out of src/ for Android compatibility
android_app/        # native Android + Chaquopy app
scripts/            # Android xray staging and build helpers
src/                # legacy compatibility placeholder only
docs/               # build notes and engine documentation
registry/           # trusted source registry consumed by the app
```

---

## License

Apache License 2.0 © 2026 Ali Sadeghi Aghili

This project is licensed under the **Apache License 2.0**. Any derivative work,
port, or redistribution must retain the [`NOTICE`](NOTICE) file and credit the
original author. See [`LICENSE`](LICENSE) for full terms.
