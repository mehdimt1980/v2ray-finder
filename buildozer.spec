[app]

# Human-readable app title
title = V2Ray Finder

# Android package metadata
package.name = v2rayfinder
package.domain = org.mehdimt

# Source layout: build from repository root so main.py and src/ are included
source.dir = .
source.include_exts = py,kv,txt,md,toml,json
source.include_patterns = src/**,main.py,README*.md,LICENSE,NOTICE
source.exclude_dirs = .git,.github,tests,docs,htmlcov,build,dist,.venv,venv,__pycache__
source.exclude_patterns = *.pyc,*.pyo,*.pyd,*.so,*.dylib,*.dll

# Version shown by Android
version = 1.0.0

# Runtime dependencies.
# Pin both python3 and hostpython3. Newer python-for-android defaults may build
# CPython 3.14, whose remote-debugging source currently fails on this Android
# CI toolchain. Python 3.11.9 avoids that code path and is stable for Kivy.
requirements = python3==3.11.9,hostpython3==3.11.9,kivy,openssl,requests

# Main Kivy entrypoint
presplash.filename =
icon.filename =

# UI behavior
orientation = portrait
fullscreen = 0

# Android settings
android.permissions = INTERNET
android.api = 35
android.minapi = 23
android.ndk = 25b
android.accept_sdk_license = True

# Build one modern ABI first. Multi-arch builds are slower and often fail during
# p4a bootstrap creation on CI; add armeabi-v7a later after arm64 is stable.
android.archs = arm64-v8a
android.allow_backup = False

# Build output
android.release_artifact = apk

# Python-for-android bootstrap
p4a.bootstrap = sdl2

# Logging
log_level = 2
warn_on_root = 1

[buildozer]
log_level = 2
warn_on_root = 1
