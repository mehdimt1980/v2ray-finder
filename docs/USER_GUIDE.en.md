# Complete User Guide — v2ray-finder

This guide is written for users with little or no technical background. Every step is explained clearly.

---

## 🌐 Web Version (No Installation Required)

If you don't want to install anything, the online version is available at:

**👉 [rkarimabadi.github.io/v2ray-finder-dotnet](https://rkarimabadi.github.io/v2ray-finder-dotnet)**

This version collects and displays V2Ray links directly in your browser — no installation needed. However, due to GitHub Pages environment limitations, **Health Check** (server quality verification) is not available in this version. If you need that feature, use the Python package instead.

---

## What is v2ray-finder?

This tool automatically collects free V2Ray links from various internet sources, removes duplicates, and checks the quality of each server. The output is a clean, ready-to-use list of `vmess://`, `vless://`, `trojan://`, `ss://`, and `ssr://` links.

---

## Step 1 — Install Python

Python must be installed on your computer (version 3.8 or higher).

- To check: open Terminal (or Command Prompt on Windows) and type: `python --version`
- If not installed, download it from [python.org](https://www.python.org/downloads/).

---

## Step 2 — Install the Package

In your terminal, run one of the following commands:

```bash
# Basic install (minimal)
pip install v2ray-finder

# Full install (recommended — all features)
pip install "v2ray-finder[all]"
```

> **Note:** The full install includes the graphical interface, a beautiful terminal UI, and faster performance.

---

## Step 3 — Get a GitHub Token (Optional but Recommended)

You need a **GitHub account** for this step. If you don't have one, create one for free at [github.com/signup](https://github.com/signup).

Without a token you are limited to 60 requests per hour. With a token this increases to 5,000.

1. Log in to your GitHub account
2. Go to [github.com/settings/tokens](https://github.com/settings/tokens)
3. Click "Generate new token"
4. Check the `public_repo` scope and generate the token
5. Copy the token (it is shown only once — save it somewhere safe)
6. Run this in your terminal:

```bash
# Linux / macOS
export GITHUB_TOKEN="ghp_your_token_here"

# Windows (Command Prompt)
set GITHUB_TOKEN=ghp_your_token_here
```

---

## Step 4 — Use the Graphical Interface (GUI)

The easiest option for users who are not comfortable with the terminal:

```bash
v2ray-finder-gui
```

A window opens with the following features:

| Section | Description |
|---------|-------------|
| Start button | Begin searching and checking servers |
| Stop button | Cancel at any point |
| Progress bar | Shows how far along the process is |
| Results table | 7 columns: #, Protocol, Score, Grade, Latency (ms), Source, Config |
| Stats bar | Fetched / Unique / Healthy / Scored / Cache hits |
| Failed Sources panel | Lists sources that returned errors |

---

## Step 5 — Use the Terminal (CLI)

If you prefer the terminal, these commands cover the most common use cases:

```bash
# Simple run — displays the server list
v2ray-finder

# Save results to a file
v2ray-finder -o servers.txt

# Broader GitHub search + limit to 200 servers
v2ray-finder -s -l 200 -o servers.txt

# Show statistics only
v2ray-finder --stats-only

# Only healthy, high-quality servers
v2ray-finder -c --min-quality 60 -o healthy_servers.txt
```

**Beautiful terminal UI (Rich CLI):**

```bash
v2ray-finder-rich
```

---

## Step 6 — Health Check

The package verifies servers across 3 layers:

- **Layer 1** — TCP connectivity: is the server reachable at all?
- **Layer 2** — HTTP probe: does it respond?
- **Layer 3** — Real-world test via xray + Google: does it actually open the internet?

To enable health checking from the CLI:

```bash
v2ray-finder -c --min-quality 60 -o healthy_servers.txt
```

---

## Scoring System

Each server receives a score from 0 to 100 and a grade from A to F:

- **A** = Excellent (fast, low latency, reliable)
- **F** = Poor or unusable

The score is calculated across 7 dimensions: latency, reachability, protocol, source trust, freshness, uniqueness, and Google 204 test.

---

## How Do I Use the Output?

Copy the entire contents of `servers.txt`, then tap **Import from Clipboard** in your V2Ray client — all links are imported at once. This is supported by all common clients:

- **v2rayNG** (Android)
- **v2rayN** (Windows)
- **Nekoray** (Linux)

After importing, run a **TCPing Test** or **Real Delay Test** once to measure the actual speed of each server. Then sort the list by lowest ping and connect to the best server at the top.

---

## ❓ Having Issues?

- Report bugs and ask questions at [github.com/alisadeghiaghili/v2ray-finder/issues](https://github.com/alisadeghiaghili/v2ray-finder/issues)
- Ideas and discussions at [Discussions](https://github.com/alisadeghiaghili/v2ray-finder/discussions)
