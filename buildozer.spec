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

# Runtime dependencies. Keep this intentionally small for Android stability.
# The mobile app uses the synchronous requests fallback of AsyncFetcher.
requirements = python3,kivy,requests,certifi,charset-normalizer,idna,urllib3

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
android.archs = arm64-v8a, armeabi-v7a
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
