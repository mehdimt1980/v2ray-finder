# Android APK build guide

The Android app is now built with a native Android Gradle project and Chaquopy.
Buildozer/Kivy was removed from the Android build path because it only packaged
`main.pyc` and did not reliably include the `v2ray_finder` package.

## Current Android architecture

```text
v2ray_finder/                  # Core Python engine
android_app/
  settings.gradle
  build.gradle
  app/
    build.gradle               # Android + Chaquopy config
    src/main/AndroidManifest.xml
    src/main/java/.../MainActivity.java
    src/main/python/android_bridge.py
```

The GitHub Actions workflow copies the root `v2ray_finder/` package into:

```text
android_app/app/src/main/python/v2ray_finder/
```

Then Gradle and Chaquopy package the Python bridge and the real engine into the APK.

## Build APK on GitHub

1. Open the repository on GitHub.
2. Go to **Actions**.
3. Select **Build Android APK**.
4. Click **Run workflow**.
5. Download the artifact named `v2ray-finder-chaquopy-debug-apk`.

## What the Android app supports

- Native Android UI
- GitHub token input
- Limit and timeout controls
- Optional TCP health check
- Running the real `v2ray_finder.Pipeline`
- Score and grade display
- Result copy to clipboard

Layer-3 xray / Google-204 probing is still disabled for Android. Bundling and running the native xray binary on Android needs a separate platform-specific implementation.

## Local build

Install Java 17 and Gradle, then run:

```bash
gradle -p android_app :app:assembleDebug
```

The APK will be created under:

```text
android_app/app/build/outputs/apk/debug/
```
