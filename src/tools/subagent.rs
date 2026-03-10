use serde_json::{json, Value};
use std::path::Path;
use std::process::Command;

use crate::agent::api_client::ToolDef;

pub fn definitions() -> Vec<ToolDef> {
    vec![ToolDef {
        name: "spawn_agent".to_string(),
        description: "Launch a sub-agent to perform an independent task in parallel. The sub-agent \
                       runs as a separate ninja process with its own context and iteration budget. \
                       Use this to fan out work: researching multiple files simultaneously, exploring \
                       different parts of a codebase, applying changes to independent files, or \
                       running searches in parallel. Each sub-agent can read, write, edit, search, \
                       and execute shell commands. Returns the sub-agent's final result text."
            .to_string(),
        input_schema: json!({
            "type": "object",
            "properties": {
                "prompt": {
                    "type": "string",
                    "description": "The task for the sub-agent. Be specific — include file paths, \
                                    function names, or exact instructions. The sub-agent has no \
                                    context from the parent conversation."
                },
                "workdir": {
                    "type": "string",
                    "description": "Working directory for the sub-agent (default: current workdir)"
                },
                "max_iterations": {
                    "type": "integer",
                    "description": "Maximum iterations for the sub-agent (default: 15, max: 30)"
                }
            },
            "required": ["prompt"]
        }),
    }]
}

pub fn spawn_agent(args: &Value, workdir: &Path) -> Result<String, String> {
    let prompt = args["prompt"]
        .as_str()
        .ok_or("Missing 'prompt' argument")?;
    let max_iterations = args["max_iterations"]
        .as_u64()
        .unwrap_or(15)
        .min(30);

    let sub_workdir = args["workdir"]
        .as_str()
        .map(|p| {
            let path = Path::new(p);
            if path.is_absolute() {
                path.to_path_buf()
            } else {
                workdir.join(path)
            }
        })
        .unwrap_or_else(|| workdir.to_path_buf());

    // Find the ninja binary — use the same binary that's running
    let ninja_bin = std::env::current_exe().unwrap_or_else(|_| "ninja".into());

    let output = Command::new(&ninja_bin)
        .arg("--prompt")
        .arg(prompt)
        .arg("--workdir")
        .arg(&sub_workdir)
        .arg("--max-iterations")
        .arg(max_iterations.to_string())
        .arg("--output-format")
        .arg("text")
        .env("NINJA_SUBAGENT", "1")
        .output()
        .map_err(|e| format!("Failed to spawn sub-agent: {}", e))?;

    let stdout = String::from_utf8_lossy(&output.stdout).to_string();
    let stderr = String::from_utf8_lossy(&output.stderr).to_string();
    let exit_code = output.status.code().unwrap_or(-1);

    let mut result = String::new();
    if !stdout.is_empty() {
        result.push_str(&stdout);
    }
    if !stderr.is_empty() && result.is_empty() {
        // Only include stderr if no stdout
        let stderr_lines: Vec<&str> = stderr
            .lines()
            .filter(|l| !l.starts_with("  ")) // Skip indented tool output
            .filter(|l| !l.is_empty())
            .collect();
        if !stderr_lines.is_empty() {
            result.push_str(&stderr_lines.join("\n"));
        }
    }

    if result.is_empty() {
        result = format!(
            "Sub-agent completed (exit {}) but produced no output.",
            exit_code
        );
    }

    // Truncate long results
    if result.len() > 20_000 {
        result.truncate(20_000);
        result.push_str("\n... (sub-agent output truncated)");
    }

    Ok(result)
}
