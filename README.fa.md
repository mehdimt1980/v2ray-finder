# v2ray-finder

[![PyPI version](https://badge.fury.io/py/v2ray-finder.svg)](https://badge.fury.io/py/v2ray-finder)
[![Python Versions](https://img.shields.io/pypi/pyversions/v2ray-finder.svg)](https://pypi.org/project/v2ray-finder/)
[![License: Apache 2.0](https://img.shields.io/badge/License-Apache%202.0-blue.svg)](https://opensource.org/licenses/Apache-2.0)

**فارسی** | [English](README.en.md) | [Deutsch](README.de.md) | [📋 CHANGELOG](CHANGELOG.md)

---

`v2ray-finder` ابزاری سریع برای دریافت، جمع‌آوری، حذف موارد تکراری، اعتبارسنجی، بررسی سلامت، تست واقعی و امتیازدهی کانفیگ‌های عمومی V2Ray/Xray از GitHub و منابع subscription انتخاب‌شده است.

خروجی ابزار، لیستی تمیز از لینک‌های زیر است:

```text
vmess://
vless://
trojan://
ss://
ssr://
```

این پروژه حالا علاوه بر موتور پایتونی، یک اپلیکیشن native اندروید قابل نصب هم دارد.

---

## ویژگی‌های اصلی

- موتور اصلی پایتون در پکیج `v2ray_finder/`
- زنجیره کامل Pipeline: کشف منبع → دریافت → حذف تکراری‌ها → بررسی سلامت → امتیازدهی
- دریافت async با `httpx`
- بررسی سلامت TCP و سنجش latency
- تست واقعی اختیاری با `xray` + Google-204 در Android
- Source Performance Engine برای رتبه‌بندی منابعی که واقعاً کانفیگ مفید تولید می‌کنند
- CLI، Rich CLI و GUI دسکتاپ با PySide6
- اپلیکیشن native اندروید با Chaquopy
- رابط فارسی و راست‌به‌چپ برای کاربران ایران
- ساخت debug APK و signed release APK از طریق GitHub Actions

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
    src/main/java/org/mehdimt/v2rayfinder/DefaultHealthActivity.java
    src/main/python/android_bridge.py
scripts/
  prepare_android_xray_asset.py     # آماده‌سازی xray و patchهای build-time اندروید
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
- بررسی سلامت TCP، روشن به‌صورت پیش‌فرض
- تست واقعی اختیاری با `xray` / Google-204: کندتر، اما بسیار دقیق‌تر
- آمار دریافتی / یکتا / سالم / رتبه‌بندی‌شده
- کارت‌های نتیجه با رتبه، پروتکل، کیفیت، امتیاز، تاخیر و منبع
- جستجو و فیلتر پروتکل
- صفحه‌بندی نتایج زیاد
- نمایش structured diagnostics برای منابع ناموفق
- بخش «منابع مؤثر» برای نمایش بهترین sourceها بعد از هر اسکن
- کپی همه کانفیگ‌ها
- کپی تک‌کانفیگ از هر کارت

### تست واقعی xray / Google-204 در Android

build اندروید می‌تواند باینری رسمی Android arm64 مربوط به `xray` را هنگام CI دانلود و داخل APK قرار دهد. اپ سپس `xray` را به‌صورت local اجرا می‌کند، یک SOCKS5 port باز می‌کند و بررسی می‌کند آیا کانفیگ انتخاب‌شده واقعاً از طریق آن proxy می‌تواند به Google-204 وصل شود یا نه.

این با تست TCP فرق دارد:

```text
TCP check         → فقط host:port در دسترس است
xray / Google-204 → کانفیگ واقعاً از طریق xray کار می‌کند
```

جزئیات مهم پیاده‌سازی Android:

- `scripts/prepare_android_xray_asset.py` هنگام build، نسخه Android arm64 باینری xray را دانلود می‌کند.
- باینری در مسیر `android_app/app/src/main/jniLibs/arm64-v8a/libxray.so` قرار می‌گیرد.
- build گزینه `doNotStrip "**/libxray.so"` را اضافه می‌کند تا Gradle فایل اجرایی را خراب نکند.
- Activity اندروید از `getApplicationInfo().nativeLibraryDir` برای اجرای باینری bundled استفاده می‌کند.
- کانفیگ probe برای xray عمداً مینیمال است و از `geoip.dat` یا `geosite.dat` استفاده نمی‌کند، چون این فایل‌ها داخل APK بسته‌بندی نشده‌اند.
- اپ خطاهای startup مربوط به xray را capture می‌کند و اگر تست واقعی fail شود، diagnostics نشان می‌دهد.

### Source Performance Engine

Source Performance Engine مشخص می‌کند کدام منابع واقعاً در یک اسکن مفید بوده‌اند. این موتور برای هر source این موارد را اندازه‌گیری می‌کند:

```text
وضعیت دریافت منبع
تعداد candidateهای TCP
تعداد TCP OK
تعداد xray checked
تعداد xray OK
میانگین latency
بهترین latency
trust
source score
نمونه خطاها
```

وقتی نتیجه تست واقعی xray موجود باشد، امتیاز منبع بیشتر بر اساس موفقیت واقعی xray محاسبه می‌شود:

```text
55% نرخ موفقیت xray
20% نرخ موفقیت TCP
15% امتیاز latency
10% trust تنظیم‌شده
```

اگر xray فعال نباشد، موتور از TCP، latency و trust استفاده می‌کند. جزئیات بیشتر در [`docs/SOURCE_PERFORMANCE_ENGINE.md`](docs/SOURCE_PERFORMANCE_ENGINE.md) آمده است.

### dependencyهای اندروید

در ماژول اندروید این dependencyهای پایتون نصب می‌شوند:

```gradle
install "requests>=2.31.0"
install "httpx>=0.24.0"
```

`httpx` لازم است چون موتور اصلی `Pipeline` برای دریافت async منابع از آن استفاده می‌کند.

### ساخت debug APK با GitHub Actions

1. در GitHub وارد بخش **Actions** شو.
2. workflow با نام **Build Android APK** را انتخاب کن.
3. روی **Run workflow** بزن و branch را روی `main` بگذار.
4. بعد از پایان build، artifact زیر را دانلود کن:

```text
v2ray-finder-chaquopy-debug-apk
```

### ساخت signed release APK با GitHub Actions

برای ساخت APK قابل نصب و signed از workflow زیر استفاده کن:

```text
Build Signed Android Release APK
version_name: 1.0.10
create_github_release: true
```

secretهای لازم repository:

```text
ANDROID_KEYSTORE_BASE64
ANDROID_KEYSTORE_PASSWORD
ANDROID_KEY_ALIAS
ANDROID_KEY_PASSWORD
```

### ساخت محلی APK

برای build محلی، اگر تست واقعی xray را می‌خواهی، اول xray را stage کن:

```bash
python scripts/prepare_android_xray_asset.py
gradle -p android_app :app:assembleDebug
```

APK در این مسیر ساخته می‌شود:

```text
android_app/app/build/outputs/apk/debug/
```

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
scripts/            # ابزارهای آماده‌سازی xray و build اندروید
src/                # فقط placeholder برای سازگاری با workflowهای قدیمی
docs/               # یادداشت‌های build و مستندات موتور
```

---

## مجوز

Apache License 2.0 © 2026 Ali Sadeghi Aghili

این پروژه تحت مجوز **Apache License 2.0** منتشر شده است. هر fork، port یا redistribition باید فایل [`NOTICE`](NOTICE) را حفظ کند و به نویسنده اصلی credit بدهد. برای جزئیات کامل [`LICENSE`](LICENSE) را ببینید.
