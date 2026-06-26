#!/usr/bin/env python3
"""Patch Android MainActivity to call the source-balanced scan bridge."""

from __future__ import annotations

from pathlib import Path

TARGET = Path("android_app/app/src/main/java/org/mehdimt/v2rayfinder/MainActivity.java")
OLD = 'PyObject bridge = py.getModule("android_bridge");'
NEW = 'PyObject bridge = py.getModule("android_bridge_balanced");'


def main() -> int:
    text = TARGET.read_text(encoding="utf-8")
    if NEW in text:
        print("MainActivity already uses android_bridge_balanced.")
        return 0
    if OLD not in text:
        raise SystemExit(f"Could not find expected scan bridge line in {TARGET}")
    TARGET.write_text(text.replace(OLD, NEW), encoding="utf-8")
    print("Patched MainActivity to use android_bridge_balanced.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
