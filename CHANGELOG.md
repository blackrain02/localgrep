# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.3.3] - 2026-09-30

### Added
- **Tier 1 Fast-Path Query Routing (<15ms)**: Automatically detects symbol, component, identifier, and PascalCase/camelCase queries. When high-confidence file or symbol declaration matches exist, bypasses the neural Cross-Encoder entirely, slashing query latency from >5000ms to sub-100ms.
- **Hybrid Path + Content Discovery**: Decoupled path-based file discovery from content search constraints. `rg --files` runs concurrently with dedicated dynamic path scoring (`compute_file_path_score`), guaranteeing component declarations (e.g. `BinaTextEditor.vue` for `BinaEditor`) outrank incidental callers.
- **Noise Dampening for Localization & Dictionaries**: Automatically excludes `**/lang/**` and `**/locales/**` from default code search scope (unless explicitly requested) and applies negative score penalties to eliminate dictionary saturation.
- **Fully Offline Tokenizer Initialization**: Enforced `local_files_only=True` on Hugging Face tokenizer loading with automatic fallback, preventing network round-trips and cold-start latency.

### Changed
- Bounded neural Cross-Encoder candidate evaluation to the top 12 pre-ranked candidates with max sequence length 256, capping conceptual query execution time under 250ms.

---

## [0.3.2] - 2026-09-29

### Added
- **Algorithmic Morphological Stemmer (`stem_word`)**: In-memory rule-based inflection analysis for prefixes (`re-`, `un-`), participles (`-ed`, `-ing`), and plural/verb suffixes (`-s`, `-es`, `-ies`), with grammatical sibilant exclusions (`status`, `wherehas`, `alias`).
- **Software Engineering Action Taxonomy (`PROGRAMMING_SYNONYMS`)**: Zero-index lexical-semantic mapping covering 40+ common lifecycle verbs, framework relations, and domain entities (`recalculate` ↔ `calculate`/`recalc`/`compute`/`update`, `variation` ↔ `variant`/`option`/`sku`, `bug` ↔ `issue`/`fix`/`wherehas`/`orwherehas`).
- **Compound Identifier Preservation**: Preserves raw camelCase and snake_case symbols (such as `orWhereHas`) alongside tokenized components during search term extraction.
- **Dynamic Modular Monorepo Discovery**: Automatically inspects `config/modules.php` (`paths.modules`) to register custom module directories (e.g. `vendor/bina/`, `Modules/`) without hardcoding proprietary vendor names.
- **Configurable Search Overrides (`LOCALGREP_DIRS`)**: Added environment variable support to scan arbitrary non-standard monorepo directories.
- **Term Density Pre-scoring**: Candidate ripgrep blocks are sorted and prioritized by query term density and source code weights prior to neural cross-encoder re-ranking.

### Changed
- Decreased default cross-encoder sequence length to 256 and batch size to 16 to reduce peak working set memory footprint.
- Added meta-programming stop words (`function`, `method`, `class`, `variable`, `trait`, `interface`) to prevent candidate pollution.
- Excluded internal prompt directories (`!**/prompts/**`) from default source code search scope.

---

## [0.3.1] - 2026-09-29

### Added
- `lg stop` subcommand for graceful daemon shutdown with signal handling.
- Process-level locking using `fcntl.flock` on the daemon PID file to prevent startup race conditions.
- Automatic non-Latin query detection and user guidance message.
- Explicit non-TTY stream detection via `stat.S_ISFIFO` and `stat.S_ISREG` for seamless shell piping (`cat file | lg "q"`).

### Fixed
- **Daemon Boot on Clean Install**: Automatically downloads missing `model.onnx` from Hugging Face Hub during first run without crashing.
- **Linear Memory Leak**: Disabled ONNX Runtime CPU memory arena (`enable_cpu_mem_arena = False`) and pattern memory allocator, keeping daemon RSS constant across long-running query cycles.
- **Header Snippet Extraction**: Candidate path snippets now anchor on AST declaration keywords rather than generic namespace/license file headers.

### Security
- Hardened daemon socket permissions from `0o777` in `/tmp` to `0o600` inside `~/.local/localgrep/` (mode `0o700`), restricting socket communication strictly to the owning user.
- Added 30-second socket timeout and 10MB payload size limit on incoming connections to defend against socket starvation and buffer exhaustion.

---

## [0.3.0] - 2026-09-28

### Added
- `lg skill "<task>"` CLI command for instant (<25ms) dynamic recommendation of AI agent skills.
- Native Model Context Protocol (MCP) tool `localgrep_skill` for JIT skill resolution in Claude Code, Antigravity, and Cursor.
- Recursive skill discovery covering `.claude/skills`, `.agents/skills`, `.gemini/skills`, and `builtin/skills`.

---

## [0.2.0] - 2026-09-28

### Added
- Tree-sitter AST context pruner: `lg prune <file> "<query>"`.
- Grammar parsers for PHP, JavaScript, TypeScript, Python, and Vue Single File Components (SFC).
- Model Context Protocol (MCP) server support (`localgrep_search`, `localgrep_prune`).
- ONNX Runtime cross-encoder backend with automatic fallback to PyTorch.

---

## [0.1.0] - 2026-09-28

### Added
- Initial release of LocalGrep (`lg`).
- Zero-index local semantic search combining ripgrep candidate extraction with cross-encoder re-ranking.
- Unix domain socket daemon architecture for sub-100ms response times.
- Stream distilling utility for large CLI command outputs (`<command> | lg "<query>"`).
