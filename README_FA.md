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

```

### ۷. استخراج سریع قرارداد کامپوننت و کلاس (`lg contract`)
استخراج رابط عمومی (Public API) کامپوننت‌های Vue (مانند props، emits، slots و مدل‌ها)، متدهای عمومی کلاس‌های PHP و اینترفیس‌های تایپ‌اسکریپت زیر ۱۰ میلی‌ثانیه بدون خواندن متن فایل:
```bash
lg contract resources/js/Components/UI/Card.vue
lg contract app/Models/User.php
lg contract resources/js/Components/Header.vue --full
```

### ۸. نگاشت فوری روت به متد کنترلر و ویو (`lg route`)
نگاشت سریع URLها، نام روت‌ها یا کنترلرها به شماره سطر دقیق در `routes/*.php` و صفحه فرانت‌اند Inertia در کمتر از ۱۵ میلی‌ثانیه:
```bash
lg route "xhr.taxes"
lg route "accounts.index"
lg route "GET /orders"
```

### ۹. کارت توپولوژی آنی و فوق فشرده پروژه (`lg topo`)
تولید خلاصه اجرایی ۱۵۰ توکنی از نسخه فریم‌ورک، PHP، پکیج‌های ماژولار، وضعیت دیتابیس و صف‌ها:
```bash
lg topo
lg topo --json
```

### ۱۰. ره‌گیری محل‌های فراخوانی و ارجاعات (`lg callers`)
یافتن فراخوانی‌های واقعی متدها یا کلاس‌ها در سراسر PHP و Vue/TS با حذف تعاریف و کامنت‌ها:
```bash
lg callers wasChanged
lg callers forceSyncPush
```

### ۱۱. نقشه معماری رویدادها و لیسنرها (`lg event-map`)
نگاشت Eventها به Listenerها و تشخیص خودکار صف‌ها (`ShouldQueue`) و جاب‌های مرتبط:
```bash
lg event-map
lg event-map Order
```

### ۱۲. استخراج اسکیما و روابط مدل‌های دیتابیس (`lg schema`)
بررسی ستون‌ها، تایپ‌ها، کست‌ها و روابط Eloquent بدون نیاز به اتصال دیتابیس یا اجرای تینکر:
```bash
lg schema Order
lg schema User --json
```

### ۱۳. اسکلت‌سازی فایل برای ادیت با کاهش ۹۰ درصدی توکن (`lg slice`)
تولید اسکلت فشرده فایل‌های بزرگ حول متد هدف (حفظ ایمپورت‌ها و متغیرها و خلاصه کردن سایر متدها به تک‌خط):
```bash
lg slice app/Http/Controllers/OrderController.php "store"
lg slice resources/js/Components/ProductCard.vue "handleAddToCart"
```

### ۱۴. اعتبارسنجی سریع پیش از تغییر (`lg lint-fast`)
بررسی سینتکس کد، کلاس‌های ایمپورت‌نشده PHP و تعادل تگ‌های Vue زیر ۲۰ میلی‌ثانیه:
```bash
lg lint-fast app/Services/PaymentService.php
lg lint-fast resources/js/Components/Header.vue
```

### ۱۵. انتخاب و اجرای ایزوله تست‌های مرتبط (`lg test-map`)
نگاشت خودکار هر فایل سورس به آزمون‌های متناظر Pest/PHPUnit و اجرای اختصاصی خطاها:
```bash
lg test-map app/Services/InvoiceService.php
lg test-map app/Services/InvoiceService.php --run
```

### ۱۶. مشاهده نمونه رکورد واقعی دیتابیس بدون کوئری (`lg sample`)
استخراج مستقیم یک نمونه رکورد واقعی از سوکت دیتابیس محلی زیر ۵ میلی‌ثانیه با ماسک کردن اطلاعات حساس:
```bash
lg sample Order
lg sample users
```

### ۱۷. محاسبه شعاع تخریب ریفکتور (`lg impact`)
محاسبه وابستگی‌ها و ارزیابی ریسک تغییر یک کلاس، متد یا کامپوننت روی کنترلرها، ویوها و تست‌ها:
```bash
lg impact PaymentGatewayInterface
lg impact app/Services/CartService.php
```

### ۱۸. پالایش لاگ‌های خطا و بایندرهای SQL در (`lg error-decode`)
تقطیر لاگ‌های چندصدخطی لاراول به فریم اصلی برنامه همراه با کوئری کامل و قطعه‌کد خطا:
```bash
lg error-decode storage/logs/laravel.log
cat error.txt | lg error-decode
```

### ۱۹. بازرسی جامع متغیرهای محیطی و دیتابیس (`lg env-audit`)
تطبیق کلیدهای `.env` با رفرنس‌های `config/*.php` و جداول دیتابیس برای کشف جداول مایگریت‌نشده زیر ۱۵ میلی‌ثانیه:
```bash
lg env-audit
```

### ۲۰. گراف وابستگی واکنش‌پذیری فرانت‌اند (`lg state-map`)
ترسیم گراف جریان متغیرها در اسکریپت کامپوننت‌های Vue 3 (`[prop] -> [computed] -> [watch] -> [emit]`):
```bash
lg state-map resources/js/Components/CartDrawer.vue
```

### ۲۱. ترکیب قرارداد کامل API در (`lg api-shape`)
خلاصه یکپارچه روت، متد کنترلر، قوانین اعتبارسنجی، ریسورس و صفحه فرانت‌اند در کمتر از ۲۵ میلی‌ثانیه:
```bash
lg api-shape "orders.store"
```

### ۲۲. پیش‌اعتبارسنجی بلاک جایگزینی (`lg verify-patch`)
محاسبه دقیق شماره سطرهای StartLine/EndLine و رفع عدم تطابق فاصله/تب قبل از ویرایش فایل:
```bash
lg verify-patch app/Services/PaymentService.php "public function verify()"
```

### ۲۳. بازرسی تغییرات پیش از کامیت (`lg audit-diff`)
کشف خودکار توابع دیباگ جا مانده (`dd`, `dump`, `console.log`) و لکنت‌های امنیتی قبل از کامیت:
```bash
lg audit-diff
lg audit-diff --staged
```

### ۲۴. ایزوله‌سازی خطاهای تست (`lg test-isolate`)
حذف ۹۵ درصد خطوط اضافی وندور در خروجی تست‌ها و نمایش خط اصلی تست شکست‌خورده:
```bash
lg test-isolate php artisan test --compact
```

### ۲۵. خروجی ساختاریافته برای ایجنت‌ها (`--json`)
امکان دریافت خروجی کاملاً ساختاریافته با افزودن فلگ `--json` به تمامی دستورات.

### ۲۶. مدیریت دیمن مقیم و رم (`lg status`, `lg stop`)
```bash
lg status
lg stop
```

---

## ⚡ راه‌اندازی دیمن دائمی در پس‌زمینه (Zero Cold-Start با Systemd)

برای از بین بردن تاخیر لود پایتون و مدل، لوکال‌گرپ به صورت سرویس پس‌زمینه کاربر (`systemd --user`) اجرا می‌شود تا دستورات در ۵ تا ۵۰ میلی‌ثانیه اجرا شوند.

### ۱. ایجاد فایل سرویس
فایل `~/.config/systemd/user/localgrep.service` را با این محتوا بسازید:
```ini
[Unit]
Description=LocalGrep Daemon (Fast AST & Semantic Search)
After=default.target

[Service]
Type=simple
ExecStart=%h/.local/localgrep/venv/bin/python %h/.local/localgrep/daemon.py
Restart=always
RestartSec=2
Environment=PYTHONUNBUFFERED=1
Environment=TOKENIZERS_PARALLELISM=false
Nice=-5

[Install]
WantedBy=default.target
```

### ۲. فعال‌سازی و استارت
```bash
systemctl --user daemon-reload
systemctl --user enable --now localgrep.service
```

---

## 🔌 تنظیم سرور پروتکل کانتکست مدل (MCP Server)

لوکال‌گرپ تمامی ابزارهای خود را از طریق دستور `lg mcp` روی پروتکل استاندارد MCP ارائه می‌دهد تا ایجنت‌ها بدون اجرای دستور شل به آن‌ها دسترسی مستقیم داشته باشند.

### ۱. پیکربندی کلاینت‌ها

#### الف. در Claude Code (`~/.claude.json`):
```json
{
  "mcpServers": {
    "localgrep": {
      "command": "lg",
      "args": ["mcp"],
      "type": "stdio"
    }
  }
}
```

#### ب. در Antigravity / Gemini CLI (`~/.gemini/settings.json`):
```json
{
  "mcpServers": {
    "localgrep": {
      "command": "lg",
      "args": ["mcp"],
      "type": "stdio"
    }
  }
}
```

#### ج. در Cursor / Windsurf (`.mcp.json`):
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

### ۲. فهرست کامل ابزارهای MCP
- **`localgrep_search`**: جستجوی معنایی بدون ایندکس زیر ۱۰۰ میلی‌ثانیه.
- **`localgrep_contract`**: استخراج قرارداد و سیگنچر کامپوننت و کلاس.
- **`localgrep_slice`**: اسکلت‌سازی فایل با کاهش ۹۰ درصدی مصرف توکن.
- **`localgrep_prune`**: هرس هوشمند کد بر اساس گرامر AST.
- **`localgrep_lint_fast`**: اعتبارسنجی سریع سینتکس و کلاس‌های گم‌شده.
- **`localgrep_test_map`**: نگاشت فایل‌های پروژه به آزمون‌های متناظر.
- **`localgrep_sample`**: مشاهده داده‌های واقعی دیتابیس زیر ۵ میلی‌ثانیه.
- **`localgrep_impact`**: محاسبه شعاع تخریب تغییرات و سطح ریسک.
- **`localgrep_error_decode`**: تقطیر لاگ خطا و کوئری SQL.
- **`localgrep_env_audit`**: بازرسی جامع متغیرهای محیطی.
- **`localgrep_state_map`**: استخراج گراف واکنش‌پذیری کامپوننت‌های فرانت‌اند.
- **`localgrep_api_shape`**: ترکیب قرارداد کامل API فول‌استک.
- **`localgrep_route`**: نگاشت آنی آدرس و نام روت به متد و ویو.
- **`localgrep_schema`**: استخراج اسکیما و روابط مدل‌های دیتابیس.
- **`localgrep_callers`**: ره‌گیری فراخوانی‌ها در سطح سورس‌کد.
- **`localgrep_event_map`**: نقشه اتصال رویدادها، لیسنرها و جاب‌ها.
- **`localgrep_test`**: مکان‌یابی تست‌های مربوط به هر ویژگی.
- **`localgrep_error`**: ردیابی ریشه خطا در کد برنامه.
- **`localgrep_skill`**: پیشنهاددهنده هوشمند اسکیل به ایجنت.

---

## 🤝 نحوه هدایت هوش مصنوعی بدون ایجاد تداخل برای سایر همکاران

برای اینکه در مخازن تیمی مشترک، ایجنت افراد فاقد `lg` دچار خطا نشود، این ساختار شرطی ایمن را در فایل‌های `AGENTS.md`، `CLAUDE.md` یا `.cursorrules` قرار دهید:

```markdown
### Code Exploration, Context Pruning & Agent Accelerator (`lg` v0.8.0)

> **PRE-CONDITION & MACHINE ENVIRONMENT DETECTION:**
> - Check `which lg 2>/dev/null` at session start.
> - **IF EXIT CODE IS 0 (`lg` is INSTALLED on this machine):**
>   1. **STRICT PROHIBITION:** Calling `view_file` on files >150 lines without prior `lg contract <file>` or `lg slice <file> "<symbol>"` is STRICTLY FORBIDDEN.
>   2. **STRICT PROHIBITION:** Using `rg` or `grep` for code discovery, exploration, or symbol search is STRICTLY FORBIDDEN. Always invoke `lg "<query>"` (<100ms) or `mcp__localgrep__search`.
>   3. **STRICT PROHIBITION:** Calling `php artisan route:list` or grepping `routes/` is STRICTLY FORBIDDEN. Always run `lg route "<query>"` (<15ms).
>   4. **Pre-Flight Fast Linting:** Run `lg lint-fast <file>` after editing PHP or Vue SFCs for instant (<20ms) syntax checking and unimported class detection before running heavier tests.
>   5. **Skeletonized File Editing (Token Pruning):** NEVER read full 300+ line files when modifying a specific method/function. Run `lg slice <file> "<symbol>"` to keep imports, class properties/refs, and only the target method body while stubbing all siblings (85-92% token savings).
>   6. **Full-Stack API Contract Synthesis:** Run `lg api-shape <route|controller@method>` (<25ms) to synthesize complete end-to-end contracts: Route URI, Controller action, FormRequest validation rules, Eloquent Resource schema, and Inertia Vue page.
>   7. **Database Schema & Runtime Peeking:** Run `lg schema <Model>` for offline table schema, casts, and relations. Run `lg sample <Model|table>` to peek 1 runtime DB record directly from the database socket (<5ms) with credentials redacted—NEVER run slow custom Tinker scripts or manual SQL queries.
>   8. **Targeted Test Mapping & Execution:** Run `lg test-map <file> [--run]` to locate relevant Pest/PHPUnit tests for any source file (core and `vendor/bina/*`) and isolate failures without full test suite overhead.
>   9. **Blast Radius & Refactoring Safety:** Before modifying shared classes, interfaces, or composables, run `lg impact <symbol|file>` to compute downstream blast radius across Vue bindings, controllers, services, routes, and tests with risk level (LOW/MED/HIGH).
>   10. **Error & Stack Trace Distillation:** Distill massive 100+ line Laravel stack traces or query errors using `lg error-decode [log|stdin]` to extract the innermost application frame, inlined SQL query bindings, and 5-line local code snippet.
>   11. **Config & Environment Integrity:** Run `lg env-audit` (<15ms) to reconcile `.env` keys against `config/*.php` references and live DB tables to catch missing variables, unmigrated tables, or production leaks.
>   12. **Frontend Reactive Flow (DAG):** Run `lg state-map <component.vue>` to extract an ASCII reactive dependency graph (`[prop] -> [computed] -> [watch] -> [emit]`) from complex Vue components without reading hundreds of lines of script setup.
>   13. **Topology at Boot:** Run `lg topo` (<15ms) at the start of a session instead of reading multiple architecture documents.
>   14. **Edit Pre-Validation (Zero-Failure Rule):** ALWAYS run `lg verify-patch <file> "<search_block>"` BEFORE calling `replace_file_content`. It calculates exact `StartLine`/`EndLine`, detects indentation/tab discrepancies, and auto-resolves whitespace to eliminate tool failure.
>   15. **Pre-Commit Diff Audit:** Run `lg audit-diff` before committing or finalizing changes to catch leftover debug calls (`dd`, `dump`, `console.log`), temporary markers, secrets, and syntax errors.
>   16. **Test Failure Distillation:** Run tests via `lg test-isolate <cmd...>` or pipe test outputs `<cmd> | lg test-isolate` to strip 95% of vendor stack traces, extracting only the failing test, app frame, and code snippet.
>   17. **Call-Site & Event Tracking:** Use `lg callers <symbol>` for actual code invocations (filtering definitions/comments) and `lg event-map [<filter>]` for Laravel Event->Listener->Queue->Job mapping.
>   18. **English Query Directive:** ALWAYS formulate semantic queries in **English using Latin characters** (e.g. `lg "payment callback"` NEVER `lg "درگاه پرداخت"`).
> - **IF EXIT CODE IS 127 (`lg` is ABSENT on colleague's machine):**
>   Silently fall back to standard tools (Semble RAG, `rg`, `grep`, `view_file`) without halting execution or throwing errors.

**Authoritative Commands Matrix (`lg` v0.8.0):**
- `lg "<query>" [--json]`: Zero-index semantic codebase search across core & `vendor/bina/*` in <100ms.
- `lg contract <file> [--full] [--json]`: Instant extraction of Vue props/emits, PHP public methods & TS interfaces (<10ms). Pass `--full` to inspect reactive state, lifecycle hooks, watchers, traits, and protected arrays without over-pruning.
- `lg slice <file> "<symbol>" [--json]`: Skeletonize file, preserving imports/props and target method while collapsing siblings (85-92% token savings).
- `lg prune <file> "<query>" [--json]`: Extract targeted AST function/method from large files without reading full file.
- `lg lint-fast <file> [--json]`: Sub-20ms pre-flight validation (syntax, unimported classes, Vue template tag balance).
- `lg test-map <file> [--run] [--json]`: Map source file to Pest/PHPUnit test files; optionally execute and isolate failures.
- `lg sample <Model|table> [--json]`: Peek 1 runtime DB record via PostgreSQL socket (<5ms) with credential redaction.
- `lg impact <symbol|file> [--json]`: Calculate downstream blast radius across Vue, Controllers, Services, and tests with risk level.
- `lg error-decode [log|stdin] [--json]`: Distill 100+ line Laravel error log/stack trace into innermost app frame with inlined SQL.
- `lg env-audit [--json]`: Audit `.env` variables against `config/*.php` references and live DB tables (<15ms).
- `lg state-map <component.vue> [--json]`: ASCII reactive DAG tracing causal flows (`[prop] -> [computed] -> [watch] -> [emit]`).
- `lg api-shape <route|controller@method> [--json]`: Synthesize full-stack contract (Route + Request rules + Resource schema + Vue view).
- `lg route "<query>" [--json]`: Map URLs/names to controller methods and Inertia Vue pages (`resources/js/Pages/*.vue`) in <15ms.
- `lg topo [--json]`: Executive topology card (PHP, Laravel, Vue, modules, database, queue, entrypoints) in <12ms.
- `lg callers <symbol> [--json]`: Deterministic call-site tracker across PHP & Vue/TS, excluding definitions & docblocks.
- `lg event-map [<filter>] [--json]`: Full event-listener architecture map with sync vs queue dispatch details.
- `lg schema <Model> [--json]`: Synthesized offline database table schema, columns, casts, and Eloquent relations (<20ms).
- `lg verify-patch <file> [target] [--json]`: Pre-validate edit block, check uniqueness, resolve `StartLine`/`EndLine`, fix tab/space mismatches.
- `lg audit-diff [--staged] [--file <f>] [--json]`: Pre-commit git diff auditor for `dd()`, `dump()`, `console.log()`, secrets, and PHP lints.
- `lg test-isolate <cmd...> [--json]`: Run test command & distill failure noise to exact app frame and snippet.
- `<cmd> | lg "<query>"`: Filter and distill massive CLI dumps via pipeline.
- `lg test "<query>"`: Pinpoint relevant Pest/PHPUnit tests.
- `lg error "<error>"`: Trace exception or stack trace to probable source file line.
- `lg skill "<task/intent>"`: Semantic skill recommender for Claude / Antigravity (<25ms).
- `lg status` / `lg stop`: Inspect daemon health, ONNX session, and memory RSS or stop daemon.
```

---

## 📚 مستندات تکمیلی و بنچمارک‌ها

- [**مقایسه جامع LocalGrep با smgrep و بررسی مدل‌ها**](COMPARISON_AND_UPGRADE.md): بررسی تفاوت ساختاری با smgrep، شتاب‌دهنده ONNX و تحلیل نیاز به مدل‌های بزرگ‌تر.
- [**بنچمارک عملی: لوکال‌گرپ (ONNX) در برابر Ollama Qwen3**](MODEL_BENCHMARK_OLLAMA_QWEN3.md): تست تجربی سرعت ۱۹ میلی‌ثانیه‌ای در برابر تاخیر ۲.۵ ثانیه‌ای اولاما در پروژه‌های واقعی.
- [**معماری بارگذاری تنبل اسکیل‌ها (JIT Skills)**](JIT_SKILL_ROUTING_PROPOSAL.md): راهنمای کاهش ۹۶ درصدی توکن‌های هرز و لود خودکار مهارت‌ها با دستور `lg skill` و اسلش‌کامند `/s`.

---

## 📄 لایسنس

این نرم‌افزار تحت مجوز متن‌باز [MIT](LICENSE) منتشر شده است.
امتیاز توسعه © ۲۰۲۶ [جواد (blackrain02)](https://github.com/blackrain02).
