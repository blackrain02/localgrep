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
2. **Sub-second Cross-Encoder**: Reranks code candidates using a CPU-friendly cross-attention model (`ms-marco-MiniLM-L-6-v2`) via a persistent Unix socket daemon.
3. **Context Pruner**: Slices large files into sliding windows and returns only the exact 20-line block needed.

---

## 📊 Benchmark

| Task | Naive AI Agent (`view_file`) | Standard `grep` | `lg` (LocalGrep) | Token Savings |
| :--- | :--- | :--- | :--- | :--- |
| Inspect method in 1,200-line file | 5,400 tokens | 0 tokens (syntax blind) | **160 tokens** | **~97%** |
| Locate Vue component | 1,800 tokens | 850 tokens (raw matches) | **120 tokens** | **~93%** |
| Filter CLI route list (400 routes) | 3,200 tokens | 600 tokens | **90 tokens** | **~97%** |
| Execution Latency | 0.8s - 2.0s (network) | ~10ms | **~350ms (CPU)** | **Sub-second** |

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

## 🧠 Model Download & Management

`lg` uses the compact `cross-encoder/ms-marco-MiniLM-L-6-v2` model (**~88 MB** in size), which runs CPU-only with sub-second cross-attention inference.

### 1. Automatic Download (Default)
No manual setup required. On the first run of `lg`, the 88 MB model weights are automatically fetched from HuggingFace and cached permanently in:
```bash
~/.cache/huggingface/hub/models--cross-encoder--ms-marco-MiniLM-L-6-v2/
```

### 2. Pre-download via CLI (Optional)
If you wish to pre-fetch the weights before first invocation:
```bash
python3 -c "from transformers import AutoTokenizer, AutoModelForSequenceClassification; AutoTokenizer.from_pretrained('cross-encoder/ms-marco-MiniLM-L-6-v2'); AutoModelForSequenceClassification.from_pretrained('cross-encoder/ms-marco-MiniLM-L-6-v2')"
```

### 3. Air-gapped / Offline Environments
In restricted networks or offline workstations:
1. Download the model on an internet-connected machine.
2. Copy the model cache directory:
   ```bash
   ~/.cache/huggingface/hub/models--cross-encoder--ms-marco-MiniLM-L-6-v2/
   ```
3. Paste it at the same path on the target machine. `lg` will detect and load it offline without making any network requests.

---

## 💡 Usage & Commands

### 1. Semantic Code & Component Search
Locate symbols, config definitions, or components across your repository without guessing exact file paths:
```bash
lg "payment callback gateway"
lg "user profile header dropdown"
```

### 2. Context Pruning (`lg prune`)
Extract the exact 20-30 line code block from a large file without dumping the entire file into context:
```bash
lg prune resources/config/AdminMenus.ts "accounting inventory"
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

---

## 🛠️ Architecture

```
┌────────────────────────────────────────────────────────┐
│                   AI Coding Assistant                  │
│       (Claude Code / Cursor / Antigravity / Aider)     │
└───────────────────────────┬────────────────────────────┘
                            │ CLI Invocation (`lg`)
                            ▼
               ┌─────────────────────────┐
               │    LocalGrep Client     │ (Fast Python stdlib, <15ms)
               └────────────┬────────────┘
                            │ Unix Domain Socket (/tmp/localgrep.sock)
                            ▼
               ┌─────────────────────────┐
               │    LocalGrep Daemon     │ (Resident in RAM)
               └──────┬───────────┬──────┘
                      │           │
       Path & Regex   │           │ Cross-Encoder Scoring
       Candidate Scan │           │ (ms-marco-MiniLM-L-6-v2)
                      ▼           ▼
               ┌──────────┐   ┌───────────────┐
               │ Ripgrep  │   │ PyTorch (CPU) │
               └──────────┘   └───────────────┘
```

The daemon starts automatically on first invocation and keeps the model weights in memory. Submissions after warm-up execute in **300ms - 800ms**.

---

## 🤝 Instructing AI Agents to Use `lg`

Add this block to your project's `AGENTS.md`, `CLAUDE.md`, or `.cursorrules`:

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

## 📄 License

MIT © [Javad (blackrain02)](https://github.com/blackrain02)
