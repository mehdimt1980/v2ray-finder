# v2ray-finder

[![PyPI version](https://badge.fury.io/py/v2ray-finder.svg)](https://badge.fury.io/py/v2ray-finder)
[![Python Versions](https://img.shields.io/pypi/pyversions/v2ray-finder.svg)](https://pypi.org/project/v2ray-finder/)
[![License: Apache 2.0](https://img.shields.io/badge/License-Apache%202.0-blue.svg)](https://opensource.org/licenses/Apache-2.0)

[فارسی](README.fa.md) | **English** | [Deutsch](README.de.md) | [📋 CHANGELOG](CHANGELOG.md)

---

`v2ray-finder` is a high-performance Python tool for fetching, aggregating, deduplicating, validating, health-checking and scoring public V2Ray/Xray server configs from GitHub and curated subscription sources.

It can produce clean lists of:

```text
vmess://
vless://
trojan://
ss://
ssr://
```

The repository now also contains a working Android APK implementation.

---

## Highlights

- Real Python core package: `v2ray_finder/`
- Pipeline engine: discovery → fetch → dedup → health → score
- Async fetching with `httpx`
- TCP health checking and latency scoring
- CLI, Rich CLI and PySide6 desktop GUI
- Native Android app with Chaquopy
- Persian / RTL Android UI designed for Iranian users
- GitHub Actions workflow to build a debug APK

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
    src/main/python/android_bridge.py
```

The GitHub Actions workflow copies the root `v2ray_finder/` package into:

```text
android_app/app/src/main/python/v2ray_finder/
```

Then Chaquopy packages the Python bridge, the real `Pipeline`, and the Python dependencies into the APK.

### Android UI features

- Native Android interface
- Persian and right-to-left layout
- GitHub token field
- result limit and timeout controls
- optional TCP health check
- fetched / unique / healthy / scored statistics
- result cards with rank, protocol, grade, score and latency
- copy all configs
- copy one config from each result card

### Android runtime dependencies

The Android module installs:

```gradle
install "requests>=2.31.0"
install "httpx>=0.24.0"
```

`httpx` is required because the real `Pipeline` uses async source fetching.

### Build APK with GitHub Actions

1. Go to **Actions** in GitHub.
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

The debug APK will be generated under:

```text
android_app/app/build/outputs/apk/debug/
```

### Android limitation

Layer-3 xray / Google-204 real-world probing is not enabled in the Android app yet. Running a native xray binary inside an APK needs a separate Android-specific packaging strategy.

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
src/                # legacy compatibility placeholder only
docs/               # build notes
```

---

## License

Apache License 2.0 © 2026 Ali Sadeghi Aghili

This project is licensed under the **Apache License 2.0**. Any derivative work, port, or redistribution must retain the [`NOTICE`](NOTICE) file and credit the original author. See [`LICENSE`](LICENSE) for full terms.
