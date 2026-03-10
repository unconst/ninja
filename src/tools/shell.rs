use serde_json::{json, Value};
use std::path::Path;
use std::process::Command;

use crate::agent::api_client::ToolDef;

pub fn definitions() -> Vec<ToolDef> {
    vec![ToolDef {
        name: "shell_exec".to_string(),
        description: "Execute a shell command and return its stdout/stderr. Use for running builds, tests, git commands, etc.".to_string(),
        input_schema: json!({
            "type": "object",
            "properties": {
                "command": {
                    "type": "string",
                    "description": "The shell command to execute"
                },
                "timeout_secs": {
                    "type": "integer",
                    "description": "Timeout in seconds (default: 120)"
                }
            },
            "required": ["command"]
        }),
    }]
}

pub fn shell_exec(args: &Value, workdir: &Path) -> Result<String, String> {
    let command = args["command"]
        .as_str()
        .ok_or("Missing 'command' argument")?;

    let output = Command::new("bash")
        .arg("-c")
        .arg(command)
        .current_dir(workdir)
        .output()
        .map_err(|e| format!("Failed to execute command: {}", e))?;

    let stdout = String::from_utf8_lossy(&output.stdout);
    let stderr = String::from_utf8_lossy(&output.stderr);

    let mut result = String::new();
    if !stdout.is_empty() {
        result.push_str(&stdout);
    }
    if !stderr.is_empty() {
        if !result.is_empty() {
            result.push('\n');
        }
        result.push_str("STDERR:\n");
        result.push_str(&stderr);
    }

    // Truncate very long outputs
    if result.len() > 50_000 {
        result.truncate(50_000);
        result.push_str("\n... (output truncated)");
    }

    let exit_code = output.status.code().unwrap_or(-1);
    if exit_code != 0 {
        result.push_str(&format!("\nExit code: {}", exit_code));
    }

    if result.is_empty() {
        result = "(no output)".to_string();
    }

    Ok(result)
}
