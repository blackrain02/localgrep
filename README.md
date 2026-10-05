# LocalGrep (`lg`) ⚡

[![License: MIT](https://img.shields.io/badge/License-MIT-blue.svg)](https://opensource.org/licenses/MIT)
[![Python 3.9+](https://img.shields.io/badge/python-3.9+-blue.svg)](https://www.python.org/downloads/)

**English** | [فارسی](README_FA.md)

> **Fast, index-free local semantic search & context pruner for AI coding agents (Claude Code, Cursor, Antigravity, Aider).**  
> Slashes LLM input token consumption by up to **90%** on large codebases.

---

## The Problem

Modern AI coding agents (Claude, Gemini, GPT-4) waste millions of tokens doing brute-force file reads:
- Reading a 1,000-line controller or Vue component to inspect a 10-line function consumes **~4,000 to 6,000 tokens** per turn.
- Dumping `php artisan route:list` or test output fills the agent's context window with irrelevant noise, leading to **context dilution, hallucinations, and rapid token quota exhaustion**.
- Traditional Vector DBs (Chroma, Qdrant, LanceDB) require heavyweight indexers that break every time you switch git branches or pull changes.

## The Solution: LocalGrep (`lg`)

`lg` is an index-free hybrid retrieval engine designed specifically for developer workstations and AI coding assistants:
1. **Zero-Index / Branch Agnostic**: Runs directly against working tree files using `ripgrep` for instant candidate retrieval.
2. **Sub-millisecond ONNX Cross-Encoder**: Reranks code candidates using a quantized/optimized CPU cross-encoder (`ms-marco-MiniLM-L-6-v2`) via ONNX Runtime (<1ms per pair) with transparent PyTorch fallback.
3. **Tree-sitter AST-Aware Context Pruner**: Parses functions, methods, classes, and traits directly from the AST in Python, PHP, TypeScript, JavaScript, Go, Rust, and Java — returning clean, complete syntactic blocks instead of arbitrary line slices.
4. **Native MCP Server**: Exposes semantic search, AST pruning, test finding, and root-cause localization directly to Claude Code, Antigravity, Cursor, and Windsurf as native tools.

---

## 📊 Benchmark

| Task | Naive AI Agent (`view_file`) | Standard `grep` | `lg` (LocalGrep) | Token Savings |
| :--- | :--- | :--- | :--- | :--- |
| Inspect method in 1,200-line file | 5,400 tokens | 0 tokens (syntax blind) | **160 tokens (AST block)** | **~97%** |
| Locate Vue component | 1,800 tokens | 850 tokens (raw matches) | **120 tokens** | **~93%** |
| Filter CLI route list (400 routes) | 3,200 tokens | 600 tokens | **90 tokens** | **~97%** |
| Cross-Encoder Scoring (20 pairs) | N/A | N/A | **19ms (ONNX CPU)** | **Sub-millisecond/pair** |

---

## 🚀 Installation

### Requirements
- Linux or macOS
- `ripgrep` (`rg`)
- Python 3.9+

```bash
# 1. Install ripgrep (if not already installed)
# Ubuntu/Debian:
sudo apt install ripgrep
# macOS:
brew install ripgrep

# 2. Install LocalGrep
pip install git+https://github.com/blackrain02/localgrep.git
```

Or clone and install in editable mode:
```bash
git clone https://github.com/blackrain02/localgrep.git
cd localgrep
pip install -e .
```

---

## 🧠 Model & ONNX Engine

`lg` uses the compact `cross-encoder/ms-marco-MiniLM-L-6-v2` model (**~87 MB**). It can run using either **ONNX Runtime** (recommended for sub-millisecond execution) or **PyTorch CPU**.

### 1. Automatic Setup (Default)
On first run, `lg` automatically fetches tokenizer configurations and weights, storing them in your HuggingFace cache.

### 2. Ultra-Fast ONNX Engine Setup
To enable sub-millisecond ONNX inference:
```bash
# Export the cross-encoder to ONNX
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
When `model.onnx` is present, `lg` automatically detects it and switches from PyTorch to ONNX Runtime, slashing latency to ~0.9ms per pair.

### 3. Air-gapped / Offline Environments
In offline environments:
1. Copy `model.onnx` to `~/.local/localgrep/model.onnx`.
2. Copy `~/.cache/huggingface/hub/models--cross-encoder--ms-marco-MiniLM-L-6-v2/` to the target machine.
`lg` will operate completely offline with zero outbound network calls.

---

## 💡 Usage & Commands

### 1. Semantic Code & Component Search
Locate symbols, config definitions, or components across your repository without guessing exact file paths:
```bash
lg "payment callback gateway"
lg "user profile header dropdown"
```

### 2. Tree-sitter AST Context Pruning (`lg prune`)
Extract the exact syntactic method, function, or class boundary from a large file without dumping the entire file into context:
```bash
lg prune resources/config/AdminMenus.ts "accounting inventory"
lg prune app/Models/User.php "avatar"
lg prune app/Services/PaymentService.php "verify callback"
```

### 3. CLI Output Distillation (Pipe)
Feed massive terminal dumps into `lg` to filter and rank only the relevant lines:
```bash
php artisan route:list | lg "export excel"
git log -n 100 --oneline | lg "stripe webhook fix"
```

### 4. Smart Test Selection (`lg test`)
Locate tests related to a specific feature or method inside `tests/`:
```bash
lg test "deferred props inertia"
lg test "user registration 2fa"
```

### 5. Error & Stack Trace Localization (`lg error`)
Trace exceptions and error logs directly to potential throwing locations in your codebase:
```bash
lg error "ValidationException: The given data was invalid. price is required"
```

### 6. Semantic Skill Recommender (`lg skill`)
Match any developer task or intention directly to installed Claude Code and Antigravity skills (`.agents/skills/`, `.claude/skills/`):
```bash
lg skill "setup 2fa authentication"
lg skill "slow database query profiling and duplicate N+1 queries"
lg skill "YAGNI simplify code and remove bloat"
```

### 7. Component & Class Contract Extraction (`lg contract`)
Extract clean public API contracts (Vue `defineProps`/`defineEmits`/`defineModel`/slots, PHP class methods/properties, TS interfaces) in <10ms without reading hundreds of lines of implementation code:
```bash
lg contract resources/js/Components/UI/Card.vue
lg contract app/Models/User.php
```

### 8. Fast Route-to-Controller Mapper (`lg route`)
Map URLs, route names, or controller actions to their exact file line in `<25ms` with full support for multi-line definitions, route groups, and resource route expansion:
```bash
lg route "xhr.taxes"
lg route "accounts.index"
lg route "GET /orders"
```

### 9. Instant Zero-Token Project Topology Card (`lg topo`)
Generate an ultra-dense, 150-token executive summary of framework, PHP, active frontend stack, modular packages, DB/queue runtime, and entrypoints:
```bash
lg topo
lg topo --json
```

### 10. Call-Site & Reference Tracker (`lg callers`)
Find deterministic invocations and references to any method, function, or class across PHP and Vue/TS/JS with enclosing caller context, filtering out definitions and comments:
```bash
lg callers wasChanged
lg callers forceSyncPush
lg callers RecordToolInvocation
```

### 11. Laravel Event Architecture Map (`lg event-map`)
Map Events to Listeners across all modular packages, detecting synchronous vs queued execution (`ShouldQueue`), queue connections, and dispatched background jobs:
```bash
lg event-map
lg event-map Order
```

### 12. Offline Model Schema & Relationship Extractor (`lg schema`)
Extract model table columns, types, nullability, indexing, casts, fillable attributes, and Eloquent relationships without connecting to a live database:
```

### 13. Skeletonized File Editing (`lg slice`)
Generate a skeletonized view of a 300+ line file around a target method. Preserves imports, class declarations, and properties while collapsing non-target sibling methods into 1-line stubs. Delivers **85% to 92% token savings** on targeted edits:
```bash
lg slice app/Http/Controllers/OrderController.php "store"
lg slice resources/js/Components/ProductCard.vue "handleAddToCart"
```

### 14. Sub-20ms Pre-Flight Linter (`lg lint-fast`)
Instantly validate syntax, unimported classes, and balanced Vue template tags before finalizing edits:
```bash
lg lint-fast app/Services/PaymentService.php
lg lint-fast resources/js/Components/Header.vue
```

### 15. Targeted Test Selector & Execution (`lg test-map`)
Map any source file (in core or modular packages) to matching Pest/PHPUnit tests; execute and isolate failures with `--run`:
```bash
lg test-map app/Services/InvoiceService.php
lg test-map app/Services/InvoiceService.php --run
```

### 16. Zero-Query Database Peeking (`lg sample`)
Peek 1 realistic runtime DB record directly via local PostgreSQL/MySQL socket in `<5ms` with credentials redacted:
```bash
lg sample Order
lg sample users
```

### 17. Refactor Blast Radius Engine (`lg impact`)
Calculate downstream impact across Vue bindings, controllers, services, routes, and tests before modifying shared code:
```bash
lg impact PaymentGatewayInterface
lg impact app/Services/CartService.php
```

### 18. Stack Trace & SQL Distiller (`lg error-decode`)
Distill massive 100+ line Laravel stack traces into the innermost application frame with inlined SQL bindings:
```bash
lg error-decode storage/logs/laravel.log
cat error.txt | lg error-decode
```

### 19. Environment & Config Integrity (`lg env-audit`)
Audit `.env` variables against `config/*.php` references and live DB tables in `<15ms`:
```bash
lg env-audit
```

### 20. Frontend Reactive Flow DAG (`lg state-map`)
Extract an ASCII Directed Acyclic Graph tracing reactive flows (`[prop] -> [computed] -> [watch] -> [emit]`):
```bash
lg state-map resources/js/Components/CartDrawer.vue
```

### 21. Full-Stack API Contract Synthesizer (`lg api-shape`)
Synthesize Route URI, controller action, FormRequest rules, Eloquent resource schema, and Inertia view in `<25ms`:
```bash
lg api-shape "orders.store"
lg api-shape "OrderController@store"
```

### 22. Edit Pre-Validation (`lg verify-patch`)
Pre-validate edit search blocks against target files to verify uniqueness, exact start/end lines, and tab/space alignment before running tool edits:
```bash
lg verify-patch app/Services/PaymentService.php "public function verify()"
```

### 23. Pre-Commit Diff Auditor (`lg audit-diff`)
Audit staged or unstaged diffs for leftover `dd()`, `dump()`, `console.log()`, secrets, and PHP lints:
```bash
lg audit-diff
lg audit-diff --staged
```

### 24. Test Failure Isolator (`lg test-isolate`)
Run tests or pipe test output to strip 95% of vendor stack noise, isolating only the failing test and app snippet:
```bash
lg test-isolate php artisan test --compact
```

### 25. Machine-Readable Agent JSON Mode (`--json`)
Append `--json` to any command for structured machine consumption by AI coding assistants:
```bash
lg route "xhr.taxes" --json
lg callers wasChanged --json
lg schema Order --json
lg slice app/Models/User.php "getName" --json
```

### 26. Daemon Lifecycle & Memory Status (`lg status`, `lg stop`)
Inspect memory RSS, runtime uptime, backend provider, or gracefully terminate the daemon:
```bash
lg status
lg stop
```

---

## ⚡ Resident Systemd Daemon Setup (Zero Cold-Start)

To eliminate Python startup and model loading overhead, run LocalGrep as a background user service via `systemd`. Once active, commands execute in **5ms - 50ms**.

### 1. Create the Service Unit
Create `~/.config/systemd/user/localgrep.service`:
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

### 2. Enable & Start
```bash
systemctl --user daemon-reload
systemctl --user enable --now localgrep.service
```

Verify status:
```bash
systemctl --user status localgrep.service
lg status
```

---

## 🔌 Model Context Protocol (MCP) Server Setup

LocalGrep exposes its entire suite of tools as a high-performance MCP server via `lg mcp`. This gives AI coding assistants native access to all capabilities without spawning shell processes.

### 1. Client Configurations

#### A. Claude Code (`~/.claude.json`):
Add `localgrep` under `mcpServers`:
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

#### B. Antigravity / Gemini CLI (`~/.gemini/settings.json`):
Add `localgrep` under `mcpServers`:
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

#### C. Cursor, Windsurf, or Project-level (`.mcp.json`):
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

### 2. Complete MCP Tools Catalog

| MCP Tool | Description |
| :--- | :--- |
| `localgrep_search` | Zero-index semantic search across codebase (<100ms) |
| `localgrep_contract` | Component & class contract extractor (props, emits, methods, TS interfaces) |
| `localgrep_slice` | Skeletonized file context generator (85-92% token reduction for edits) |
| `localgrep_prune` | AST-driven context pruner returning exact function/class boundaries |
| `localgrep_lint_fast` | Sub-20ms pre-flight linter (syntax, unimported classes, Vue template tags) |
| `localgrep_test_map` | Targeted test selector mapping source files to Pest/PHPUnit tests |
| `localgrep_sample` | Zero-query database socket record peeker (<5ms) with credential redaction |
| `localgrep_impact` | Refactor blast radius & downstream dependency calculator |
| `localgrep_error_decode` | 100+ line Laravel stack trace & bound SQL distiller |
| `localgrep_env_audit` | Environment variable and live DB table reconciler (<15ms) |
| `localgrep_state_map` | Vue 3 SFC reactive dependency graph DAG generator |
| `localgrep_api_shape` | Full-stack contract synthesizer (Route, FormRequest, Resource, Vue view) |
| `localgrep_route` | Fast URL/name to controller & Inertia view mapper (<15ms) |
| `localgrep_schema` | Offline database table schema, columns, casts, and Eloquent relations |
| `localgrep_callers` | Deterministic call-site tracker across PHP & Vue/TS |
| `localgrep_event_map` | Full event-listener architecture map with sync vs queue dispatch |
| `localgrep_test` | Pinpoint tests matching features or bugs |
| `localgrep_error` | Trace exceptions/stack traces to root causes in source code |
| `localgrep_skill` | Semantic skill recommender matching developer intent to skills |

---

## 🤝 Instructing AI Agents (Team-Safe Configuration)

When sharing a repository with team members who may not have LocalGrep installed, AI rules must be **environment-aware**. This ensures agents use `lg` when available without breaking or hanging on machines where `lg` is absent.

Add the following block to your project's `AGENTS.md`, `CLAUDE.md`, `GEMINI.md`, or `.cursorrules`:

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

## 📚 Deep Dives & Guides

- [**LocalGrep vs smgrep & Model Upgrade Analysis**](COMPARISON_AND_UPGRADE.md): In-depth comparison with smgrep, ONNX acceleration benchmarks, and evaluation of whether larger models are necessary.
- [**Benchmark: LocalGrep (ONNX) vs Ollama (Qwen3-Embedding)**](MODEL_BENCHMARK_OLLAMA_QWEN3.md): Real-world evaluation of 19ms CPU ONNX vs Ollama Qwen3 on live codebases.
- [**Just-In-Time (JIT) Skill Routing Proposal**](JIT_SKILL_ROUTING_PROPOSAL.md): How dormant skills + `lg skill` / `/s` slash command save up to 115,000 tokens per 20-turn session.

---

## 📄 License

MIT © [Javad (blackrain02)](https://github.com/blackrain02)
