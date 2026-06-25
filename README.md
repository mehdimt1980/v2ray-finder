# v2ray-finder

[![PyPI version](https://badge.fury.io/py/v2ray-finder.svg)](https://badge.fury.io/py/v2ray-finder)
[![Python Versions](https://img.shields.io/pypi/pyversions/v2ray-finder.svg)](https://pypi.org/project/v2ray-finder/)
[![License: Apache 2.0](https://img.shields.io/badge/License-Apache%202.0-blue.svg)](https://opensource.org/licenses/Apache-2.0)

[فارسی](README.fa.md) | [English](README.en.md) | [Deutsch](README.de.md) | [📋 CHANGELOG](CHANGELOG.md)

---

A high-performance Python and Android tool to fetch, aggregate, deduplicate, validate, health-check, real-test and score public V2Ray/Xray server configs from GitHub and curated subscription sources.

The project includes both a Python engine and a working native Android APK workflow.

**Built with love for eternal freedom ❤️**

---

## What is included

- Python package: `v2ray_finder/`
- Pipeline engine: discovery → fetch → dedup → health → score
- TCP health check and latency scoring
- Optional Android real check with bundled `xray` + Google-204
- Source Performance Engine for ranking which sources actually produce working configs
- CLI and Rich CLI
- PySide6 desktop GUI
- Native Android app under `android_app/`
- GitHub Actions workflows for debug and signed release APKs

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
  prepare_android_xray_asset.py     # stages xray and patches Android build-time files
```

### Android features

- Native Android UI
- Persian / RTL interface designed for Iranian users
- GitHub token input
- result limit and timeout controls
- TCP health check, enabled by default
- optional real `xray` / Google-204 validation
- fetched / unique / healthy / scored statistics
- scored server cards with protocol, grade, score, latency and source URL
- search, protocol filter and pagination
- structured failed-source diagnostics
- Source Performance section showing top effective sources
- copy all configs or copy a single config
- runs the real `v2ray_finder.Pipeline` through Chaquopy

### Real xray / Google-204 check

The Android CI build can bundle the official Android arm64 `xray` binary. The app starts `xray` locally, opens a SOCKS5 port and checks whether a candidate config can reach Google-204 through that proxy.

```text
TCP check         → host:port is reachable
xray / Google-204 → the config really works through xray
```

The build script stages the binary as:

```text
android_app/app/src/main/jniLibs/arm64-v8a/libxray.so
```

The xray probe config is intentionally minimal and does not use `geoip.dat` or `geosite.dat`, because those data files are not bundled in the APK.

### Source Performance Engine

The engine reports which sources actually produce useful configs. It measures per source:

```text
fetch status
TCP candidates / TCP OK
xray checked / xray OK
latency
trust
source score
error samples
```

See [`docs/SOURCE_PERFORMANCE_ENGINE.md`](docs/SOURCE_PERFORMANCE_ENGINE.md) for details.

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
```

---

## License

Apache License 2.0 © 2026 Ali Sadeghi Aghili

This project is licensed under the **Apache License 2.0**. Any derivative work,
port, or redistribution must retain the [`NOTICE`](NOTICE) file and credit the
original author. See [`LICENSE`](LICENSE) for full terms.
