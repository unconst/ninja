use serde_json::{json, Value};
use std::path::Path;
use std::process::Command;

use crate::agent::api_client::ToolDef;

pub fn definitions() -> Vec<ToolDef> {
    vec![
        ToolDef {
            name: "spawn_thread".to_string(),
            description: "Launch a thread (sub-agent) to perform a subtask. The thread runs as a \
                           separate ninja process with its own context and iteration budget. Use this \
                           for the RLM pattern: decompose work into subtasks, dispatch threads, collect \
                           structured results, then re-evaluate your plan.\n\n\
                           Key features:\n\
                           - **Structured output**: Returns JSON with files_changed, findings, errors, \
                             test_results, and confidence score\n\
                           - **Context inheritance**: Pass context from your state to the thread\n\
                           - **File constraints**: Optionally restrict which files the thread can edit\n\n\
                           After collecting thread results, update your state: mark subtasks done/failed, \
                           record observations, and re-evaluate your plan before dispatching more threads."
                .to_string(),
            input_schema: json!({
                "type": "object",
                "properties": {
                    "task": {
                        "type": "string",
                        "description": "The task for the thread. Be specific — include file paths, \
                                        function names, and exact instructions."
                    },
                    "context": {
                        "type": "string",
                        "description": "Context from the orchestrator to pass to the thread. Include \
                                        relevant findings, constraints, or state that the thread needs."
                    },
                    "files": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "List of files this thread should focus on. The thread will be \
                                        instructed to only modify these files."
                    },
                    "workdir": {
                        "type": "string",
                        "description": "Working directory for the thread (default: current workdir)"
                    },
                    "max_iterations": {
                        "type": "integer",
                        "description": "Maximum iterations for the thread (default: 20, max: 50)"
                    }
                },
                "required": ["task"]
            }),
        },
        // Keep backward compatibility with spawn_agent
        ToolDef {
            name: "spawn_agent".to_string(),
            description: "Launch a sub-agent to perform an independent task in parallel. The sub-agent \
                           runs as a separate ninja process with its own context and iteration budget. \
                           Use this to fan out work: researching multiple files simultaneously, exploring \
                           different parts of a codebase, applying changes to independent files, or \
                           running searches in parallel. Each sub-agent can read, write, edit, search, \
                           and execute shell commands. Returns the sub-agent's final result text. \
                           (Consider using spawn_thread for structured output and context inheritance.)"
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
        },
    ]
}

/// Launch a thread with structured output and context inheritance.
pub fn spawn_thread(args: &Value, workdir: &Path) -> Result<String, String> {
    let task = args["task"]
        .as_str()
        .ok_or("Missing 'task' argument")?;
    let max_iterations = args["max_iterations"]
        .as_u64()
        .unwrap_or(20)
        .min(50);

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

    let context = args["context"].as_str().unwrap_or("");
    let files: Vec<String> = args["files"]
        .as_array()
        .map(|arr| {
            arr.iter()
                .filter_map(|v| v.as_str().map(|s| s.to_string()))
                .collect()
        })
        .unwrap_or_default();

    // Build the thread prompt with context and file constraints
    let mut thread_prompt = String::new();

    if !context.is_empty() {
        thread_prompt.push_str(&format!(
            "## Context from orchestrator\n{}\n\n",
            context
        ));
    }

    if !files.is_empty() {
        thread_prompt.push_str(&format!(
            "## File scope\nFocus your changes on these files: {}\n\
             Do NOT modify files outside this scope unless absolutely necessary.\n\n",
            files.join(", ")
        ));
    }

    thread_prompt.push_str(&format!("## Task\n{}\n\n", task));

    // Instruct thread to write structured result
    thread_prompt.push_str(
        "## Output format\n\
         When you are done, write your result summary as JSON to /tmp/.ninja_thread_result.json:\n\
         ```json\n\
         {\n\
           \"files_changed\": [\"list of files you modified\"],\n\
           \"findings\": [\"key observations or discoveries\"],\n\
           \"errors\": [\"any errors encountered\"],\n\
           \"test_results\": \"summary of test results if tests were run\",\n\
           \"confidence\": 0.8,\n\
           \"summary\": \"brief summary of what was done\"\n\
         }\n\
         ```\n\
         Write this file using write_file as your LAST action before stopping.",
    );

    // Find the ninja binary
    let ninja_bin = std::env::current_exe().unwrap_or_else(|_| "ninja".into());

    // Clean up any previous thread result
    let _ = std::fs::remove_file("/tmp/.ninja_thread_result.json");

    let output = Command::new(&ninja_bin)
        .arg("--prompt")
        .arg(&thread_prompt)
        .arg("--workdir")
        .arg(&sub_workdir)
        .arg("--max-iterations")
        .arg(max_iterations.to_string())
        .arg("--output-format")
        .arg("text")
        .env("NINJA_SUBAGENT", "1")
        .env("NINJA_THREAD", "1")
        .output()
        .map_err(|e| format!("Failed to spawn thread: {}", e))?;

    let stdout = String::from_utf8_lossy(&output.stdout).to_string();
    let stderr = String::from_utf8_lossy(&output.stderr).to_string();
    let exit_code = output.status.code().unwrap_or(-1);

    // Try to read structured result first
    let structured_result = std::fs::read_to_string("/tmp/.ninja_thread_result.json").ok();

    // Build the response
    let mut result = String::new();

    if let Some(ref json_str) = structured_result {
        // Parse and validate the structured result
        match serde_json::from_str::<Value>(json_str) {
            Ok(parsed) => {
                result.push_str("## Thread Result (structured)\n");
                result.push_str(&serde_json::to_string_pretty(&parsed).unwrap_or_default());
                result.push('\n');
            }
            Err(_) => {
                // JSON was written but invalid — include raw
                result.push_str("## Thread Result (raw JSON)\n");
                result.push_str(json_str);
                result.push('\n');
            }
        }
    }

    // Also include the text output for additional context
    if !stdout.is_empty() {
        if result.is_empty() {
            result.push_str("## Thread Output\n");
        } else {
            result.push_str("\n## Thread Text Output\n");
        }
        // Truncate text output if structured result exists (structured is primary)
        let max_text = if structured_result.is_some() { 5_000 } else { 20_000 };
        if stdout.len() > max_text {
            result.push_str(&stdout[..max_text]);
            result.push_str("\n... (text output truncated)");
        } else {
            result.push_str(&stdout);
        }
    }

    if result.is_empty() {
        if !stderr.is_empty() {
            let stderr_lines: Vec<&str> = stderr
                .lines()
                .filter(|l| !l.starts_with("  "))
                .filter(|l| !l.is_empty())
                .collect();
            if !stderr_lines.is_empty() {
                result.push_str(&stderr_lines.join("\n"));
            }
        }
        if result.is_empty() {
            result = format!(
                "Thread completed (exit {}) but produced no output.",
                exit_code
            );
        }
    }

    // Truncate overall result
    if result.len() > 25_000 {
        result.truncate(25_000);
        result.push_str("\n... (thread result truncated)");
    }

    Ok(result)
}

/// Legacy spawn_agent for backward compatibility.
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
        let stderr_lines: Vec<&str> = stderr
            .lines()
            .filter(|l| !l.starts_with("  "))
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

    if result.len() > 20_000 {
        result.truncate(20_000);
        result.push_str("\n... (sub-agent output truncated)");
    }

    Ok(result)
}
