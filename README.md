# Ninja

A CLI coding agent powered by Claude. Ninja is a Rust-based tool that acts as an autonomous coding assistant — reading files, editing code, running shell commands, and searching codebases to solve software engineering tasks.

## Features

- **Claude-powered**: Uses the Claude API (via OpenRouter or direct Anthropic API) for reasoning
- **Tool use**: File read/write/edit, shell execution, glob/grep search
- **Full rollout logging**: Captures all LLM I/O, tool calls, timing data for analysis
- **Configurable**: Model selection, iteration limits, output formats (text/json/stream-json)

## Installation

```bash
cargo install --path .
```

## Usage

```bash
# Basic usage
ninja --prompt "Fix the bug in main.rs"

# With a prompt file
ninja --prompt-file task.md --workdir /path/to/repo

# Save rollout for analysis
ninja --prompt "Add tests" --rollout rollout.json --verbose

# Use a specific model
ninja --prompt "Refactor this" --model anthropic/claude-sonnet-4
```

## Architecture

```
src/
├── main.rs              # CLI entry point (clap)
├── agent/
│   ├── mod.rs           # Module exports
│   ├── claude_client.rs # API client for Claude/OpenRouter
│   ├── runner.rs        # Agent loop: prompt → LLM → tool → repeat
│   └── rollout.rs       # Rollout logging (tokens, timing, tool calls)
└── tools/
    ├── mod.rs           # Tool registry and dispatch
    ├── file_ops.rs      # read_file, write_file, edit_file, list_dir
    ├── shell.rs         # shell_exec
    └── search.rs        # glob_search, grep_search
```

## License

MIT
