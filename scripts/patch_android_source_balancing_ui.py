#!/usr/bin/env python3
"""Patch MainActivity to show source-balanced sampling diagnostics."""

from __future__ import annotations

from pathlib import Path

TARGET = Path("android_app/app/src/main/java/org/mehdimt/v2rayfinder/MainActivity.java")
OLD = '''            String done = "تمام شد. " + latestConfigs.size() + " کانفیگ آماده است.";
            if (currentSourcePerformance.length() > 0) {
                done += " عملکرد " + currentSourcePerformance.length() + " منبع تحلیل شد.";
            }
'''
NEW = '''            String done = "تمام شد. " + latestConfigs.size() + " کانفیگ آماده است.";
            JSONObject balancing = stats == null ? null : stats.optJSONObject("source_balancing");
            if (balancing != null && balancing.optBoolean("enabled", false)) {
                done += " نمونه‌گیری متوازن از " + balancing.optInt("active_sources", 0)
                        + " منبع فعال انجام شد"
                        + "؛ سقف هر منبع: " + balancing.optInt("per_source_cap", 0) + ".";
            }
            if (currentSourcePerformance.length() > 0) {
                done += " عملکرد " + currentSourcePerformance.length() + " منبع تحلیل شد.";
            }
'''


def main() -> int:
    text = TARGET.read_text(encoding="utf-8")
    if 'stats.optJSONObject("source_balancing")' in text:
        print("Source balancing UI already patched.")
        return 0
    if OLD not in text:
        raise SystemExit("Could not find status message block to patch.")
    TARGET.write_text(text.replace(OLD, NEW), encoding="utf-8")
    print("Patched MainActivity source balancing status message.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
