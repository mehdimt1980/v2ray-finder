# Kotlin Migration Plan

This document defines the phased migration of the Android app from the current Java + Chaquopy/Python runtime toward a native Kotlin runtime.

The migration must be incremental. Each phase must be tested before the next one starts. The current Java/Chaquopy app remains the fallback until a native Kotlin phase reaches feature parity.

## Current architecture snapshot

```text
android_app/
  settings.gradle
  build.gradle                    # Android Gradle plugin + Chaquopy plugin
  app/
    build.gradle                  # Android app + Chaquopy Python runtime
    src/main/AndroidManifest.xml  # launcher uses DefaultHealthActivity
    src/main/java/.../MainActivity.java
    src/main/java/.../DefaultHealthActivity.java
    src/main/python/android_bridge.py
    src/main/python/android_source_refresh.py
```

Current runtime flow:

```text
DefaultHealthActivity / MainActivity
→ Chaquopy Python bridge
→ v2ray_finder.Pipeline
→ registry/sources.json
→ fetch configs
→ parse / dedup / health / score
→ JSON payload back to Android UI
```

The current manifest still depends on `com.chaquo.python.android.PyApplication`. Chaquopy must not be removed until the Kotlin runtime has reached feature parity.

## Source registry contract

The source registry is now produced by the external `v2ray-source-hunter` repository. The Android app consumes only the trusted runtime registry:

```text
registry/sources.json
```

The Kotlin runtime must treat this file as the source-of-truth input for source feeds.

Minimum source record fields Kotlin must support:

```json
{
  "id": "source-id",
  "label": "Human label",
  "url": "https://example.com/sub.txt",
  "source_type": "static_subscription",
  "trust": "medium",
  "status": "trusted",
  "enabled": true,
  "tags": ["hunter", "trusted"],
  "protocols": ["vless", "vmess"],
  "notes": "optional",
  "added_at": "2026-06-27",
  "last_reviewed_at": "2026-06-27"
}
```

Default Kotlin loading rule:

```text
include only enabled records whose status is official or trusted
exclude candidate, experimental, quarantine and disabled records unless explicitly requested by a debug/test path
```

## Migration phases

### Phase 0 — Audit and safety baseline

Goal: document architecture and define migration gates without changing runtime behavior.

Allowed changes:

- documentation
- migration notes
- optional non-runtime test metadata

Not allowed:

- adding Kotlin plugin
- changing app entrypoint
- removing Chaquopy
- changing runtime scan behavior
- changing registry loading behavior

Exit criteria:

- no runtime files changed
- current Android build configuration remains unchanged
- migration plan and test gates are documented

### Phase 1 — Kotlin project skeleton beside existing app

Goal: add Kotlin support and a minimal Kotlin package without replacing Java or Python.

Allowed changes:

- add Kotlin Android plugin
- add Kotlin source directory
- add small Kotlin model/utility classes
- add compile-only Kotlin smoke test or compile gate

Not allowed:

- replacing MainActivity
- removing Chaquopy
- changing scan behavior

Exit criteria:

- Gradle sync/build succeeds
- existing launcher remains `DefaultHealthActivity`
- Chaquopy still works

### Phase 2 — Native Kotlin registry loader

Goal: implement Kotlin loading/parsing of `registry/sources.json` while leaving scan execution in Python.

Allowed changes:

- Kotlin data models for source records
- Kotlin JSON parser for bundled registry
- Kotlin filtering for enabled trusted/official records
- lightweight UI/debug path to report loaded source count

Not allowed:

- replacing Python scan pipeline
- changing result scoring

Exit criteria:

- Kotlin loader can parse current `registry/sources.json`
- active source count matches Python registry loader expectations
- existing scan still works

### Phase 3 — Native Kotlin fetcher, parser and dedup

Goal: move fetch + config extraction + dedup to Kotlin.

Allowed changes:

- OkHttp or standard network fetcher
- parsers for raw URI lists and base64 subscriptions
- initial Clash/YAML handling only if safe and tested
- dedup engine

Exit criteria:

- Kotlin fetcher returns configs from trusted sources
- dedup is stable
- output can be compared with Python output on the same registry sample

### Phase 4 — Native Kotlin TCP health and scoring

Goal: move TCP reachability and scoring to Kotlin.

Allowed changes:

- TCP socket reachability checks
- latency measurement
- protocol-aware scoring
- source performance statistics

Exit criteria:

- Kotlin scan produces ranked configs
- UI can display Kotlin results
- Python scan path remains available as fallback

### Phase 5 — Native Kotlin Xray real validation orchestration

Goal: move xray process orchestration out of Python.

Allowed changes:

- Kotlin process management for bundled `libxray.so`
- local SOCKS port handling
- multi-probe HTTP validation
- timeout and cleanup handling

Exit criteria:

- xray starts and stops reliably
- failed configs do not leak processes or ports
- result diagnostics match current UI needs

### Phase 6 — Remove Chaquopy and Python from APK

Goal: remove Python runtime only after native feature parity is confirmed.

Allowed changes:

- remove Chaquopy plugin
- remove Python bridge from APK path
- remove PyApplication from manifest
- remove Python Android dependencies

Exit criteria:

- debug APK builds without Chaquopy
- signed APK builds without Chaquopy
- registry scan, dedup, health check, real validation and UI all work natively

## Test gates

Each phase needs at least these checks:

```text
1. Gradle project configuration check
2. Android debug build or compile check
3. Runtime fallback check when applicable
4. Registry contract check when registry code is touched
5. No unintended source discovery reintroduced into v2ray-finder
```

The rule is simple: do not start the next phase until the current phase has passed its gate.
