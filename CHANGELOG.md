# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.7.0] - 2026-10-04

### Added
- **Multi-Tier AST Extraction (`lg contract <file> [--full]`)**:
  - Eliminates over-pruning by providing full visibility into component and model internals without reading entire 400+ line files.
  - **Vue 3 SFC**: Extracts `defineExpose`, internal reactive state variables (`ref`, `reactive`, `computed`), lifecycle hooks (`onMounted`, `onUnmounted`, etc.) with summarized invoked functions, and balanced watchers (`watch([a, b], ...)`, `watchEffect`).
  - **PHP**: Extracts traits used within classes (`use HasFactory, SoftDeletes;`), protected configuration arrays (`$casts`, `$fillable`, `$table`, `$hidden`), and protected lifecycle methods/scopes (`booted()`, `casts()`).
  - **TS/JS**: Extracts internal interfaces, type aliases, and unexported module declarations.
  - **MCP Server & CLI**: Added `full: bool = False` to `localgrep_contract` in MCP server, and `--full` / `--hooks` flags to `lg contract`.
- **Zero Cold-Start Architecture via Linux User Service (`systemd --user`)**:
  - Solves the 3-6s cold start and CLI background task dropping by running `localgrep.service` under `systemd --user` with persistent `loginctl enable-linger`.
  - Keeps ONNX runtime model warm in memory for instant (<5ms) agent query execution.
  - Automatic restart on failure and zero-maintenance daemon management.

---

## [0.6.1] - 2026-09-30

### Added
- **Frontend Inertia & Blade Route Resolution in `lg route`**: Inspects controller action methods for `Inertia::render('Component', ...)` and `view('name', ...)`, linking routes directly to frontend Vue SFC files (`resources/js/Pages/*.vue`). Supports searching routes directly by Vue component names or page URLs.

---

## [0.6.0] - 2026-09-30

### Added
- **`lg verify-patch <file> [target] [--json]`**: Pre-validation of edit blocks for code replacement tools (`replace_file_content`). Checks uniqueness, resolves exact 1-indexed `StartLine` and `EndLine`, detects indentation/whitespace discrepancies (tabs vs spaces), auto-resolves actual file indentation, and outputs drop-in tool arguments.
- **`lg audit-diff [--staged] [--file <f>] [--json]`**: Pre-commit code sanity auditor. Scans git diff for leftover debug calls (`dd`, `dump`, `ray`, `var_dump`, `console.log`, `debugger`), temporary markers (`TODO: remove`), potential secrets/tokens, and runs PHP syntax validation.
- **`lg test-isolate <command...> [--json]`**: Test failure noise isolator for Pest, PHPUnit, and Python unittest. Strips 95% of framework and vendor stack traces to distill test failures into failure description, exact test location, failure assertion message, application stack frame, and snippet.
- **MCP Server Expansion**: Added `localgrep_verify_patch`, `localgrep_audit_diff`, and `localgrep_test_isolate` tools to `mcp_server.py`.
- **Unit Test Suite**: Added `tests/test_phase3.py` with 100% test coverage across patch verification, whitespace correction, and test isolation.

---

## [0.5.1] - 2026-09-30

### Fixed
- **Upward Project Root Discovery in `lg topo`**: Added parent directory traversal to detect `composer.json` or `.git` when `lg topo` is executed from deep subfolders (e.g. `resources/js/Pages` or `app/Http`), ensuring consistent and accurate topology resolution regardless of the active working directory.

---

## [0.5.0] - 2026-09-30

### Added
- **`lg callers <Method|Class>`**: Deterministic call-site and reference tracker across PHP and Vue/TS/JS. Filters out method definitions, docblocks, comments, and pure imports to surface actual invocations with enclosing caller context (e.g. `submitOrder()`) in <25ms.
- **`lg event-map [<filter>]`**: Laravel Event-Listener-Queue-Job architecture mapper. Parses all `EventServiceProvider` files across modular packages, mapping events to listeners, detecting synchronous vs queued execution (`ShouldQueue`), queue connections, and dispatched background jobs.
- **`lg schema <Model>`**: Offline database schema and relationship extractor. Parses Model `$table`, `$fillable`, `$guarded`, and `$casts` / `casts()`, combines them with migration column definitions (types, nullability, indexing), and extracts all Eloquent relationships without connecting to a live database or running tinker (<20ms).
- **MCP Server Expansion**: Added `localgrep_callers`, `localgrep_event_map`, and `localgrep_schema` tools to `mcp_server.py`.
- **Test Suite**: Added comprehensive test suite in `tests/test_phase2.py` with 100% passing assertions.

---

## [0.4.1] - 2026-09-30

### Added
- **`--json` Flag Across All CLI Commands**: Native machine-readable JSON output for `lg contract`, `lg route`, `lg topo`, `lg prune`, `lg test`, `lg error`, `lg skill`, `lg status`, and default semantic search, enabling frictionless programmatic consumption by AI coding agents.
- **Multi-line & Chained Route Block Parsing**: Parses Laravel route definitions spanning multiple lines, including multi-line controller arrays, `Route::match(['get', 'post'], ...)`, and trailing chained calls (`->name()`, `->middleware()`).
- **Namespace & Module-Aware Controller Disambiguation**: Resolves identical controller class names (e.g. `XHRController` across 12 packages) by mapping `use` imports and prioritizing the route file's parent module directory with exact file-matching (`{clean_cls}.php`).
- **Resource Route Expansion**: Automatically expands `Route::resource` and `Route::apiResource` into standard REST actions (`index`, `create`, `store`, `show`, `edit`, `update`, `destroy`) with full `->only()` and `->except()` filtering and exact action line mapping.
- **Nested Route Group Tracking**: Tracks active URI prefixes and route name prefixes across nested closures via a curly brace stack.

### Fixed
- **Vue SFC `withDefaults` Contract Extraction**: Introduced `extract_balanced()` parser to extract full `withDefaults(defineProps<Props>(), ...)` blocks without leaking internal component lifecycle code (`onMounted`).

---

## [0.4.0] - 2026-09-30

### Added
- **`lg contract <file|component>`**: AST contract extractor for Vue SFCs (`defineProps`, `defineEmits`, `defineModel`, slots), PHP classes/interfaces (namespace, public properties, constructor promoted properties, and public method signatures), and TypeScript modules. Slashes file-reading token burn by up to 90% (<10ms execution).
- **`lg route '<query>'`**: Fast route-to-controller mapper. Scans Laravel `routes/*.php` and modular packages (`vendor/bina/*/routes/`), resolving route methods, URIs, route names, and exact controller target file line numbers in <30ms.
- **`lg topo`**: Zero-token project topology card. Generates an ultra-dense, 150-token executive summary of framework stack (Laravel, PHP), active frontend dependencies (Vue, Inertia, Tailwind, Vite), database/queue drivers, modular monorepo packages, and entry points (<15ms).
- **MCP Server Expansion**: Added `localgrep_contract`, `localgrep_route`, and `localgrep_topo` tools to `mcp_server.py`.
- Automated test suite in `tests/test_phase1.py` covering contract, route, and topology extraction.

---

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
