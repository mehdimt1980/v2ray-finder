# v2ray-finder

[![PyPI version](https://badge.fury.io/py/v2ray-finder.svg)](https://badge.fury.io/py/v2ray-finder)
[![Python Versions](https://img.shields.io/pypi/pyversions/v2ray-finder.svg)](https://pypi.org/project/v2ray-finder/)
[![License: Apache 2.0](https://img.shields.io/badge/License-Apache%202.0-blue.svg)](https://opensource.org/licenses/Apache-2.0)

[فارسی](README.fa.md) | [English](README.en.md) | **Deutsch** | [📋 CHANGELOG](CHANGELOG.md)

---

`v2ray-finder` ist ein schnelles Python-Werkzeug zum Abrufen, Aggregieren, Deduplizieren, Validieren, Health-Checking und Bewerten öffentlicher V2Ray/Xray-Konfigurationen aus GitHub und kuratierten Subscription-Quellen.

Das Tool erzeugt saubere Listen mit:

```text
vmess://
vless://
trojan://
ss://
ssr://
```

Das Repository enthält inzwischen zusätzlich eine funktionierende Android-APK-Implementierung.

---

## Hauptfunktionen

- Echtes Python-Core-Paket: `v2ray_finder/`
- Pipeline-Engine: Discovery → Fetch → Dedup → Health → Score
- Asynchrones Fetching mit `httpx`
- TCP-Health-Check und Latenzbewertung
- CLI, Rich CLI und PySide6-Desktop-GUI
- Native Android-App mit Chaquopy
- Persische / RTL Android-Oberfläche für iranische Nutzer
- GitHub-Actions-Workflow zum Erstellen einer Debug-APK

---

## Android APK

Die Android-App wurde nach mehreren Tests neu aufgebaut.

### Was wurde geändert?

Der erste mobile Ansatz nutzte Kivy + Buildozer. Die APK konnte zwar erstellt werden, aber Buildozer verpackte nur `main.pyc` und nahm das echte `v2ray_finder`-Paket nicht zuverlässig in die APK auf. Deshalb wurde der Android-Build auf eine robustere Architektur umgestellt:

```text
Native Android UI + Gradle + Chaquopy + echtes Python-Paket
```

Der alte Buildozer/Kivy-Pfad ist nicht mehr der Hauptweg für die APK-Erstellung.

### Aktuelle Android-Architektur

```text
v2ray_finder/                       # echte Python-Core-Engine
android_app/
  settings.gradle
  build.gradle
  app/
    build.gradle                    # Android- und Chaquopy-Konfiguration
    src/main/AndroidManifest.xml
    src/main/java/org/mehdimt/v2rayfinder/MainActivity.java
    src/main/python/android_bridge.py
```

Der GitHub-Actions-Workflow kopiert das Root-Paket `v2ray_finder/` nach:

```text
android_app/app/src/main/python/v2ray_finder/
```

Anschließend packt Chaquopy den Python-Bridge-Code, die echte `Pipeline` und die Python-Abhängigkeiten in die APK.

### Android-UI-Funktionen

- Native Android-Oberfläche
- Persisch und rechts-nach-links
- Optionales GitHub-Token-Feld
- Steuerung von Ergebnislimit und Timeout
- Optionaler TCP-Health-Check
- Statistiken: Fetched / Unique / Healthy / Scored
- Ergebnis-Karten mit Rang, Protokoll, Qualität, Score und Latenz
- Alle Konfigurationen kopieren
- Einzelne Konfiguration pro Karte kopieren

### Android-Python-Abhängigkeiten

Das Android-Modul installiert:

```gradle
install "requests>=2.31.0"
install "httpx>=0.24.0"
```

`httpx` wird benötigt, weil die echte `Pipeline` asynchrones Source-Fetching nutzt.

### APK mit GitHub Actions bauen

1. In GitHub zu **Actions** gehen.
2. **Build Android APK** auswählen.
3. **Run workflow** auf dem Branch `main` ausführen.
4. Das Artifact herunterladen:

```text
v2ray-finder-chaquopy-debug-apk
```

### Lokaler Android-Build

```bash
gradle -p android_app :app:assembleDebug
```

Die Debug-APK wird hier erzeugt:

```text
android_app/app/build/outputs/apk/debug/
```

### Android-Einschränkung

Layer-3 xray / Google-204 Real-World-Probing ist in der Android-App noch nicht aktiviert. Das Bündeln und Ausführen einer nativen xray-Binärdatei in einer APK benötigt eine separate Android-spezifische Implementierung.

---

## Python-Installation

```bash
pip install v2ray-finder
pip install "v2ray-finder[async]"
pip install "v2ray-finder[all]"
```

### Aus dem Quellcode

```bash
git clone https://github.com/mehdimt1980/v2ray-finder.git
cd v2ray-finder
python -m venv .venv
source .venv/bin/activate
pip install -e ".[all,dev]"
```

---

## Python-API

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

## Desktop-GUI

```bash
pip install "v2ray-finder[gui]"
v2ray-finder-gui
```

Die Desktop-GUI verwendet dieselbe `Pipeline`-Engine wie CLI und Android-Bridge.

---

## Repository-Struktur

```text
v2ray_finder/       # Root-Python-Paket; für Android-Kompatibilität aus src/ verschoben
android_app/        # native Android-App + Chaquopy
src/                # nur Legacy-Kompatibilitätsplatzhalter
docs/               # Build-Hinweise
```

---

## Lizenz

Apache License 2.0 © 2026 Ali Sadeghi Aghili

Dieses Projekt steht unter der **Apache License 2.0**. Jede abgeleitete Arbeit, Portierung oder Weiterverteilung muss die Datei [`NOTICE`](NOTICE) beibehalten und den ursprünglichen Autor nennen. Details siehe [`LICENSE`](LICENSE).
