# Ninja

A coding agent written entirely by AI through a continuous self-improvement loop. Every line of Rust, every tool, every prompt directive — all generated and refined automatically by running the agent against increasingly difficult tasks and feeding failures back as code changes.

## The Self-Improvement Loop

Ninja wasn't designed by a human. It was **grown** through an automated feedback cycle:

```
                    ┌─────────────────────────┐
                    │   1. Generate Tasks      │
                    │   (from real GitHub PRs   │
                    │    + synthetic frontier)  │
                    └───────────┬──────────────┘
                                │
                                ▼
                    ┌─────────────────────────┐
                    │   2. Run Ninja           │
                    │   (attempt each task,    │
                    │    save full rollout)     │
                    └───────────┬──────────────┘
                                │
                                ▼
                    ┌─────────────────────────┐
                    │   3. Evaluate            │
                    │   (did it work? why not? │
                    │    what went wrong?)      │
                    └───────────┬──────────────┘
                                │
                                ▼
                    ┌─────────────────────────┐
                    │   4. Patch Ninja's Code  │
                    │   (system prompt, tools, │
                    │    agent loop, heuristics)│
                    └───────────┬──────────────┘
                                │
                                ▼
                    ┌─────────────────────────┐
                    │   5. Rebuild & Retest    │
                    │   (measure improvement,  │
                    │    rollback if worse)     │
                    └───────────┴──────────────┘
                                │
                                └──────► back to 1
```

An outer agent ([Arbos](https://github.com/unconst/arbos)) orchestrates this loop continuously. It:
- Analyzes rollouts to find failure patterns
- Writes Rust patches to Ninja's source code
- Rebuilds the binary, re-runs tasks, measures the delta
- Pushes improvements that show net-positive results, reverts the rest

This has run for **30+ sessions** producing **99 commits** of improvements — from crash fixes to sophisticated behavioral directives.

## What the Loop Has Discovered

Through hundreds of automated experiments, the loop has uncovered the **competence cliff** — a precise model of when coding agents fail:

- **Isolated bug fixes**: immune to scale (8+ bugs, 8+ files = 100% pass rate)
- **Interconnected fixes**: cliff onset at 4-6 bugs depending on interdependency
- **Code construction**: cliff at 4 files / 6 endpoints
- **Refactoring**: hardest cognitive mode — cliff at 2 modules
- **Key insight**: it's **interconnection**, not complexity, that breaks agents

The loop also identified four distinct failure modes and generated targeted fixes for each:
1. **Propagation incompleteness** → breadth-first directive, pattern propagation
2. **Interface contract violation** → signature checking, return-type preservation
3. **Difficulty-selective attention** → anti-analysis-paralysis alerts, idle nudges
4. **Test gaming** → unfalsifiable test design principles

Each of these was discovered by the loop, not a human. The loop noticed the pattern in rollout data, generated a hypothesis, wrote a code change, and measured the result.

## What Makes Ninja Different

**Every feature exists because it earned its place through measured improvement:**

- **Post-edit lint loop** — added after the loop found syntax errors compounding at high iteration counts
- **Fuzzy edit matching** — added after exact-match edits failed on whitespace variations
- **Phase-check injections** — added after the loop found the agent losing direction mid-task
- **Strategy switching** — added after the loop detected repeated failed edit patterns
- **Plan file auto-recovery** — added after context compaction was found to lose critical state
- **Anti-fabrication directives** — added after the loop caught the agent editing wrong files as substitutes
- **Signature change detection** — added after refactoring tasks revealed interface contract violations

No feature was added speculatively. Every one was a response to a measured failure.

## How It Works

Ninja runs an **agent loop**: it sends a prompt to an LLM, receives tool calls back, executes them locally, and feeds results back. This repeats until the task is done.

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

Model-agnostic via OpenRouter — works with Claude, GPT-4, Gemini, Llama, and anything else available. Dual API format auto-detection (Anthropic vs OpenAI).

## Tools

| Tool | Description |
|------|-------------|
| `read_file` | Read file contents with line ranges |
| `write_file` | Create or overwrite files |
| `edit_file` | Exact string replacement with fuzzy fallback and `replace_all` support |
| `replace_lines` | Line-range based editing for large changes |
| `list_dir` | List directory contents |
| `shell_exec` | Execute shell commands with timeout |
| `glob_search` | File pattern matching (`**/*.py`, `src/**/*.rs`) |
| `grep_search` | Content search powered by ripgrep |
| `find_definition` | AST-aware symbol lookup |
| `find_references` | Find all usages of a symbol |
| `run_tests` | Execute test suites with output capture |
| `spawn_agent` | Launch sub-agents for parallel work |
| `todo_write` | Structured task tracking |
| `web_fetch` | Fetch and parse web content |
| `web_search` | Search the web |
| `git_status` / `git_diff` / `git_log` / `git_commit` | Git operations |
| MCP tools | Dynamic tool loading via Model Context Protocol |

## Installation

```bash
git clone https://github.com/unconst/ninja
cd ninja
cargo build
```

Requires Rust (install via [rustup](https://rustup.rs)). Uses `rustls-tls` — no OpenSSL dependency.

## Usage

```bash
# Set your API key
export OPENROUTER_API_KEY=your-key-here

# Basic usage (defaults to anthropic/claude-sonnet-4)
ninja --prompt "Fix the bug in main.rs"

# Use any OpenRouter model
ninja --prompt "Refactor this" --model google/gemini-2.5-pro
ninja --prompt "Add tests" --model openai/gpt-4o

# With prompt file and working directory
ninja --prompt-file task.md --workdir /path/to/repo

# Save full rollout trace
ninja --prompt "Add tests" --rollout rollout.json --verbose

# Control iteration budget and thinking
ninja --prompt "Implement feature X" --max-iterations 75 --thinking-budget 10000
```

## Benchmarks

### SWE-Bench Pro

| Metric | Value |
|--------|-------|
| **pass@1** | **69/615 (11.2%)** |
| Total tasks | 651 (592 evaluated, 59 Docker errors) |
| Near-misses | 58 tasks (52 partial F2P + 6 P2P regressions) |
| Zero-pass | 524 tasks |
| Cost per task | ~$0.14 avg |
| Max iterations | 75 |

**By repository:**
| Repo | Pass Rate | Tasks |
|------|-----------|-------|
| ansible/ansible | 15/90 (17%) | 96 |
| NodeBB/NodeBB | 7/43 (16%) | 44 |
| future-architect/vuls | 9/58 (16%) | 62 |
| qutebrowser/qutebrowser | 11/73 (15%) | 79 |
| flipt-io/flipt | 9/82 (11%) | 85 |
| gravitational/teleport | 5/69 (7%) | 76 |
| navidrome/navidrome | 4/56 (7%) | 57 |
| protonmail/webclients | 5/61 (8%) | 65 |

**Near-miss analysis** (58 tasks with partial test passes):
- 6 P2P regressions (solved target tests but broke existing) — most addressable
- 2 tasks at 90%+ F2P pass rate (navidrome 93%, teleport 92%)
- Top failure modes: incomplete ripple propagation, over-modification, missing file creation, mock-path bypass, return-type cascading

### Performance Over Time

```
SWE-Bench Pro pass@1
────────────────────────────────────────────────────
Date        Score       Rate   Notes
────────────────────────────────────────────────────
2026-03-11  19/215      8.8%  First baseline (29% sample)
2026-03-12  69/615     11.2%  Full run (Claude via OpenRouter)
────────────────────────────────────────────────────
SOTA: ~46% (SEAL scaffold)
Claude 4.5 Sonnet raw: 23.7%

 50% ┤
     │
 40% ┤
     │
 30% ┤
     │                                          ← target
 20% ┤
     │
 10% ┤  ■ 8.8%  ■ 11.2%
     │
  0% ┼──┬──────┬──────────────────────────────
     Mar 11  Mar 12
```

*Goal: close the gap to Claude 4.5 Sonnet raw (23.7%) through general-purpose improvements, not benchmark-specific hacks.*

**Active eval**: Kimi-K2.5-TEE full run in progress (169/621, ~27%). Pilot: 2/30 (6.7%) at 27x Claude's cost ($3.80 vs $0.14/task). Near-miss re-test with 7 new Ninja commits running (58 tasks).

### Frontier Tasks (175 custom diagnostic tasks)

| Category | Pass Rate | Notes |
|----------|-----------|-------|
| Isolated debugging | 100% | Immune to scale |
| Construction (2-3 files) | 100% | |
| Construction (4 files) | 83% | |
| Construction (5 files) | 50% | |
| Dependency update (3-5 files) | 100% | |
| Dependency update (6 files) | 17% | Sharpest cliff measured |
| Refactoring (2 modules) | 67% | |
| Refactoring (3 modules) | 17% | |
| Migration (flask to fastapi) | 33% | |
| Cross-layer debugging | cliff at 5 bugs | |
| Deadlock/structural | cliff at 4 bugs | |
| Parser/grammar | cliff at 6 bugs | |
| Dead code elimination (8 files) | 50% | |
| Perf optimization (3+ bugs) | 0% | Attention fragmentation |
| Backward compat shims | 100% | Writing new code is easier |
| Test generation | 100% | Single-file comprehension |

## Architecture

```
src/
├── main.rs                  # CLI entry point (clap)
├── agent/
│   ├── api_client.rs        # OpenRouter + Anthropic API client
│   ├── runner.rs            # Agent loop with phase checks, nudges, strategy switching
│   └── rollout.rs           # Full rollout logging (tokens, timing, tool calls)
└── tools/
    ├── mod.rs               # Tool registry, concurrent dispatch, lint loop
    ├── file_ops.rs          # read_file, write_file, edit_file, replace_lines
    ├── shell.rs             # shell_exec
    ├── search.rs            # glob_search, grep_search
    └── mcp.rs               # MCP client (stdio transport, JSON-RPC 2.0)

tasks/                       # Self-improvement task framework
├── schema.py                # Task/evaluation schema
├── runner.py                # CLI: generate, run, batch, evaluate, coverage
├── generators/              # 12 task generators (frontier, repo_debug, etc.)
├── evaluators/              # 7 evaluation methods
└── dataset/                 # 250 tasks (175 frontier + 75 standard)
```

## The Improvement Pipeline (Arbos)

The outer loop that drives Ninja's improvement lives in the [Arbos](https://github.com/unconst/arbos) repo:

- `tools/swe_gen/` — Task generator: discovers merged PRs from GitHub Archive, clones at base commit, extracts ground truth diffs, packages as evaluation tasks
- `tools/eval_pipeline.py` — Runs Ninja against tasks in Docker containers, evaluates with test suites
- `tools/auto_improve.py` — Reads evaluation results, generates improvement patches to Ninja's Rust source

The loop runs continuously via pm2. When a new weakness is found, it generates frontier tasks targeting that weakness, iterates on Ninja until it improves, then validates on SWE-Bench Pro to confirm the improvement transfers to real-world tasks.

## Configuration

| Env Variable | Description | Default |
|---|---|---|
| `OPENROUTER_API_KEY` | API key for OpenRouter | (required) |
| `OPENROUTER_BASE_URL` | Override API base URL | `https://openrouter.ai/api` |
| `ANTHROPIC_API_KEY` | Direct Anthropic API (fallback) | — |
| `ANTHROPIC_BASE_URL` | Direct API base URL (fallback) | — |

## License

MIT
