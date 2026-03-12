# Ninja

A model-agnostic Rust CLI coding agent powered by OpenRouter. Ninja is an open-source replacement for Claude Code — it reads files, edits code, runs shell commands, and searches codebases to solve software engineering tasks autonomously. Use any model available on OpenRouter (Claude, GPT-4, Gemini, Llama, etc.) with a single `--model` flag.

## How It Works

Ninja runs an **agent loop**: it sends a prompt to the LLM via OpenRouter, receives tool calls back, executes them locally, and feeds the results back. This repeats until the task is complete or the iteration limit is reached.

```
┌─────────┐     ┌──────────────┐     ┌───────────┐
│  Prompt  │────▶│  OpenRouter   │────▶│ Tool Calls │
│          │     │ (any model)   │     │            │
└─────────┘     └──────────────┘     └─────┬──────┘
                       ▲                     │
                       │                     ▼
                 ┌─────┴──────┐     ┌───────────────┐
                 │  Tool      │◀────│  Local Tools   │
                 │  Results   │     │  (file, shell, │
                 └────────────┘     │   search)      │
                                    └───────────────┘
```

Every LLM call, tool invocation, and result is captured in a **rollout log** — a full JSON trace with timestamps, token counts, and timing data. This enables automated evaluation and improvement.

## Tools

| Tool | Description |
|------|-------------|
| `read_file` | Read file contents with path resolution |
| `write_file` | Create or overwrite files |
| `edit_file` | Exact string replacement (`old_string` → `new_string`), with `replace_all` support and contextual error messages |
| `list_dir` | List directory contents |
| `shell_exec` | Execute shell commands with timeout |
| `glob_search` | File pattern matching (`**/*.py`, `src/**/*.rs`) |
| `grep_search` | Content search powered by ripgrep with regex support |

## Installation

```bash
git clone https://github.com/unconst/ninja
cd ninja
cargo build
```

Requires Rust (install via [rustup](https://rustup.rs)). Uses `rustls-tls` — no OpenSSL/libssl dependency.

## Usage

```bash
# Set your API key
export OPENROUTER_API_KEY=your-key-here

# Basic usage (defaults to anthropic/claude-sonnet-4)
ninja --prompt "Fix the bug in main.rs"

# Use any OpenRouter model
ninja --prompt "Refactor this" --model google/gemini-2.5-pro
ninja --prompt "Add tests" --model openai/gpt-4o
ninja --prompt "Explain the code" --model meta-llama/llama-4-scout

# With a prompt file and specific working directory
ninja --prompt-file task.md --workdir /path/to/repo

# Save full rollout trace for analysis
ninja --prompt "Add tests" --rollout rollout.json --verbose

# Control iteration budget
ninja --prompt "Implement feature X" --max-iterations 30

# JSON output for piping
ninja --prompt "Describe the codebase" --output-format json
```

## Architecture

```
src/
├── main.rs                  # CLI entry point (clap)
├── agent/
│   ├── mod.rs               # Module exports
│   ├── api_client.rs        # OpenRouter Messages API client (model-agnostic)
│   ├── runner.rs            # Agent loop: prompt → model → tool calls → repeat
│   └── rollout.rs           # Rollout logging (tokens, timing, tool calls)
└── tools/
    ├── mod.rs               # Tool registry and dispatch
    ├── file_ops.rs          # read_file, write_file, edit_file, list_dir
    ├── shell.rs             # shell_exec
    └── search.rs            # glob_search, grep_search
```

## Autonomous Improvement Pipeline

Ninja is improved automatically through a closed-loop pipeline:

1. **Task Generation** — SWE tasks are generated from real GitHub PRs (merged pull requests from repos like Django, Flask, FastAPI, Black). The generator clones at the base commit, extracts the diff as ground truth, and packages it as a task.

2. **Execution** — Ninja attempts to solve the task in an isolated checkout. The full rollout (every LLM call, tool call, and result) is saved as JSON.

3. **Evaluation** — An evaluator LLM reviews the rollout against the ground truth diff: which files were modified correctly, what was missed, where the agent got stuck.

4. **Improvement** — Based on evaluation results, the evaluator generates patches to Ninja's own source code (system prompt tuning, tool improvements, agent loop fixes). Patches are applied with automatic rollback on build failure.

5. **Rebuild & Retest** — Ninja is rebuilt and re-run on the same tasks to measure improvement.

### SWE-Bench Pro Results

| Metric | Value |
|--------|-------|
| **SWE-Bench Pro pass@1** | **19/215 (8.8%)** |
| Patch rate | 93% (199/215 produced patches) |
| Near-misses (partial F2P) | 26 tasks |
| Average cost per task | $0.16 |
| Total eval cost | $34.61 |

*Baseline measured on 215/731 tasks with locally available Docker images. Full run pending.*

### Frontier Task Results (175 custom tasks)

| Task Category | Result |
|---------------|--------|
| Isolated debugging (ETL, repo_debug) | 100% — immune to scale |
| Construction (2-3 files) | 100% |
| Construction (4 files) | 83% |
| Construction (5 files) | 50% |
| Dependency update (3-5 files) | 100% |
| Dependency update (6 files) | 17% — sharpest cliff |
| Refactoring extraction (2 modules) | 67% |
| Refactoring extraction (3 modules) | 17% |
| Migration (flask→fastapi) | 33% |
| Cross-layer debugging (5+ bugs) | cliff at 5 bugs |
| Deadlock/structural reorg | cliff at 4 bugs |
| Parser/grammar debugging | cliff at 6 bugs |
| Dead code elimination (8 files) | 50% |
| Perf optimization (3+ bugs) | 0% — attention fragmentation |

### Key Findings

The agent's competence boundary follows a **gradual cliff model** driven by interconnection, not raw scale:
- **Isolated fixes**: immune through 8+ bugs in 8+ files
- **Interconnected fixes**: cliff onset at 4-6 bugs depending on interdependency type
- **Construction**: cliff at 4 files / 6 endpoints
- **Refactoring**: hardest — cliff at 2 modules (even simplest extraction is stochastic)
- **Attention fragmentation**: agent preferentially does easy substitutions and drops hard structural changes

Four distinct failure modes identified:
1. **Propagation incompleteness** — misses locations in multi-file changes (stochastic)
2. **Interface contract violation** — changes signatures during transformations
3. **Difficulty-selective attention** — easy fixes done, hard ones dropped
4. **Test gaming** — satisfies weak tests via shortcuts

Pipeline tools live in the [Arbos](https://github.com/unconst/arbos) repo:
- `tools/swe_gen/` — SWE task generator (GitHub Archive → PR discovery → task packaging)
- `tools/eval_pipeline.py` — end-to-end task evaluation
- `tools/auto_improve.py` — automated improvement suggestions

## Configuration

| Env Variable | Description | Default |
|---|---|---|
| `OPENROUTER_API_KEY` | API key for OpenRouter | (required) |
| `OPENROUTER_BASE_URL` | Override API base URL | `https://openrouter.ai/api` |
| `ANTHROPIC_API_KEY` | Alternative: direct Anthropic API key (fallback) | — |
| `ANTHROPIC_BASE_URL` | Alternative: direct API base URL (fallback) | — |

## License

MIT
