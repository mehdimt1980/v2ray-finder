#!/usr/bin/env python3
"""Patch Android Java UI to display Real Validation v2 diagnostics.

This helper is intentionally small and idempotent.  It is used by CI after the
main xray staging script so release builds expose confidence, stability and
multi-probe counts in result cards even when the Java source has not yet been
manually refactored.
"""

from __future__ import annotations

from pathlib import Path

MAIN_ACTIVITY = Path("android_app/app/src/main/java/org/mehdimt/v2rayfinder/MainActivity.java")

OLD_BLOCK = '''                String meta = "تاخیر: " + latency;
                if (source != null && !source.trim().isEmpty()) meta += "  •  منبع: " + shortUrl(source);
'''

NEW_BLOCK = '''                String confidence = "";
                if (!item.isNull("confidence_score")) {
                    confidence = "  •  اطمینان: " + String.format(Locale.US, "%.0f%%", item.optDouble("confidence_score", 0.0));
                }
                String stability = "";
                if (!item.isNull("stability_attempts")) {
                    stability = "  •  پایداری: " + item.optInt("stability_passes", 0) + "/" + item.optInt("stability_attempts", 0);
                }
                String probes = "";
                if (!item.isNull("passed_probes")) {
                    probes = "  •  پروب: " + item.optInt("passed_probes", 0) + "/" + item.optInt("total_probes", 0);
                }
                String meta = "تاخیر: " + latency + confidence + stability + probes;
                if (source != null && !source.trim().isEmpty()) meta += "  •  منبع: " + shortUrl(source);
'''


def main() -> int:
    text = MAIN_ACTIVITY.read_text(encoding="utf-8")
    if "confidence_score" in text:
        print("MainActivity already shows Real Validation v2 diagnostics.")
        return 0
    if OLD_BLOCK not in text:
        raise SystemExit("Could not locate MainActivity result meta block to patch.")
    MAIN_ACTIVITY.write_text(text.replace(OLD_BLOCK, NEW_BLOCK, 1), encoding="utf-8")
    print("Patched MainActivity result cards with confidence/stability/probe diagnostics.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
