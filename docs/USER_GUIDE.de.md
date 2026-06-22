# Vollständige Benutzeranleitung — v2ray-finder

Diese Anleitung richtet sich an Benutzer mit wenig oder keinen technischen Vorkenntnissen. Jeder Schritt wird klar erklärt.

---

## 🌐 Webversion (Keine Installation erforderlich)

Wenn Sie nichts installieren möchten, steht die Online-Version unter folgender Adresse zur Verfügung:

**👉 [rkarimabadi.github.io/v2ray-finder-dotnet](https://rkarimabadi.github.io/v2ray-finder-dotnet)**

Diese Version sammelt und zeigt V2Ray-Links direkt im Browser an — ohne jede Installation. Aufgrund der Einschränkungen der GitHub Pages-Umgebung ist der **Health Check** (Serverqualitätsprüfung) in dieser Version jedoch nicht verfügbar. Wenn Sie diese Funktion benötigen, verwenden Sie stattdessen das Python-Paket.

---

## Was ist v2ray-finder?

Dieses Tool sammelt automatisch kostenlose V2Ray-Links aus verschiedenen Internetquellen, entfernt Duplikate und prüft die Qualität jedes Servers. Das Ergebnis ist eine saubere, sofort einsatzbereite Liste mit `vmess://`-, `vless://`-, `trojan://`-, `ss://`- und `ssr://`-Links.

---

## Schritt 1 — Python installieren

Python muss auf Ihrem Computer installiert sein (Version 3.8 oder höher).

- Zur Überprüfung: Öffnen Sie das Terminal (oder die Eingabeaufforderung unter Windows) und tippen Sie: `python --version`
- Falls nicht installiert, laden Sie es von [python.org](https://www.python.org/downloads/) herunter.

---

## Schritt 2 — Paket installieren

Führen Sie in Ihrem Terminal einen der folgenden Befehle aus:

```bash
# Einfache Installation (minimal)
pip install v2ray-finder

# Vollständige Installation (empfohlen — alle Funktionen)
pip install "v2ray-finder[all]"
```

> **Hinweis:** Die vollständige Installation umfasst die grafische Oberfläche, eine übersichtliche Terminal-UI und bessere Performance.

---

## Schritt 3 — GitHub Token erstellen (Optional, aber empfohlen)

Für diesen Schritt benötigen Sie ein **GitHub-Konto**. Falls Sie noch keins haben, erstellen Sie eines kostenlos unter [github.com/signup](https://github.com/signup).

Ohne Token sind Sie auf 60 Anfragen pro Stunde limitiert. Mit Token steigt diese Zahl auf 5.000.

1. Melden Sie sich bei Ihrem GitHub-Konto an
2. Gehen Sie zu [github.com/settings/tokens](https://github.com/settings/tokens)
3. Klicken Sie auf „Generate new token"
4. Aktivieren Sie den Bereich `public_repo` und erstellen Sie den Token
5. Kopieren Sie den Token (er wird nur einmal angezeigt — speichern Sie ihn sicher)
6. Führen Sie dies im Terminal aus:

```bash
# Linux / macOS
export GITHUB_TOKEN="ghp_ihr_token_hier"

# Windows (Eingabeaufforderung)
set GITHUB_TOKEN=ghp_ihr_token_hier
```

---

## Schritt 4 — Grafische Oberfläche verwenden (GUI)

Die einfachste Option für Benutzer, die mit dem Terminal nicht vertraut sind:

```bash
v2ray-finder-gui
```

Es öffnet sich ein Fenster mit folgenden Funktionen:

| Bereich | Beschreibung |
|---------|-------------- |
| Start-Schaltfläche | Suche und Serverprüfung starten |
| Stop-Schaltfläche | Jederzeit abbrechen |
| Fortschrittsbalken | Zeigt den Fortschritt des Vorgangs |
| Ergebnistabelle | 7 Spalten: #, Protokoll, Bewertung, Note, Latenz (ms), Quelle, Konfiguration |
| Statistikleiste | Gefunden / Eindeutig / Gesund / Bewertet / Cache-Treffer |
| Panel „Fehlgeschlagene Quellen" | Listet Quellen auf, die Fehler zurückgegeben haben |

---

## Schritt 5 — Terminal verwenden (CLI)

Wenn Sie das Terminal bevorzugen, decken diese Befehle die häufigsten Anwendungsfälle ab:

```bash
# Einfacher Start — zeigt die Serverliste an
v2ray-finder

# Ergebnisse in Datei speichern
v2ray-finder -o servers.txt

# Erweiterte GitHub-Suche + Begrenzung auf 200 Server
v2ray-finder -s -l 200 -o servers.txt

# Nur Statistiken anzeigen
v2ray-finder --stats-only

# Nur gesunde, qualitativ hochwertige Server
v2ray-finder -c --min-quality 60 -o healthy_servers.txt
```

**Übersichtlichere Terminal-UI (Rich CLI):**

```bash
v2ray-finder-rich
```

---

## Schritt 6 — Health Check

Das Paket prüft Server auf 3 Ebenen:

- **Ebene 1** — TCP-Verbindung: Ist der Server überhaupt erreichbar?
- **Ebene 2** — HTTP-Probe: Antwortet er?
- **Ebene 3** — Echter Test via xray + Google: Öffnet er tatsächlich das Internet?

Um den Health Check über die CLI zu aktivieren:

```bash
v2ray-finder -c --min-quality 60 -o healthy_servers.txt
```

---

## Bewertungssystem

Jeder Server erhält eine Punktzahl von 0 bis 100 und eine Note von A bis F:

- **A** = Ausgezeichnet (schnell, geringe Latenz, zuverlässig)
- **F** = Schlecht oder unbrauchbar

Die Punktzahl wird anhand von 7 Kriterien berechnet: Latenz, Erreichbarkeit, Protokoll, Quellenvertrauen, Aktualität, Einzigartigkeit und Google-204-Test.

---

## Wie verwende ich die Ausgabe?

Kopieren Sie den gesamten Inhalt von `servers.txt`, tippen Sie dann in Ihrem V2Ray-Client auf **Import from Clipboard** — alle Links werden auf einmal importiert. Dies wird von allen gängigen Clients unterstützt:

- **v2rayNG** (Android)
- **v2rayN** (Windows)
- **Nekoray** (Linux)

Führen Sie nach dem Import einmal einen **TCPing-Test** oder **Real Delay Test** durch, um die tatsächliche Geschwindigkeit jedes Servers zu messen. Sortieren Sie die Liste dann nach dem niedrigsten Ping und verbinden Sie sich mit dem besten Server oben in der Liste.

---

## ❓ Probleme?

- Fehler melden und Fragen stellen unter [github.com/alisadeghiaghili/v2ray-finder/issues](https://github.com/alisadeghiaghili/v2ray-finder/issues)
- Ideen und Diskussionen unter [Discussions](https://github.com/alisadeghiaghili/v2ray-finder/discussions)
