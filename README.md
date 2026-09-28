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

---

## 🔌 Model Context Protocol (MCP) Server

`lg` includes a native Model Context Protocol (MCP) server so coding assistants can invoke search, AST pruning, and skill discovery natively through tool calls.

### Launching the MCP Server
```bash
lg mcp
```

### Configuring MCP Clients

#### For Antigravity / Claude Code / Cursor / Windsurf (`.mcp.json`):
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

#### Available MCP Tools:
- **`localgrep_search`**: Fast semantic code search across components and modules.
- **`localgrep_prune`**: AST-driven context pruner returning exact function/class boundaries.
- **`localgrep_skill`**: Semantic skill selector matching developer intent to installed skills.
- **`localgrep_test`**: Pinpoint tests matching features or bugs.
- **`localgrep_error`**: Trace exceptions/stack traces to root causes in source code.

---

## 🛠️ Architecture

```
┌────────────────────────────────────────────────────────┐
│                   AI Coding Assistant                  │
│       (Claude Code / Cursor / Antigravity / Aider)     │
└──────────────┬──────────────────────────┬──────────────┘
               │ CLI (`lg`)               │ MCP (stdio)
               ▼                          ▼
┌─────────────────────────┐    ┌─────────────────────────┐
│    LocalGrep Client     │    │   LocalGrep MCP Server  │
└──────────────┬──────────┘    └──────────┬──────────────┘
               │                          │
               └────────────┬─────────────┘
                            │ Unix Domain Socket (/tmp/localgrep.sock)
                            ▼
               ┌─────────────────────────┐
               │    LocalGrep Daemon     │ (Persistent resident process)
               └──────┬───────────┬──────┘
                      │           │
       Path & Regex   │           ├── Tree-sitter AST Chunker (PHP, Py, JS, TS, Go, Rust)
       Candidate Scan │           │
                      │           └── ONNX Runtime Cross-Encoder (<1ms / pair)
                      ▼
               ┌──────────┐
               │ Ripgrep  │
               └──────────┘
```

The daemon starts automatically on first invocation and maintains model sessions in memory. Searches execute in **20ms - 300ms**.

---

## 🤝 Instructing AI Agents to Use `lg`

Add this block to your project's `AGENTS.md`, `CLAUDE.md`, or `.cursorrules`:

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

## 📄 License

MIT © [Javad (blackrain02)](https://github.com/blackrain02)

