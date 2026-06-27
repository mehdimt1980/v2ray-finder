# v2ray-finder

[![PyPI version](https://badge.fury.io/py/v2ray-finder.svg)](https://badge.fury.io/py/v2ray-finder)
[![Python Versions](https://img.shields.io/pypi/pyversions/v2ray-finder.svg)](https://pypi.org/project/v2ray-finder/)
[![License: Apache 2.0](https://img.shields.io/badge/License-Apache%202.0-blue.svg)](https://opensource.org/licenses/Apache-2.0)

**فارسی** | [English](README.en.md) | [Deutsch](README.de.md) | [📋 CHANGELOG](CHANGELOG.md)

---

`v2ray-finder` اپلیکیشن اندروید و موتور runtime پایتونی برای دریافت، حذف تکراری‌ها، اعتبارسنجی، بررسی سلامت، تست واقعی و امتیازدهی کانفیگ‌های V2Ray/Xray از روی یک registry قابل اعتماد است.

کشف سورس دیگر داخل این ریپو انجام نمی‌شود. Source discovery، شکار سورس‌ها، crawling تلگرام/گیت‌هاب، امتیازدهی سورس‌ها و تولید registry در ریپوی جداگانه‌ی [`v2ray-source-hunter`](https://github.com/mehdimt1980/v2ray-source-hunter) انجام می‌شود.

`v2ray-finder` فقط این فایل را مصرف می‌کند:

```text
registry/sources.json
```

و خروجی runtime آن لیستی تمیز از کانفیگ‌هاست:

```text
vmess://
vless://
trojan://
ss://
ssr://
```

---

## نقش هر ریپو

```text
v2ray-source-hunter
→ سورس‌های عمومی را پیدا می‌کند
→ feedهای سورس را validate و score می‌کند
→ خروجی‌های تلگرام را در صورت نیاز به فایل raw تمیز تبدیل می‌کند
→ registry سازگار با اپ را export می‌کند
→ registry/sources.json را به v2ray-finder sync می‌کند

v2ray-finder
→ registry/sources.json را مصرف می‌کند
→ از سورس‌های trusted و enabled کانفیگ می‌گیرد
→ کانفیگ‌ها را deduplicate می‌کند
→ health-check و real-validation انجام می‌دهد
→ کانفیگ‌ها را رتبه‌بندی می‌کند
→ performance سورس‌ها را گزارش می‌دهد
→ APK اندروید را می‌سازد
```

این جداسازی جلوی تداخل دو موتور discovery روی یک registry را می‌گیرد.

---

## ویژگی‌های اصلی

- موتور اصلی پایتون در پکیج `v2ray_finder/`
- pipeline مبتنی بر registry: source registry → fetch → dedup → health → score
- بدون global source discovery داخل این ریپو
- registry قابل اعتماد از طرف `v2ray-source-hunter` sync می‌شود
- دریافت async با `httpx`
- بررسی سلامت TCP و سنجش latency
- Real Validation Engine v2 در Android با `xray`
- چند probe واقعی، confidence score و stability signal
- Source Performance Engine برای رتبه‌بندی سورس‌های trusted که واقعاً کانفیگ مفید می‌دهند
- CLI، Rich CLI و GUI دسکتاپ با PySide6
- اپلیکیشن native اندروید با Chaquopy
- رابط فارسی و راست‌به‌چپ برای کاربران ایران
- ساخت debug APK و signed release APK از طریق GitHub Actions

---

## اپلیکیشن اندروید

مسیر اندروید پروژه بعد از چند مرحله آزمایش بازطراحی شد.

### چه چیزی تغییر کرد؟

نسخه‌ی اول موبایل با Kivy و Buildozer ساخته شد. APK ساخته می‌شد، اما Buildozer فقط `main.pyc` را وارد APK می‌کرد و پکیج اصلی `v2ray_finder` وارد برنامه نمی‌شد. به همین دلیل، مسیر اندروید به معماری مطمئن‌تر منتقل شد:

```text
Native Android UI + Gradle + Chaquopy + real Python package
```

مسیر Buildozer/Kivy دیگر استفاده نمی‌شود.

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
  prepare_android_xray_asset.py     # آماده‌سازی xray و فایل‌های build-time اندروید
  patch_android_validation_ui.py    # patch اختیاری UI برای نمایش confidence/stability
registry/
  sources.json                      # registry trusted که از v2ray-source-hunter sync می‌شود
```

در workflow گیت‌هاب، پکیج اصلی از ریشه پروژه به مسیر زیر کپی می‌شود:

```text
android_app/app/src/main/python/v2ray_finder/
```

بعد Chaquopy فایل bridge، موتور واقعی `Pipeline`، موتور Real Validation v2 و dependencyهای پایتون را داخل APK بسته‌بندی می‌کند.

### امکانات رابط اندروید

- رابط native اندروید
- فارسی و راست‌به‌چپ
- فیلد توکن GitHub برای دریافت runtime در صورت نیاز
- کنترل تعداد نتایج و timeout
- بررسی سلامت TCP، روشن به‌صورت پیش‌فرض
- Real Validation Engine v2 اختیاری با `xray`
- آمار دریافتی / یکتا / سالم / رتبه‌بندی‌شده
- کارت‌های نتیجه با رتبه، پروتکل، کیفیت، امتیاز، latency و source URL
- metadata اعتبارسنجی از bridge: confidence score، confidence level، تعداد probe و stability
- جستجو و فیلتر پروتکل
- صفحه‌بندی نتایج زیاد
- نمایش structured diagnostics برای سورس‌های ناموفق
- بخش Source Performance برای نمایش بهترین سورس‌های trusted بعد از هر scan
- کپی همه کانفیگ‌ها
- کپی تک‌کانفیگ از هر کارت

---

## Source Registry

registry runtime در این مسیر است:

```text
registry/sources.json
```

این فایل توسط `v2ray-source-hunter` تولید و sync می‌شود. `v2ray-finder` دیگر GitHub source discovery، Telegram source discovery، source hunting یا auto-promotion workflow اجرا نمی‌کند.

اسکن پیش‌فرض فقط سورس‌های active و enabled را با این statusها می‌خواند:

```text
official
trusted
```

سورس‌های candidate، experimental، quarantine و disabled به‌صورت پیش‌فرض وارد scan نمی‌شوند.

### Onboarding دستی

ابزار single-source onboarding هنوز برای بررسی دستی یک سورس باقی مانده است:

```bash
python -m v2ray_finder.source_onboarding \
  --url https://example.com/sub.txt \
  --label "Example Source" \
  --tcp-sample-size 50 \
  --json
```

این global discovery نیست. Global discovery فقط در `v2ray-source-hunter` انجام می‌شود.

---

## Real Validation Engine v2 در Android

build اندروید می‌تواند باینری رسمی Android arm64 مربوط به `xray` را هنگام CI دانلود و داخل APK قرار دهد. اپ سپس `xray` را local اجرا می‌کند، یک SOCKS5 port باز می‌کند و بررسی می‌کند آیا کانفیگ انتخاب‌شده واقعاً از طریق آن proxy می‌تواند چند endpoint سبک را باز کند یا نه.

```text
TCP check              → فقط host:port در دسترس است
single Google-204      → یک endpoint از طریق xray کار می‌کند
Real Validation v2     → چند probe + confidence + stability از طریق xray
```

پروب‌های فعلی:

```text
google_204       → clients3.google.com/generate_204
gstatic_204      → connectivitycheck.gstatic.com/generate_204
google_www_204   → www.google.com/generate_204
cloudflare_trace → one.one.one.one/cdn-cgi/trace
```

برای هر کانفیگ این خروجی‌ها ساخته می‌شود:

```text
validation_ok
confidence_score
confidence_level
passed_probes / total_probes
stability_passes / stability_attempts
latency_ms
error diagnostics
```

فرمول confidence فعلی:

```text
50% موفقیت probeها
25% stability
15% latency
10% امتیاز اضافه برای Google-204
```

یک کانفیگ فقط وقتی پذیرفته می‌شود که reachable باشد، حداقل یک stability pass داشته باشد و به حداقل confidence برسد.

جزئیات مهم Android:

- `scripts/prepare_android_xray_asset.py` هنگام build نسخه Android arm64 باینری xray را دانلود می‌کند.
- باینری در مسیر `android_app/app/src/main/jniLibs/arm64-v8a/libxray.so` قرار می‌گیرد.
- build گزینه `doNotStrip "**/libxray.so"` را اضافه می‌کند تا Gradle فایل اجرایی را خراب نکند.
- Activity اندروید از `getApplicationInfo().nativeLibraryDir` برای اجرای باینری bundled استفاده می‌کند.
- کانفیگ probe برای xray عمداً مینیمال است و از `geoip.dat` یا `geosite.dat` استفاده نمی‌کند.
- اپ خطاهای startup مربوط به xray را capture می‌کند و اگر validation fail شود، diagnostics نشان می‌دهد.

---

## Source Performance Engine

Source Performance Engine مشخص می‌کند کدام سورس‌های trusted در یک scan واقعاً مفید بوده‌اند. برای هر source این موارد اندازه‌گیری می‌شود:

```text
fetch status
TCP candidates
TCP OK count
real-validation checked count
real-validation OK count
average latency
best latency
trust
source score
error samples
```

وقتی نتیجه Real Validation v2 موجود باشد، امتیاز سورس بیشتر بر اساس موفقیت validation محاسبه می‌شود:

```text
55% real-validation success rate
20% TCP success rate
15% latency score
10% configured trust
```

اگر real validation فعال نباشد، موتور از TCP، latency و trust استفاده می‌کند. جزئیات بیشتر در [`docs/SOURCE_PERFORMANCE_ENGINE.md`](docs/SOURCE_PERFORMANCE_ENGINE.md) آمده است.

---

## dependencyهای اندروید

در ماژول اندروید این dependencyهای پایتون نصب می‌شوند:

```gradle
install "requests>=2.31.0"
install "httpx>=0.24.0"
```

`httpx` لازم است چون موتور اصلی `Pipeline` برای دریافت async سورس‌ها از آن استفاده می‌کند.

---

## ساخت debug APK با GitHub Actions

1. در GitHub وارد بخش **Actions** شو.
2. workflow با نام **Build Android APK** را انتخاب کن.
3. روی **Run workflow** بزن و branch را روی `main` بگذار.
4. بعد از پایان build، artifact زیر را دانلود کن:

```text
v2ray-finder-chaquopy-debug-apk
```

## ساخت signed release APK با GitHub Actions

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

## ساخت محلی APK

```bash
python scripts/prepare_android_xray_asset.py
python scripts/patch_android_validation_ui.py
gradle -p android_app :app:assembleDebug
```

APK debug در این مسیر ساخته می‌شود:

```text
android_app/app/build/outputs/apk/debug/
```

---

## نصب Python

```bash
pip install v2ray-finder
pip install "v2ray-finder[async]"
pip install "v2ray-finder[all]"
```

از سورس:

```bash
git clone https://github.com/mehdimt1980/v2ray-finder.git
cd v2ray-finder
python -m venv .venv
source .venv/bin/activate
pip install -e ".[all,dev]"
```

---

## Python API

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

GUI دسکتاپ از همان موتور `Pipeline` استفاده می‌کند که CLI و Android bridge استفاده می‌کنند.

---

## ساختار ریپو

```text
v2ray_finder/       # پکیج اصلی Python؛ برای سازگاری Android از src/ به ریشه منتقل شده
android_app/        # اپ native اندروید + Chaquopy
registry/           # registry trusted که runtime مصرف می‌کند
scripts/            # آماده‌سازی xray و ابزارهای build اندروید
src/                # فقط placeholder قدیمی برای سازگاری
docs/               # مستندات build و engine
```

---

## License

Apache License 2.0 © 2026 Ali Sadeghi Aghili

این پروژه تحت **Apache License 2.0** منتشر شده است. هر کار مشتق، port یا بازنشر باید فایل [`NOTICE`](NOTICE) را حفظ کند و نام نویسنده اصلی را ذکر کند. جزئیات در [`LICENSE`](LICENSE) آمده است.
