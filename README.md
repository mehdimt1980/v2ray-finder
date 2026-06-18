# v2ray-finder

[![PyPI version](https://badge.fury.io/py/v2ray-finder.svg)](https://badge.fury.io/py/v2ray-finder)
[![Python Versions](https://img.shields.io/pypi/pyversions/v2ray-finder.svg)](https://pypi.org/project/v2ray-finder/)
[![Tests](https://github.com/alisadeghiaghili/v2ray-finder/workflows/Tests/badge.svg)](https://github.com/alisadeghiaghili/v2ray-finder/actions)
[![Code Quality](https://github.com/alisadeghiaghili/v2ray-finder/workflows/Code%20Quality/badge.svg)](https://github.com/alisadeghiaghili/v2ray-finder/actions)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)
[![GitHub Stars](https://img.shields.io/github/stars/alisadeghiaghili/v2ray-finder?style=flat)](https://github.com/alisadeghiaghili/v2ray-finder/stargazers)

[فارسی](README.fa.md) | [English](README.en.md) | [Deutsch](README.de.md) | [📋 CHANGELOG](CHANGELOG.md)

---

A **high-performance** tool to **fetch, aggregate, validate and health-check public V2Ray server configs** from GitHub and curated subscription sources.

**Built with love for eternal freedom ❤️**

---

## 🚀 What's New in v0.7.0

🛡️ **Structured error model** — `FetchResult.structured_error` with `category` / `kind` / `message` hierarchy (V1-D2)  
🔄 **xray Layer-3 port-contention retry** — auto-retry on a fresh OS port when xray fails to bind (V1-D4)  
🖥️ **GUI fully migrated to Pipeline** — Stop button, real progress bar, Score/Grade/Latency columns, Failed Sources panel (V1-A2)  

```python
from v2ray_finder import Pipeline, StopController

pipeline = Pipeline(check_health=True)
result = pipeline.run()
for score in result.scores[:5]:
    print(score.grade, score.config[:80])
```

> **Full docs:** [README.en.md](README.en.md) | **فارسی:** [README.fa.md](README.fa.md) | **Changelog:** [CHANGELOG.md](CHANGELOG.md)

---

## 📦 Quick Install

```bash
pip install v2ray-finder                # core
pip install "v2ray-finder[async]"       # + httpx for concurrent fetch
pip install "v2ray-finder[all]"         # everything
```

---

## 🧪 Test Coverage

~85% across Python 3.8–3.12, Linux, macOS & Windows.

---

## 📝 License

MIT License © 2026 Ali Sadeghi Aghili
