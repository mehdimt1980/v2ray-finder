# v2ray-finder

[![PyPI version](https://badge.fury.io/py/v2ray-finder.svg)](https://badge.fury.io/py/v2ray-finder)
[![Python Versions](https://img.shields.io/pypi/pyversions/v2ray-finder.svg)](https://pypi.org/project/v2ray-finder/)
[![License: Apache 2.0](https://img.shields.io/badge/License-Apache%202.0-blue.svg)](https://opensource.org/licenses/Apache-2.0)

**فارسی** | [English](README.en.md) | [Deutsch](README.de.md) | [📋 CHANGELOG](CHANGELOG.md)

---

`v2ray-finder` ابزاری سریع برای دریافت، جمع‌آوری، حذف موارد تکراری، اعتبارسنجی، بررسی سلامت و امتیازدهی کانفیگ‌های عمومی V2Ray/Xray از GitHub و منابع subscription انتخاب‌شده است.

خروجی ابزار، لیستی تمیز از لینک‌های زیر است:

```text
vmess://
vless://
trojan://
ss://
ssr://
```

این پروژه حالا علاوه بر موتور پایتونی، یک اپلیکیشن اندروید قابل نصب هم دارد.

---

## ویژگی‌های اصلی

- موتور اصلی پایتون در پکیج `v2ray_finder/`
- زنجیره کامل Pipeline: کشف منبع → دریافت → حذف تکراری‌ها → بررسی سلامت → امتیازدهی
- دریافت async با `httpx`
- بررسی سلامت TCP و سنجش latency
- CLI، Rich CLI و GUI دسکتاپ با PySide6
- اپلیکیشن native اندروید با Chaquopy
- رابط فارسی و راست‌به‌چپ برای کاربران ایران
- ساخت APK از طریق GitHub Actions

---

## اپلیکیشن اندروید

مسیر اندروید پروژه بعد از چند مرحله آزمایش بازطراحی شد.

### چه چیزی تغییر کرد؟

نسخه اول موبایل با Kivy و Buildozer ساخته شد. APK ساخته می‌شد، اما Buildozer فقط `main.pyc` را وارد APK می‌کرد و پکیج اصلی `v2ray_finder` وارد برنامه نمی‌شد. به همین دلیل، مسیر اندروید به معماری مطمئن‌تر منتقل شد:

```text
Native Android UI + Gradle + Chaquopy + real Python package
```

مسیر Buildozer/Kivy دیگر مسیر اصلی ساخت APK نیست.

### معماری فعلی Android

```text
v2ray_finder/                       # موتور اصلی پایتون
android_app/
  settings.gradle
  build.gradle
  app/
    build.gradle                    # تنظیمات Android + Chaquopy
    src/main/AndroidManifest.xml
    src/main/java/org/mehdimt/v2rayfinder/MainActivity.java
    src/main/python/android_bridge.py
```

در workflow گیت‌هاب، پکیج اصلی از ریشه پروژه به مسیر زیر کپی می‌شود:

```text
android_app/app/src/main/python/v2ray_finder/
```

بعد Chaquopy فایل bridge، موتور واقعی `Pipeline` و dependencyهای پایتون را داخل APK بسته‌بندی می‌کند.

### امکانات رابط اندروید

- رابط native اندروید
- فارسی و راست‌به‌چپ
- فیلد توکن GitHub اختیاری
- کنترل تعداد نتایج و مهلت اتصال
- بررسی سلامت TCP
- آمار دریافتی / یکتا / سالم / رتبه‌بندی‌شده
- کارت‌های نتیجه با رتبه، پروتکل، کیفیت، امتیاز و تاخیر
- کپی همه کانفیگ‌ها
- کپی تک‌کانفیگ از هر کارت

### dependencyهای اندروید

در ماژول اندروید این dependencyهای پایتون نصب می‌شوند:

```gradle
install "requests>=2.31.0"
install "httpx>=0.24.0"
```

`httpx` لازم است چون موتور اصلی `Pipeline` برای دریافت async منابع از آن استفاده می‌کند.

### ساخت APK با GitHub Actions

1. در GitHub وارد بخش **Actions** شو.
2. workflow با نام **Build Android APK** را انتخاب کن.
3. روی **Run workflow** بزن و branch را روی `main` بگذار.
4. بعد از پایان build، artifact زیر را دانلود کن:

```text
v2ray-finder-chaquopy-debug-apk
```

### ساخت محلی APK

```bash
gradle -p android_app :app:assembleDebug
```

APK در این مسیر ساخته می‌شود:

```text
android_app/app/build/outputs/apk/debug/
```

### محدودیت نسخه اندروید

بررسی واقعی لایه ۳ با xray / Google-204 هنوز در اپ اندروید فعال نیست. اجرای باینری native xray داخل APK نیاز به پیاده‌سازی جداگانه مخصوص Android دارد.

---

## نصب نسخه پایتون

```bash
pip install v2ray-finder
pip install "v2ray-finder[async]"
pip install "v2ray-finder[all]"
```

### نصب از سورس

```bash
git clone https://github.com/mehdimt1980/v2ray-finder.git
cd v2ray-finder
python -m venv .venv
source .venv/bin/activate
pip install -e ".[all,dev]"
```

---

## استفاده به‌صورت کتابخانه

```python
from v2ray_finder import Pipeline

pipeline = Pipeline(
    check_health=True,
    check_http_probe=False,
    check_google_204=False,
    limit=200,
)
result = pipeline.run()

print(result.stats)
for score in result.scores[:10]:
    print(score.grade, f"{score.total:.2f}", score.config[:80])
```

---

## CLI

```bash
v2ray-finder -o servers.txt
v2ray-finder -c --min-quality 60 -o healthy_servers.txt
```

Rich CLI:

```bash
pip install "v2ray-finder[cli-rich]"
v2ray-finder-rich
```

---

## GUI دسکتاپ

```bash
pip install "v2ray-finder[gui]"
v2ray-finder-gui
```

GUI دسکتاپ از همان موتور `Pipeline` استفاده می‌کند که در CLI و Android bridge هم استفاده می‌شود.

---

## ساختار repository

```text
v2ray_finder/       # پکیج اصلی پایتون؛ برای سازگاری اندروید از src خارج شد
android_app/        # اپ native اندروید + Chaquopy
src/                # فقط placeholder برای سازگاری با workflowهای قدیمی
docs/               # یادداشت‌های build
```

---

## مجوز

Apache License 2.0 © 2026 Ali Sadeghi Aghili

این پروژه تحت مجوز **Apache License 2.0** منتشر شده است. هر fork، port یا redistribition باید فایل [`NOTICE`](NOTICE) را حفظ کند و به نویسنده اصلی credit بدهد. برای جزئیات کامل [`LICENSE`](LICENSE) را ببینید.
