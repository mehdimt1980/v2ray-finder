# Signed Android release APK

This document explains how to build a signed release APK for the Android app.

The Android app uses:

```text
Native Android UI + Gradle + Chaquopy + v2ray_finder Python package
```

The signed release workflow is:

```text
.github/workflows/android-release.yml
```

## 1. Generate a release keystore

Run this locally on your computer, not in GitHub:

```bash
keytool -genkeypair \
  -v \
  -keystore v2ray-finder-release.jks \
  -storetype JKS \
  -keyalg RSA \
  -keysize 4096 \
  -validity 10000 \
  -alias v2rayfinder
```

Choose strong passwords and keep them safe. You need the same keystore for future app updates.

## 2. Convert the keystore to base64

Linux / macOS:

```bash
base64 -w 0 v2ray-finder-release.jks > keystore-base64.txt
```

If your `base64` command does not support `-w 0`, use:

```bash
base64 v2ray-finder-release.jks | tr -d '\n' > keystore-base64.txt
```

Windows PowerShell:

```powershell
[Convert]::ToBase64String([IO.File]::ReadAllBytes("v2ray-finder-release.jks")) | Out-File -Encoding ascii keystore-base64.txt
```

## 3. Add GitHub Actions secrets

Open:

```text
GitHub repository → Settings → Secrets and variables → Actions → New repository secret
```

Create these four secrets:

```text
ANDROID_KEYSTORE_BASE64      # content of keystore-base64.txt
ANDROID_KEYSTORE_PASSWORD    # keystore password
ANDROID_KEY_ALIAS            # v2rayfinder
ANDROID_KEY_PASSWORD         # key password
```

## 4. Build signed release APK

Open:

```text
Actions → Build Signed Android Release APK → Run workflow
```

Inputs:

```text
version_name: 1.0.0
create_github_release: false or true
```

The artifact will be:

```text
v2ray-finder-signed-release-apk
```

Inside it you will find:

```text
v2ray-finder-android-<version>-signed.apk
apk-signature.txt
```

## 5. Optional GitHub Release

If `create_github_release` is set to `true`, the workflow creates a GitHub Release with this tag format:

```text
android-v<version>
```

Example:

```text
android-v1.0.0
```

## Important notes

- Never commit the `.jks` file to the repository.
- Never share the keystore password or key password publicly.
- Keep the same keystore forever if you want users to receive updates without uninstalling the old app.
- Debug APKs are for testing only. Public distribution should use the signed release APK.
