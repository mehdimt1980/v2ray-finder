# v2ray-finder

[![PyPI version](https://badge.fury.io/py/v2ray-finder.svg)](https://badge.fury.io/py/v2ray-finder)
[![Python Versions](https://img.shields.io/pypi/pyversions/v2ray-finder.svg)](https://pypi.org/project/v2ray-finder/)
[![License: Apache 2.0](https://img.shields.io/badge/License-Apache%202.0-blue.svg)](https://opensource.org/licenses/Apache-2.0)

[فارسی](README.fa.md) | [English](README.en.md) | **Deutsch** | [📋 CHANGELOG](CHANGELOG.md)

---

`v2ray-finder` ist ein schnelles Python- und Android-Werkzeug zum Abrufen, Aggregieren, Deduplizieren, Validieren, Health-Checking, Real-Testing und Bewerten öffentlicher V2Ray/Xray-Konfigurationen aus GitHub und kuratierten Subscription-Quellen.

Das Tool erzeugt saubere Listen mit:

```text
vmess://
vless://
trojan://
ss://
ssr://
```

Das Repository enthält inzwischen sowohl die Python-Engine als auch eine funktionierende native Android-APK-Implementierung.

---

## Hauptfunktionen

- Echtes Python-Core-Paket: `v2ray_finder/`
- Pipeline-Engine: Discovery → Fetch → Dedup → Health → Score
- Asynchrones Fetching mit `httpx`
- TCP-Health-Check und Latenzbewertung
- Real Validation Engine v2 auf Android mit gebündeltem `xray`, Multi-Probe-Checks, Confidence Score und Stability-Signal
- Source Performance Engine zur Bewertung der Quellen, die wirklich nützliche Konfigurationen liefern
- CLI, Rich CLI und PySide6-Desktop-GUI
- Native Android-App mit Chaquopy
- Persische / RTL Android-Oberfläche für iranische Nutzer
- GitHub-Actions-Workflows für Debug-APK und signierte Release-APK

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
    src/main/java/org/mehdimt/v2rayfinder/DefaultHealthActivity.java
    src/main/python/android_bridge.py
scripts/
  prepare_android_xray_asset.py     # Staging von xray und Android-Build-Patches
  patch_android_validation_ui.py    # optionaler UI-Patch für Confidence/Stability-Anzeige
```

Der GitHub-Actions-Workflow kopiert das Root-Paket `v2ray_finder/` nach:

```text
android_app/app/src/main/python/v2ray_finder/
```

Anschließend packt Chaquopy den Python-Bridge-Code, die echte `Pipeline`, die Real Validation Engine v2 und die Python-Abhängigkeiten in die APK.

### Android-UI-Funktionen

- Native Android-Oberfläche
- Persisch und rechts-nach-links
- Optionales GitHub-Token-Feld
- Steuerung von Ergebnislimit und Timeout
- TCP-Health-Check, standardmäßig aktiviert
- Real Validation Engine v2 mit `xray`: langsamer, aber deutlich strenger
- Statistiken: Fetched / Unique / Healthy / Scored
- Ergebnis-Karten mit Rang, Protokoll, Qualität, Score, Latenz und Quelle
- Validierungs-Metadaten aus der Bridge: Confidence Score, Confidence Level, Probe-Anzahl und Stability-Anzahl
- Suche und Protokollfilter
- Pagination für größere Ergebnislisten
- strukturierte Diagnose für fehlgeschlagene Quellen
- Bereich „effektive Quellen“ mit den besten Sources nach jedem Scan
- Alle Konfigurationen kopieren
- Einzelne Konfiguration pro Karte kopieren

### Real Validation Engine v2 auf Android

Der Android-Build kann während CI die offizielle Android-arm64-`xray`-Binärdatei bündeln. Die App startet `xray` lokal, öffnet einen SOCKS5-Port und prüft, ob die getestete Konfiguration über diesen Proxy mehrere leichte HTTP-Endpunkte erreichen kann.

Das ist strenger als ein einfacher TCP-Test oder ein einzelner Google-204-Test:

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

Eine Konfiguration wird nur akzeptiert, wenn sie erreichbar ist, mindestens einen Stability Pass hat und den Mindest-Confidence-Wert erreicht. Dadurch ist die Android-Validierung strenger als die frühere einmalige Google-204-Prüfung.

Wichtige Implementierungsdetails für Android:

- `scripts/prepare_android_xray_asset.py` lädt während des Builds das Android-arm64-Release-Asset von xray herunter.
- Die Binärdatei wird als `android_app/app/src/main/jniLibs/arm64-v8a/libxray.so` abgelegt.
- Der Build setzt `doNotStrip "**/libxray.so"`, damit Gradle die ausführbare Datei nicht beschädigt.
- Die Android-Activity verwendet `getApplicationInfo().nativeLibraryDir`, um die gebündelte Binärdatei zu starten.
- Die erzeugte xray-Probe-Konfiguration ist absichtlich minimal und nutzt weder `geoip.dat` noch `geosite.dat`, weil diese Daten nicht in der APK enthalten sind.
- Die App erfasst xray-Startfehler und zeigt Diagnosedaten, wenn echte Validierung fehlschlägt.

### Source Performance Engine

Die Source Performance Engine bewertet, welche Subscription-Quellen in einem Scan wirklich nützlich waren. Pro Quelle werden unter anderem gemessen:

```text
Fetch-Status
TCP-Kandidaten
TCP-OK-Anzahl
real-validation checked count
real-validation OK count
durchschnittliche Latenz
beste Latenz
Trust
Source Score
Fehlerbeispiele
```

Wenn echte Validierungsergebnisse verfügbar sind, wird der Source Score stärker nach Validierungserfolg gewichtet:

```text
55% real-validation success rate
20% TCP success rate
15% latency score
10% configured trust
```

Ohne Real Validation fällt die Engine auf TCP, Latenz und konfiguriertes Trust zurück. Details stehen in [`docs/SOURCE_PERFORMANCE_ENGINE.md`](docs/SOURCE_PERFORMANCE_ENGINE.md).

### Android-Python-Abhängigkeiten

Das Android-Modul installiert:

```gradle
install "requests>=2.31.0"
install "httpx>=0.24.0"
```

`httpx` wird benötigt, weil die echte `Pipeline` asynchrones Source-Fetching nutzt.

### Debug-APK mit GitHub Actions bauen

1. In GitHub zu **Actions** gehen.
2. **Build Android APK** auswählen.
3. **Run workflow** auf dem Branch `main` ausführen.
4. Das Artifact herunterladen:

```text
v2ray-finder-chaquopy-debug-apk
```

### Signierte Release-APK mit GitHub Actions bauen

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

### Lokaler Android-Build

Für lokale Builds zuerst xray und den UI-Patch vorbereiten, wenn Real Validation v2 benötigt wird:

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
scripts/            # xray-Staging und Android-Build-Helfer
src/                # nur Legacy-Kompatibilitätsplatzhalter
docs/               # Build-Hinweise und Engine-Dokumentation
```

---

## Lizenz

Apache License 2.0 © 2026 Ali Sadeghi Aghili

Dieses Projekt steht unter der **Apache License 2.0**. Jede abgeleitete Arbeit, Portierung oder Weiterverteilung muss die Datei [`NOTICE`](NOTICE) beibehalten und den ursprünglichen Autor nennen. Details siehe [`LICENSE`](LICENSE).
