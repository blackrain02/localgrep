# لوکال‌گرپ (LocalGrep / `lg`) ⚡

[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](https://opensource.org/licenses/MIT)
[![Python 3.9+](https://img.shields.io/badge/python-3.9+-blue.svg)](https://www.python.org/downloads/)

[English](README.md) | **فارسی**

> **موتور جستجوی معنایی و هرس کانتکست (Context Pruning) محلی و بدون نیاز به ایندکس برای دستیارهای هوش مصنوعی (Claude Code, Cursor, Antigravity, Aider).**  
> کاهش مصرف توکن ورودی به مدل‌های زبانی تا **۹۰ درصد** در پروژه‌های بزرگ.

---

## صورت مسئله (The Problem)

دستیارهای هوش مصنوعی مدرن حین توسعه و دیباگ کد، حجم عظیمی از توکن‌ها را با بازخوانی کل فایل‌ها هدر می‌دهند:
- باز کردن یک کامپوننت یا کنترلر ۱۰۰۰ خطی برای دیدن یک متد ۱۰ خطی، در هر مرحله بین **۴,۰۰۰ تا ۶,۰۰۰ توکن** می‌سوزاند.
- خروجی دستوراتی مانند `php artisan route:list` یا لاگ‌های حجیم، کانتکست ایجنت را اشباع کرده و باعث **کاهش دقت، هذیان (Hallucination) و اتمام سریع سقف اشتراک** می‌شود.
- پایگاه‌های داده برداری (Vector DBs مانند Chroma یا Qdrant) سنگین هستند و با هر بار تعویض شاخه در گیت، ایندکس آن‌ها باطل شده و نیاز به بازسازی دارند.

## راه‌حل: لوکال‌گرپ (`lg`)

ابزار `lg` یک موتور سبک و ترکیبی است که بدون نیاز به ساخت فایل ایندکس روی سیستم کار می‌کند:
1. **بدون ایندکس و مستقل از شاخه (Zero-Index)**: مستقیماً با هسته پرسرعت `ripgrep` کاندیداها را در کسری از ثانیه پیدا می‌کند.
2. **رتبه‌بندی معنایی زیر ثانیه (Cross-Encoder)**: کاندیداها توسط مدل سبک هوش مصنوعی (`ms-marco-MiniLM-L-6-v2`) روی CPU از طریق دیمن مقیم در رم رتبه‌بندی می‌شوند.
3. **هرس کانتکست (Context Pruner)**: فایل‌های چند هزار خطی را برش داده و دقیقاً همان بلاک ۲۰ سطری مورد نظر را بازمی‌گرداند.

---

## 📊 بنچمارک مقایسه‌ای (کاهش توکن و زمان)

| وظیفه | روش عادی ایجنت (`view_file`) | ابزار سنتی `grep` | لوکال‌گرپ (`lg`) | میزان صرفه‌جویی توکن |
| :--- | :--- | :--- | :--- | :--- |
| بررسی یک متد در فایل ۱۲۰۰ خطی | ۵,۴۰۰ توکن | ۰ توکن (بدون درک لاجیک) | **۱۶۰ توکن** | **~۹۷٪** |
| مکان‌یابی کامپوننت در فرانت‌اند | ۱,۸۰۰ توکن | ۸۵۰ توکن (خروجی خام) | **۱۲۰ توکن** | **~۹۳٪** |
| فیلتر خروجی دستور روت‌ها (۴۰۰ روت) | ۳,۲۰۰ توکن | ۶۰۰ توکن | **۹۰ توکن** | **~۹۷٪** |
| زمان اجرا (Latency) | ۰.۸ تا ۲.۰ ثانیه (شبکه) | ~۱۰ میلی‌ثانیه | **~۳۵۰ میلی‌ثانیه (CPU)** | **زیر ثانیه و آفلاین** |

---

## 🚀 پیش‌نیازها و نصب

### پیش‌نیازها:
- لینوکس یا مک‌او‌اس
- ابزار `ripgrep` (`rg`)
- پایتون ۳.۹ یا بالاتر

### روش ۱: نصب مستقیم از طریق گیت (پیشنهادی)

```bash
# ۱. نصب ripgrep (در صورت عدم وجود)
# اوبونتو / دبیان:
sudo apt install ripgrep
# مک:
brew install ripgrep

# ۲. نصب لوکال‌گرپ با pip
pip install git+https://github.com/blackrain02/localgrep.git
```

### روش ۲: کلون مخزن و نصب دستی (توسعه‌دهندگان)

```bash
git clone https://github.com/blackrain02/localgrep.git
cd localgrep
pip install -e .
```

---

## 🧠 راهنمای دانلود و مدیریت مدل هوش مصنوعی

مدل استفاده‌شده `cross-encoder/ms-marco-MiniLM-L-6-v2` است که **تنها ۸۸ مگابایت** حجم دارد و روی CPU با سرعت بسیار بالا استنتاج می‌شود.

### ۱. دانلود خودکار (ساده‌ترین روش)
نیازی به اقدام دستی نیست؛ با اولین اجرای دستور `lg`، مدل به‌صورت خودکار از HuggingFace دانلود و در مسیر کش استاندارد ذخیره می‌شود:
```bash
lg "test query"
# در اولین اجرا: فایل ۸۸ مگابایتی یکبار دانلود شده و برای همیشه در سیستم ذخیره می‌شود.
```

### ۲. پیش‌دانلود مدل از خط فرمان (اختیاری)
اگر می‌خواهید قبل از شروع کار مدل را دانلود کنید:
```bash
python3 -c "from transformers import AutoTokenizer, AutoModelForSequenceClassification; AutoTokenizer.from_pretrained('cross-encoder/ms-marco-MiniLM-L-6-v2'); AutoModelForSequenceClassification.from_pretrained('cross-encoder/ms-marco-MiniLM-L-6-v2')"
```

### ۳. نصب آفلاین در سیستم‌های بدون اینترنت (Air-gapped)
در صورتی که سیستم دسترسی به اینترنت ندارد:
1. روی یک سیستم متصل به اینترنت، مدل را دانلود کنید.
2. پوشه مدل را از مسیر زیر کپی کنید:
   ```bash
   ~/.cache/huggingface/hub/models--cross-encoder--ms-marco-MiniLM-L-6-v2/
   ```
3. این پوشه را در همان مسیر در سیستم مقصد قرار دهید. `lg` بدون نیاز به اینترنت مستقیماً فایل‌های کش محلی را می‌خواند.

---

## 💡 راهنمای دستورات و نحوه استفاده

### ۱. جستجوی معنایی در کل پروژه
یافتن کامپوننت‌ها، کنترلرها یا متغیرهای کانفیگ بدون حدس زدن مسیر دقیق:
```bash
lg "payment callback gateway"
lg "user profile header dropdown"
```

### ۲. هرس کانتکست فایل‌های حجیم (`lg prune`)
استخراج دقیق یک قطعه کد ۲۰ تا ۳۰ خطی از فایل‌های بزرگ بدون باز کردن کل فایل:
```bash
lg prune resources/config/AdminMenus.ts "accounting inventory"
lg prune app/Services/PaymentService.php "verify callback"
```

### ۳. تقطیر و فیلتر خروجی دستورات ترمینال (Pipe)
پایپ کردن خروجی دستورات طولانی به `lg` برای استخراج فقط سطرهای مهم:
```bash
php artisan route:list | lg "export excel"
git log -n 100 --oneline | lg "stripe webhook fix"
```

### ۴. انتخاب هوشمند فایل‌های تست (`lg test`)
جستجوی مستقیم در پوشه تست‌ها (`tests/`) برای یافتن تست‌های مرتبط با یک قابلیت:
```bash
lg test "deferred props inertia"
lg test "user registration 2fa"
```

### ۵. ردیابی ریشه خطا در استک‌ترس (`lg error`)
تطابق پیام خطا یا متن لاگ با کدهایی که ممکن است استثنا پرتاب کنند:
```bash
lg error "ValidationException: The given data was invalid. price is required"
```

---

## 🛠️ ساختار معماری (Architecture)

```
┌────────────────────────────────────────────────────────┐
│                   AI Coding Assistant                  │
│       (Claude Code / Cursor / Antigravity / Aider)     │
└───────────────────────────┬────────────────────────────┘
                            │ فراخوانی خط فرمان (`lg`)
                            ▼
               ┌─────────────────────────┐
               │    LocalGrep Client     │ (پایتون استاندارد، زمان شروع < ۱۵ میلی‌ثانیه)
               └────────────┬────────────┘
                            │ یونیکس دامین سوکت (/tmp/localgrep.sock)
                            ▼
               ┌─────────────────────────┐
               │    LocalGrep Daemon     │ (مقیم در رم با مدل آماده)
               └──────┬───────────┬──────┘
                      │           │
           فیلتر مسیر │           │ رتبه‌بندی کراس‌انکور
          و ریپ‌گرپ   │           │ (ms-marco-MiniLM-L-6-v2)
                      ▼           ▼
               ┌──────────┐   ┌───────────────┐
               │ Ripgrep  │   │ PyTorch (CPU) │
               └──────────┘   └───────────────┘
```

---

## 🤝 نحوه معرفی و اجبار هوش مصنوعی به استفاده از `lg`

کد زیر را به فایل `AGENTS.md`، `CLAUDE.md` یا `.cursorrules` پروژه خود اضافه کنید:

```markdown
### Code Exploration & Context Pruning

If `lg` is available in PATH, prioritize it to minimize token consumption:
- `lg "<query>"`: Locate code snippets and entry points across codebase without reading full files.
- `lg prune <file> "<query>"`: Extract the exact 20-30 line block from large files (avoids reading whole file into context).
- `<command> | lg "<query>"`: Filter massive CLI dumps (e.g. `php artisan route:list | lg "comment"`).
- `lg test "<query>"`: Pinpoint relevant Pest/PHPUnit tests.
- `lg error "<error>"`: Trace exception/stack trace to probable throwing locations.

Fallback: If `lg` is missing, silently proceed with standard tools.
```

---

## 📄 لایسنس

این نرم‌افزار تحت مجوز متن‌باز [MIT](LICENSE) منتشر شده است.
امتیاز توسعه © ۲۰۲۶ [جواد (blackrain02)](https://github.com/blackrain02).
