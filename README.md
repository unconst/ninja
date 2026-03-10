# Ninja

A Rust CLI coding agent powered by Claude via OpenRouter. Ninja is an open-source replacement for Claude Code — it reads files, edits code, runs shell commands, and searches codebases to solve software engineering tasks autonomously.

## How It Works

Ninja runs an **agent loop**: it sends a prompt to Claude, receives tool calls back, executes them locally, and feeds the results back to Claude. This repeats until the task is complete or the iteration limit is reached.

```
┌─────────┐     ┌──────────────┐     ┌───────────┐
│  Prompt  │────▶│  Claude API   │────▶│ Tool Calls │
│          │     │ (OpenRouter)  │     │            │
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

# Basic usage
ninja --prompt "Fix the bug in main.rs"

# With a prompt file and specific working directory
ninja --prompt-file task.md --workdir /path/to/repo

# Save full rollout trace for analysis
ninja --prompt "Add tests" --rollout rollout.json --verbose

# Use a specific model
ninja --prompt "Refactor this" --model anthropic/claude-sonnet-4

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
│   ├── claude_client.rs     # Anthropic Messages API client (via OpenRouter)
│   ├── runner.rs            # Agent loop: prompt → Claude → tool calls → repeat
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

3. **Evaluation** — Claude evaluates the rollout against the ground truth diff: which files were modified correctly, what was missed, where the agent got stuck.

4. **Improvement** — Based on evaluation results, Claude generates patches to Ninja's own source code (system prompt tuning, tool improvements, agent loop fixes). Patches are applied with automatic rollback on build failure.

5. **Rebuild & Retest** — Ninja is rebuilt and re-run on the same tasks to measure improvement.

### Current Results

| Task Type | Success Rate |
|-----------|-------------|
| Single-file tasks | 100% |
| Multi-file tasks | 60–75% |

Pipeline tools live in the [Arbos](https://github.com/unconst/arbos) repo:
- `tools/swe_gen/` — SWE task generator (GitHub Archive → PR discovery → task packaging)
- `tools/eval_pipeline.py` — end-to-end task evaluation
- `tools/auto_improve.py` — automated improvement suggestions
- `tools/improve_ninja.py` — full improvement cycle orchestrator

## Configuration

| Env Variable | Description | Default |
|---|---|---|
| `OPENROUTER_API_KEY` | API key for OpenRouter | (required) |
| `ANTHROPIC_API_KEY` | Alternative: direct Anthropic API key | — |
| `ANTHROPIC_BASE_URL` | Override API base URL | `https://openrouter.ai/api` |

## License

MIT
