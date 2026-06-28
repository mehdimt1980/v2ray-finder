# Kotlin Migration Phase 0 Audit

Phase 0 is a safety baseline. It records what exists today and what must not change before Kotlin code is introduced.

## Branch

```text
kotlin-migration-phase-0
```

## Files inspected

```text
android_app/settings.gradle
android_app/build.gradle
android_app/app/build.gradle
android_app/app/src/main/AndroidManifest.xml
android_app/app/src/main/java/org/mehdimt/v2rayfinder/MainActivity.java
android_app/app/src/main/java/org/mehdimt/v2rayfinder/DefaultHealthActivity.java
```

## Current Gradle state

Root Android project:

```text
rootProject.name = V2RayFinderAndroid
include :app
```

Top-level Android Gradle plugins:

```text
com.android.application 8.7.3
com.chaquo.python 17.0.0
```

App module plugins:

```text
com.android.application
com.chaquo.python
```

The app currently has no Kotlin plugin. Phase 0 intentionally does not add one.

## Current Android app config

```text
namespace: org.mehdimt.v2rayfinder
applicationId: org.mehdimt.v2rayfinder
compileSdk: 35
minSdk: 24
targetSdk: 35
versionCode: 11
versionName: 1.0.10
ABI: arm64-v8a
Java source/target compatibility: 17
```

## Current Chaquopy config

```text
Python version: 3.11
buildPython: python3.11
pip packages:
  requests>=2.31.0
  httpx>=0.24.0
```

## Current manifest state

The app uses:

```text
android:name="com.chaquo.python.android.PyApplication"
launcher activity: .DefaultHealthActivity
```

This means Chaquopy is still required at app startup. It must not be removed until Phase 6.

## Current Java UI/runtime dependency points

`MainActivity.java`:

```text
- builds the Persian RTL UI programmatically
- starts scans through Chaquopy Python.getInstance()
- calls android_bridge.scan(...)
- receives JSON payload
- renders stats, configs, failed sources and source performance
```

`DefaultHealthActivity.java`:

```text
- extends MainActivity
- enables TCP health check by default
- adds Real Validation v2 checkbox
- locates bundled libxray.so
- calls android_bridge.set_real_check(...)
- calls android_source_refresh.refresh_sources_now()
```

## Known migration risks

```text
1. UI and Python scan bridge are tightly coupled through JSON payload shape.
2. Chaquopy application class is in the manifest.
3. xray orchestration currently depends on Python bridge state.
4. source refresh is currently Python-backed.
5. result rendering expects exact JSON fields from android_bridge.scan.
```

## JSON payload contract used by Java UI

The current UI expects at least:

```text
stats.fetched
stats.deduped
stats.healthy
stats.scored
configs[]
items[].config
items[].protocol
items[].grade
items[].total
items[].latency_ms
items[].source
failed_sources[]
source_performance[]
```

The future Kotlin runtime must either preserve this payload shape or the UI migration must be done at the same time.

## Phase 0 validation

Phase 0 changes only documentation. It does not modify:

```text
android_app/build.gradle
android_app/app/build.gradle
AndroidManifest.xml
MainActivity.java
DefaultHealthActivity.java
android_bridge.py
android_source_refresh.py
registry/sources.json
```

Expected result:

```text
Runtime behavior unchanged.
Existing Java + Chaquopy app remains the active implementation.
Kotlin migration is documented but not yet started.
```

## Next phase gate

Phase 1 may start only after Phase 0 is reviewed and confirmed.

Phase 1 will add Kotlin support without replacing Java or Python.
