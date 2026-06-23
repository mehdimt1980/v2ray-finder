# v2ray-finder

[![PyPI version](https://badge.fury.io/py/v2ray-finder.svg)](https://badge.fury.io/py/v2ray-finder)
[![Python Versions](https://img.shields.io/pypi/pyversions/v2ray-finder.svg)](https://pypi.org/project/v2ray-finder/)
[![License: Apache 2.0](https://img.shields.io/badge/License-Apache%202.0-blue.svg)](https://opensource.org/licenses/Apache-2.0)

[فارسی](README.fa.md) | [English](README.en.md) | [Deutsch](README.de.md) | [📋 CHANGELOG](CHANGELOG.md)

---

A high-performance tool to fetch, aggregate, deduplicate, validate, health-check and score public V2Ray/Xray server configs from GitHub and curated subscription sources.

The project now includes both a Python engine and a working Android APK workflow.

**Built with love for eternal freedom ❤️**

---

## What is included

- Python package: `v2ray_finder/`
- Pipeline engine: discovery → fetch → dedup → health → score
- CLI and Rich CLI
- PySide6 desktop GUI
- Native Android app under `android_app/`
- GitHub Actions workflow for building a debug APK

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
    src/main/python/android_bridge.py
```

### Android features

- Native Android UI
- Persian / RTL interface designed for Iranian users
- GitHub token input
- result limit and timeout controls
- optional TCP health check
- fetched / unique / healthy / scored statistics
- scored server cards with protocol, grade, score and latency
- copy all configs or copy a single config
- runs the real `v2ray_finder.Pipeline` through Chaquopy

### Build APK with GitHub Actions

1. Open **Actions** in GitHub.
2. Select **Build Android APK**.
3. Click **Run workflow** on `main`.
4. Download the artifact:

```text
v2ray-finder-chaquopy-debug-apk
```

### Local Android build

```bash
gradle -p android_app :app:assembleDebug
```

The APK is generated under:

```text
android_app/app/build/outputs/apk/debug/
```

### Android limitations

Layer-3 xray / Google-204 real-world probing is not enabled in the Android app yet. Bundling and running the native xray binary on Android requires a separate Android-specific implementation.

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
src/                # legacy compatibility placeholder only
docs/               # build notes
```

---

## License

Apache License 2.0 © 2026 Ali Sadeghi Aghili

This project is licensed under the **Apache License 2.0**. Any derivative work,
port, or redistribution must retain the [`NOTICE`](NOTICE) file and credit the
original author. See [`LICENSE`](LICENSE) for full terms.
