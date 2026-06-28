# V2Ray Finder Android

Native Android app for finding, scoring and copying public V2Ray/Xray configs from a trusted source registry.

This repository is now focused on the **native Kotlin/Java Android runtime**. The old Python package, Chaquopy bridge, Python CLI and desktop GUI paths have been removed from the active app repository.

## What this app does

- Reads trusted sources from `registry/sources.json`
- Fetches source contents concurrently
- Extracts VLESS, VMess, Trojan and Shadowsocks configs
- Deduplicates and samples configs with a smart native candidate selector
- Runs fast concurrent TCP health checks
- Optionally runs real validation with bundled `xray`
- Scores and ranks configs
- Shows per-source performance diagnostics
- Shows per-config TCP/Xray validation status
- Provides Persian/RTL Android UI with search, protocol filters, pagination and copy buttons

## Current architecture

```text
android_app/
  settings.gradle
  build.gradle
  app/
    build.gradle
    src/main/AndroidManifest.xml
    src/main/java/org/mehdimt/v2rayfinder/
      MainActivity.java
      DefaultHealthActivity.java
      registry/
      runtime/
      runtime/xray/
    src/main/jniLibs/arm64-v8a/libxray.so

registry/
  sources.json

.github/workflows/
  android-apk.yml
  android-release.yml
```

There is no active Python runtime in the Android app. The APK verification step explicitly fails if Chaquopy payloads are present.

## Source registry

The Android app consumes:

```text
registry/sources.json
```

Source discovery and source hunting are intentionally outside this repository. This app only consumes the curated registry.

## Smart native scan pipeline

```text
fetch sources concurrently
→ extract configs
→ early per-source sampling
→ global dedup over sampled configs
→ protocol-aware candidate selection
→ concurrent TCP health checks
→ optional strict xray validation
→ scoring and result rendering
```

The native scanner is optimized for mobile networks and slow connections. It avoids testing every raw config and instead builds a smaller, source-balanced candidate pool before network validation.

## TCP and Xray validation

Each result can show whether it passed TCP and whether it passed real xray validation.

Example status line:

```text
TCP: OK 180ms | Xray: OK 2/4 conf 0.72
```

When xray validation is off:

```text
TCP: OK 180ms | Xray: off
```

The default xray probe set includes:

```text
google_204       → https://clients3.google.com/generate_204
gstatic_204      → https://connectivitycheck.gstatic.com/generate_204
google_www_204   → https://www.google.com/generate_204
cloudflare_trace → https://one.one.one.one/cdn-cgi/trace
```

## Build debug APK

From GitHub Actions:

1. Open **Actions**.
2. Select **Build Android APK**.
3. Run the workflow on `main`.
4. Download `v2ray-finder-native-debug-apk`.

Locally:

```bash
gradle -p android_app :app:assembleDebug
```

The APK is generated under:

```text
android_app/app/build/outputs/apk/debug/
```

## Build signed release APK

Use the GitHub Actions workflow:

```text
Build Signed Android Release APK
```

Required repository secrets:

```text
ANDROID_KEYSTORE_BASE64
ANDROID_KEYSTORE_PASSWORD
ANDROID_KEY_ALIAS
ANDROID_KEY_PASSWORD
```

The workflow verifies that the APK contains:

```text
assets/sources.json
lib/arm64-v8a/libxray.so
```

and fails if any Chaquopy payload is found.

## License

Apache License 2.0. See `LICENSE` and `NOTICE`.
