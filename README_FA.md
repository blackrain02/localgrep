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
2. **استنتاج زیر میلی‌ثانیه با موتور ONNX Runtime**: رتبه‌بندی فوق سریع کراس‌انکور با مدل سبک `ms-marco-MiniLM-L-6-v2` روی CPU (زیر ۱ میلی‌ثانیه به ازای هر جفت کد) با قابلیت فال‌بک خودکار به PyTorch.
3. **هرس هوشمند کانتکست با Tree-sitter AST**: تحلیل ساختار گرامری زبان‌ها (PHP، پایتون، تایپ‌اسکریپت، جاوااسکریپت، گو، راست، جاوا) و استخراج توابع، متدها و کلاس‌های کامل به‌جای برش‌های سطری تصادفی.
4. **سرور بومی پروتکل کانتکست مدل (Native MCP Server)**: اتصال یکپارچه به دستیارهای مدرن (Claude Code، Cursor، Antigravity، Windsurf) از طریق ابزارهای بومی `lg mcp`.

---

## 📊 بنچمارک مقایسه‌ای (کاهش توکن و زمان)

| وظیفه | روش عادی ایجنت (`view_file`) | ابزار سنتی `grep` | لوکال‌گرپ (`lg`) | میزان صرفه‌جویی توکن |
| :--- | :--- | :--- | :--- | :--- |
| بررسی یک متد در فایل ۱۲۰۰ خطی | ۵,۴۰۰ توکن | ۰ توکن (بدون درک لاجیک) | **۱۶۰ توکن (بلاک دقیق AST)** | **~۹۷٪** |
| مکان‌یابی کامپوننت در فرانت‌اند | ۱,۸۰۰ توکن | ۸۵۰ توکن (خروجی خام) | **۱۲۰ توکن** | **~۹۳٪** |
| فیلتر خروجی دستور روت‌ها (۴۰۰ روت) | ۳,۲۰۰ توکن | ۶۰۰ توکن | **۹۰ توکن** | **~۹۷٪** |
| رتبه‌بندی ۲۰ کاندیدا با کراس‌انکور | - | - | **۱۹ میلی‌ثانیه (ONNX CPU)** | **زیر میلی‌ثانیه/جفت** |

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

## 🧠 موتور ONNX و دانلود مدل

مدل مورد استفاده `cross-encoder/ms-marco-MiniLM-L-6-v2` با حجم **~۸۷ مگابایت** است و می‌تواند با **ONNX Runtime** (پیشنهادی برای سرعت زیر میلی‌ثانیه) یا **PyTorch CPU** اجرا شود.

### ۱. دانلود خودکار (ساده‌ترین روش)
نیازی به اقدام دستی نیست؛ با اولین اجرای دستور `lg`، توکنایزر و تنظیمات از HuggingFace دانلود و در کش سیستم ذخیره می‌شود.

### ۲. فعال‌سازی موتور پرسرعت ONNX (زیر میلی‌ثانیه)
برای فعال‌سازی استنتاج سریع ONNX کافی است فایل مدل را خروجی بگیرید:
```bash
python3 -c "
import torch
from transformers import AutoTokenizer, AutoModelForSequenceClassification
model_name = 'cross-encoder/ms-marco-MiniLM-L-6-v2'
tokenizer = AutoTokenizer.from_pretrained(model_name)
model = AutoModelForSequenceClassification.from_pretrained(model_name)
model.eval()

dummy = tokenizer([['test query', 'test snippet']], return_tensors='pt')
torch.onnx.export(
    model,
    (dummy['input_ids'], dummy['attention_mask']),
    '~/.local/localgrep/model.onnx',
    input_names=['input_ids', 'attention_mask'],
    output_names=['logits'],
    dynamic_axes={'input_ids': {0: 'batch', 1: 'seq'}, 'attention_mask': {0: 'batch', 1: 'seq'}, 'logits': {0: 'batch'}},
    opset_version=14
)
print('ONNX model ready at ~/.local/localgrep/model.onnx')
"
```
به محض وجود فایل `model.onnx`، لوکال‌گرپ به‌صورت خودکار موتور ONNX را لود کرده و زمان پردازش را به ۰.۹ میلی‌ثانیه کاهش می‌دهد.

### ۳. نصب آفلاین در سیستم‌های بدون اینترنت (Air-gapped)
در صورتی که سیستم مقصد دسترسی به اینترنت ندارد:
1. فایل `model.onnx` را در مسیر `~/.local/localgrep/model.onnx` کپی کنید.
2. پوشه مدل کش هوگینگ‌فیس را منتقل کنید:
   ```bash
   ~/.cache/huggingface/hub/models--cross-encoder--ms-marco-MiniLM-L-6-v2/
   ```
`lg` بدون ارسال درخواست به اینترنت، کاملاً آفلاین اجرا می‌شود.

---

## 💡 راهنمای دستورات و نحوه استفاده

### ۱. جستجوی معنایی در کل پروژه
یافتن کامپوننت‌ها، کنترلرها یا متغیرهای کانفیگ بدون حدس زدن مسیر دقیق:
```bash
lg "payment callback gateway"
lg "user profile header dropdown"
```

### ۲. هرس هوشمند کانتکست با Tree-sitter AST (`lg prune`)
استخراج دقیق کل تابع، متد یا کلاس از فایل‌های بزرگ بر اساس ساختار نحوی کد (نه خطوط تصادفی):
```bash
lg prune resources/config/AdminMenus.ts "accounting inventory"
lg prune app/Models/User.php "avatar"
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

### ۶. پیشنهاددهنده هوشمند اسکیل‌های کلود و آنتی‌گراویتی (`lg skill`)
تطبیق هوشمند هر نیاز یا پرامپت با اسکیل‌های نصب‌شده روی سیستم (`.agents/skills/`, `.claude/skills/`):
```bash
lg skill "setup 2fa authentication"
lg skill "slow database query profiling and duplicate N+1 queries"
lg skill "YAGNI simplify code and remove bloat"
```

---

## 🔌 سرور پروتکل کانتکست مدل (MCP Server)

لوکال‌گرپ دارای یک سرور بومی **Model Context Protocol (MCP)** است که به دستیارهای هوش مصنوعی اجازه می‌دهد مستقیماً از طریق ابزار به این قابلیت‌ها دسترسی داشته باشند.

### اجرای سرور MCP
```bash
lg mcp
```

### تنظیم در کلاینت‌های هوش مصنوعی (`.mcp.json`):
```json
{
  "mcpServers": {
    "localgrep": {
      "command": "lg",
      "args": ["mcp"]
    }
  }
}
```

#### ابزارهای در دسترس در MCP:
- **`localgrep_search`**: جستجوی معنایی پرسرعت در سراسر سورس‌کد و ماژول‌ها.
- **`localgrep_prune`**: هرس هوشمند کانتکست بر اساس AST زبان‌ها برای خواندن فقط تابع مربوطه.
- **`localgrep_skill`**: انتخاب هوشمند اسکیل مناسب برای هر تسک برنامه‌نویسی.
- **`localgrep_test`**: کشف و انتخاب هوشمند تست‌های مربوط به یک باگ یا ویژگی.
- **`localgrep_error`**: ردیابی ریشه خطاهای رخ‌داده در برنامه و ارجاع به کد مبدا.

---

## 🛠️ ساختار معماری (Architecture)

```
┌────────────────────────────────────────────────────────┐
│                   AI Coding Assistant                  │
│       (Claude Code / Cursor / Antigravity / Aider)     │
└──────────────┬──────────────────────────┬──────────────┘
               │ خط فرمان (`lg`)          │ پروتکل MCP (stdio)
               ▼                          ▼
┌─────────────────────────┐    ┌─────────────────────────┐
│    LocalGrep Client     │    │   LocalGrep MCP Server  │
└──────────────┬──────────┘    └──────────┬──────────────┘
               │                          │
               └────────────┬─────────────┘
                            │ یونیکس دامین سوکت (/tmp/localgrep.sock)
                            ▼
               ┌─────────────────────────┐
               │    LocalGrep Daemon     │ (مقیم در حافظه با مدل آماده)
               └──────┬───────────┬──────┘
                      │           │
           فیلتر مسیر │           ├── هرس نحوی AST (PHP, Py, JS, TS, Go, Rust)
          و ریپ‌گرپ   │           │
                      │           └── موتور ONNX Runtime (زیر ۱ میلی‌ثانیه/جفت)
                      ▼
               ┌──────────┐
               │ Ripgrep  │
               └──────────┘
```

دیمن با اولین فراخوانی روشن شده و مدل در رم مقیم می‌ماند. اجرای کوئری‌ها پس از گرم‌شدن تنها بین **۲۰ تا ۳۰۰ میلی‌ثانیه** زمان می‌برد.

---

## 🤝 نحوه معرفی و اجبار هوش مصنوعی به استفاده از `lg`

کد زیر را به فایل `AGENTS.md`، `CLAUDE.md` یا `.cursorrules` پروژه خود اضافه کنید:

```markdown
### Code Exploration & Context Pruning (Priority & Accelerator)

> **Safe Host Directive:**
> 1. `lg` is an optional local CLI accelerator. **Never assume it exists globally and NEVER attempt to install it.**
> 2. **Priority 1 (When `lg` exists in PATH):** ALWAYS use `lg` first via terminal for code discovery, large file reading, and CLI filtering before reading full files. It reduces token consumption by up to 90%.
> 3. **English Query Directive:** ALWAYS formulate `lg` queries in **English using Latin characters** (e.g. `lg "payment callback"` NEVER `lg "درگاه پرداخت"`). If the user asks in Persian, translate the conceptual intent into English keywords before invoking `lg`.
> 4. **Fallback Rule (When `lg` is missing / exit code 127):** Silently and immediately fallback to standard tools (`Semble RAG`, `rg`, `grep`, `view_file`) without raising errors, failing tasks, or prompting the user.

**Commands:**
- `lg "<query>"`: Locate code snippets and entry points across codebase without reading full files (ALWAYS English).
- `lg prune <file> "<query>"`: Extract the exact AST function or block from large files (avoids reading whole file into context).
- `<command> | lg "<query>"`: Filter massive CLI dumps (e.g. `php artisan route:list | lg "comment"`).
- `lg test "<query>"`: Pinpoint relevant Pest/PHPUnit tests.
- `lg error "<error>"`: Trace exception/stack trace to probable throwing locations.
- `lg skill "<task/intent>"`: Match any task or prompt to the most relevant installed Claude / Antigravity skill.
```

---

## 📄 لایسنس

این نرم‌افزار تحت مجوز متن‌باز [MIT](LICENSE) منتشر شده است.
امتیاز توسعه © ۲۰۲۶ [جواد (blackrain02)](https://github.com/blackrain02).

