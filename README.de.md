# v2ray-finder

[![PyPI version](https://badge.fury.io/py/v2ray-finder.svg)](https://badge.fury.io/py/v2ray-finder)
[![Python Versions](https://img.shields.io/pypi/pyversions/v2ray-finder.svg)](https://pypi.org/project/v2ray-finder/)
[![License: Apache 2.0](https://img.shields.io/badge/License-Apache%202.0-blue.svg)](https://opensource.org/licenses/Apache-2.0)

[فارسی](README.fa.md) | [English](README.en.md) | **Deutsch** | [📋 CHANGELOG](CHANGELOG.md)

---

`v2ray-finder` ist die Android- und Python-Runtime zum Abrufen, Deduplizieren, Validieren, Health-Checking, Real-Testing und Bewerten von V2Ray/Xray-Konfigurationen aus einer vertrauenswürdigen Source Registry.

Source Discovery ist nicht mehr Teil dieses Repositories. Discovery, Source Hunting, Telegram/GitHub-Crawling, Source Scoring und Registry-Erzeugung werden im separaten Repository [`v2ray-source-hunter`](https://github.com/mehdimt1980/v2ray-source-hunter) ausgeführt.

`v2ray-finder` konsumiert:

```text
registry/sources.json
```

und erzeugt zur Laufzeit saubere Konfigurationen wie:

```text
vmess://
vless://
trojan://
ss://
ssr://
```

---

## Rollen der Repositories

```text
v2ray-source-hunter
→ entdeckt öffentliche Source-Kandidaten
→ validiert und bewertet Source-Feeds
→ materialisiert Telegram-basierte Feeds in saubere Raw-Dateien
→ exportiert app-kompatible Trusted-Registry-Einträge
→ synchronisiert registry/sources.json nach v2ray-finder

v2ray-finder
→ konsumiert registry/sources.json
→ ruft Konfigurationen aus aktivierten Trusted Sources ab
→ dedupliziert Konfigurationen
→ führt Health Checks und Real Validation aus
→ bewertet Konfigurationen
→ berichtet Source Performance
→ baut die Android-APK
```

Diese Trennung verhindert, dass zwei Discovery-Engines dieselbe App-Registry gleichzeitig verändern.

---

## Hauptfunktionen

- Echtes Python-Core-Paket: `v2ray_finder/`
- Registry-gesteuerte Pipeline: Source Registry → Fetch → Dedup → Health → Score
- Keine globale Source Discovery in diesem Repository
- Trusted Registry wird von `v2ray-source-hunter` geliefert
- Asynchrones Fetching mit `httpx`
- TCP-Health-Check und Latenzbewertung
- Real Validation Engine v2 auf Android mit gebündeltem `xray`
- Multi-Probe-Checks, Confidence Score und Stability-Signal
- Source Performance Engine zur Bewertung der Trusted Sources, die wirklich nützliche Konfigurationen liefern
- CLI, Rich CLI und PySide6-Desktop-GUI
- Native Android-App mit Chaquopy
- Persische / RTL Android-Oberfläche für iranische Nutzer
- GitHub-Actions-Workflows für Debug-APK und signierte Release-APK

---

## Android APK

Die Android-App wurde nach mehreren Tests neu aufgebaut.

### Was wurde geändert?

Der erste mobile Ansatz nutzte Kivy + Buildozer. Die APK konnte zwar erstellt werden, aber Buildozer verpackte nur `main.pyc` und nahm das echte `v2ray_finder`-Paket nicht zuverlässig in die APK auf. Deshalb wurde der Android-Build auf diese Architektur umgestellt:

```text
Native Android UI + Gradle + Chaquopy + echtes Python-Paket
```

Der alte Buildozer/Kivy-Pfad wird nicht mehr genutzt.

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
    src/main/java/org/mehdimt/v2rayfinder/DefaultHealthActivity.java
    src/main/python/android_bridge.py
scripts/
  prepare_android_xray_asset.py     # Staging von xray und Android-Build-Dateien
  patch_android_validation_ui.py    # optionaler UI-Patch für Confidence/Stability-Anzeige
registry/
  sources.json                      # Trusted Registry, synchronisiert von v2ray-source-hunter
```

Der GitHub-Actions-Workflow kopiert das Root-Paket `v2ray_finder/` nach:

```text
android_app/app/src/main/python/v2ray_finder/
```

Anschließend packt Chaquopy die Python-Bridge, die echte `Pipeline`, die Real Validation Engine v2 und die Python-Abhängigkeiten in die APK.

### Android-UI-Funktionen

- Native Android-Oberfläche
- Persisch und rechts-nach-links
- GitHub-Token-Feld für Runtime-Fetching bei Bedarf
- Steuerung von Ergebnislimit und Timeout
- TCP-Health-Check, standardmäßig aktiviert
- optionale Real Validation Engine v2 mit gebündeltem `xray`
- Statistiken: Fetched / Unique / Healthy / Scored
- Ergebnis-Karten mit Rang, Protokoll, Qualität, Score, Latenz und Source URL
- Validierungs-Metadaten aus der Bridge: Confidence Score, Confidence Level, Probe-Anzahl und Stability-Anzahl
- Suche und Protokollfilter
- Pagination für große Ergebnislisten
- strukturierte Diagnose für fehlgeschlagene Quellen
- Source-Performance-Bereich mit den besten Trusted Sources nach jedem Scan
- Alle Konfigurationen kopieren
- Einzelne Konfiguration pro Karte kopieren

---

## Source Registry

Die Runtime-Registry liegt hier:

```text
registry/sources.json
```

Diese Datei wird von `v2ray-source-hunter` erzeugt und synchronisiert. `v2ray-finder` führt keine GitHub Source Discovery, Telegram Source Discovery, Source Hunting oder Auto-Promotion-Workflows mehr aus.

Der Standardscan lädt nur aktive und aktivierte Sources mit diesen Statuswerten:

```text
official
trusted
```

Candidate-, Experimental-, Quarantine- und Disabled-Sources werden standardmäßig nicht gescannt.

### Manuelles Onboarding

Single-Source-Onboarding bleibt für lokale oder manuelle Prüfungen verfügbar:

```bash
python -m v2ray_finder.source_onboarding \
  --url https://example.com/sub.txt \
  --label "Example Source" \
  --tcp-sample-size 50 \
  --json
```

Das ist keine globale Discovery. Globale Discovery gehört zu `v2ray-source-hunter`.

---

## Real Validation Engine v2 auf Android

Der Android-Build kann während CI die offizielle Android-arm64-`xray`-Binärdatei bündeln. Die App startet `xray` lokal, öffnet einen SOCKS5-Port und prüft, ob die getestete Konfiguration über diesen Proxy mehrere leichte HTTP-Endpunkte erreichen kann.

```text
TCP check              → host:port ist erreichbar
single Google-204      → ein Endpunkt funktioniert über xray
Real Validation v2     → mehrere Probes + Confidence + Stability über xray
```

Aktuelle Probes:

```text
google_204       → clients3.google.com/generate_204
gstatic_204      → connectivitycheck.gstatic.com/generate_204
google_www_204   → www.google.com/generate_204
cloudflare_trace → one.one.one.one/cdn-cgi/trace
```

Pro Kandidat werden erzeugt:

```text
validation_ok
confidence_score
confidence_level
passed_probes / total_probes
stability_passes / stability_attempts
latency_ms
Fehlerdiagnose
```

Die aktuelle Confidence-Gewichtung:

```text
50% Probe-Erfolg
25% Stability
15% Latenz
10% Google-204-Bonus
```

Eine Konfiguration wird nur akzeptiert, wenn sie erreichbar ist, mindestens einen Stability Pass hat und den Mindest-Confidence-Wert erreicht.

Wichtige Android-Implementierungsdetails:

- `scripts/prepare_android_xray_asset.py` lädt während des Builds das Android-arm64-Release-Asset von xray herunter.
- Die Binärdatei wird als `android_app/app/src/main/jniLibs/arm64-v8a/libxray.so` abgelegt.
- Der Build setzt `doNotStrip "**/libxray.so"`, damit Gradle die ausführbare Datei nicht beschädigt.
- Die Android-Activity verwendet `getApplicationInfo().nativeLibraryDir`, um die gebündelte Binärdatei zu starten.
- Die erzeugte xray-Probe-Konfiguration ist absichtlich minimal und nutzt weder `geoip.dat` noch `geosite.dat`.
- Die App erfasst xray-Startfehler und zeigt Diagnosedaten, wenn echte Validierung fehlschlägt.

---

## Source Performance Engine

Die Source Performance Engine bewertet, welche Trusted Sources in einem Scan wirklich nützlich waren. Pro Quelle werden gemessen:

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

Wenn Real-Validation-Ergebnisse verfügbar sind, wird der Source Score stärker nach validiertem Erfolg gewichtet:

```text
55% real-validation success rate
20% TCP success rate
15% latency score
10% configured trust
```

Ohne Real Validation fällt die Engine auf TCP, Latenz und konfiguriertes Trust zurück. Details stehen in [`docs/SOURCE_PERFORMANCE_ENGINE.md`](docs/SOURCE_PERFORMANCE_ENGINE.md).

---

## Android-Python-Abhängigkeiten

Das Android-Modul installiert:

```gradle
install "requests>=2.31.0"
install "httpx>=0.24.0"
```

`httpx` wird benötigt, weil die echte `Pipeline` asynchrones Source-Fetching nutzt.

---

## Debug-APK mit GitHub Actions bauen

1. In GitHub zu **Actions** gehen.
2. **Build Android APK** auswählen.
3. **Run workflow** auf dem Branch `main` ausführen.
4. Das Artifact herunterladen:

```text
v2ray-finder-chaquopy-debug-apk
```

## Signierte Release-APK mit GitHub Actions bauen

Für eine installierbare signierte APK den Release-Workflow verwenden:

```text
Build Signed Android Release APK
version_name: 1.0.10
create_github_release: true
```

Benötigte Repository-Secrets:

```text
ANDROID_KEYSTORE_BASE64
ANDROID_KEYSTORE_PASSWORD
ANDROID_KEY_ALIAS
ANDROID_KEY_PASSWORD
```

## Lokaler Android-Build

```bash
python scripts/prepare_android_xray_asset.py
python scripts/patch_android_validation_ui.py
gradle -p android_app :app:assembleDebug
```

Die Debug-APK wird hier erzeugt:

```text
android_app/app/build/outputs/apk/debug/
```

---

## Python-Installation

```bash
pip install v2ray-finder
pip install "v2ray-finder[async]"
pip install "v2ray-finder[all]"
```

Aus dem Quellcode:

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
registry/           # Trusted Source Registry, die zur Laufzeit konsumiert wird
scripts/            # xray-Staging und Android-Build-Helfer
src/                # nur Legacy-Kompatibilitätsplatzhalter
docs/               # Build-Hinweise und Engine-Dokumentation
```

---

## Lizenz

Apache License 2.0 © 2026 Ali Sadeghi Aghili

Dieses Projekt steht unter der **Apache License 2.0**. Jede abgeleitete Arbeit, Portierung oder Weiterverteilung muss die Datei [`NOTICE`](NOTICE) beibehalten und den ursprünglichen Autor nennen. Details siehe [`LICENSE`](LICENSE).
