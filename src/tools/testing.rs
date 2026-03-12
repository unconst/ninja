use serde_json::{json, Value};
use std::path::Path;
use std::process::Command;

use crate::agent::api_client::ToolDef;

pub fn definitions() -> Vec<ToolDef> {
    vec![ToolDef {
        name: "run_tests".to_string(),
        description: "Run tests for the project. Auto-detects the test framework (pytest, cargo test, \
                       npm test, go test, etc.) or accepts a custom command. Returns test output \
                       with pass/fail status."
            .to_string(),
        input_schema: json!({
            "type": "object",
            "properties": {
                "command": {
                    "type": "string",
                    "description": "Custom test command to run. If omitted, auto-detects the test framework."
                },
                "path": {
                    "type": "string",
                    "description": "Specific test file or directory to test (default: project root)"
                },
                "timeout": {
                    "type": "integer",
                    "description": "Timeout in seconds (default: 120)"
                }
            },
            "required": []
        }),
    }]
}

pub fn run_tests(args: &Value, workdir: &Path) -> Result<String, String> {
    let timeout_secs = args["timeout"].as_u64().unwrap_or(120);
    let test_path = args["path"].as_str();

    let command = if let Some(cmd) = args["command"].as_str() {
        cmd.to_string()
    } else {
        detect_test_command(workdir, test_path)?
    };

    let timed_command = format!("timeout {} bash -c '{}'", timeout_secs, command.replace('\'', "'\\''"));
    let output = Command::new("bash")
        .arg("-c")
        .arg(&timed_command)
        .current_dir(workdir)
        .env("TERM", "dumb")
        .env("NO_COLOR", "1")
        .output()
        .map_err(|e| format!("Failed to run tests: {}", e))?;

    let stdout = String::from_utf8_lossy(&output.stdout);
    let stderr = String::from_utf8_lossy(&output.stderr);

    let status = if output.status.success() {
        "PASSED"
    } else {
        "FAILED"
    };

    let exit_code = output.status.code().unwrap_or(-1);

    let mut result = format!("Test Status: {} (exit code: {})\nCommand: {}\n\n", status, exit_code, command);

    if !stdout.is_empty() {
        result.push_str("--- stdout ---\n");
        let lines: Vec<&str> = stdout.lines().collect();

        // For Go tests with large output, extract failures first for visibility
        let is_go_test = command.contains("go test");
        if is_go_test && lines.len() > 200 && !output.status.success() {
            // Extract FAIL lines and --- FAIL: blocks for visibility
            let mut fail_summary: Vec<String> = Vec::new();
            let mut in_fail_block = false;
            let mut fail_block_lines = 0;
            for line in &lines {
                if line.starts_with("--- FAIL:") || line.starts_with("FAIL\t") || line.starts_with("FAIL ") {
                    fail_summary.push(line.to_string());
                    in_fail_block = line.starts_with("--- FAIL:");
                    fail_block_lines = 0;
                } else if in_fail_block && fail_block_lines < 15 {
                    fail_summary.push(line.to_string());
                    fail_block_lines += 1;
                    if line.trim().is_empty() || line.starts_with("---") {
                        in_fail_block = false;
                    }
                } else {
                    in_fail_block = false;
                }
            }
            if !fail_summary.is_empty() {
                result.push_str("=== FAILURE SUMMARY ===\n");
                for line in &fail_summary {
                    result.push_str(line);
                    result.push('\n');
                }
                result.push_str("=== END FAILURE SUMMARY ===\n\n");
            }
            // Still show last 100 lines for context
            result.push_str(&format!("... ({} lines total, showing last 100) ...\n", lines.len()));
            for line in &lines[lines.len().saturating_sub(100)..] {
                result.push_str(line);
                result.push('\n');
            }
        } else if lines.len() > 200 {
            result.push_str(&format!("... ({} lines total, showing last 200) ...\n", lines.len()));
            for line in &lines[lines.len() - 200..] {
                result.push_str(line);
                result.push('\n');
            }
        } else {
            result.push_str(&stdout);
        }
    }

    if !stderr.is_empty() {
        result.push_str("\n--- stderr ---\n");
        let lines: Vec<&str> = stderr.lines().collect();
        if lines.len() > 100 {
            result.push_str(&format!("... ({} lines total, showing last 100) ...\n", lines.len()));
            for line in &lines[lines.len() - 100..] {
                result.push_str(line);
                result.push('\n');
            }
        } else {
            result.push_str(&stderr);
        }
    }

    Ok(result)
}

fn detect_test_command(workdir: &Path, test_path: Option<&str>) -> Result<String, String> {
    // Check for Rust project (Cargo.toml)
    if workdir.join("Cargo.toml").exists() {
        return Ok(match test_path {
            Some(p) => format!("cargo test -- {} 2>&1", p),
            None => "cargo test 2>&1".to_string(),
        });
    }

    // Check for Python project (pytest)
    if workdir.join("pytest.ini").exists()
        || workdir.join("pyproject.toml").exists()
        || workdir.join("setup.py").exists()
        || workdir.join("setup.cfg").exists()
    {
        return Ok(match test_path {
            Some(p) => format!("python -m pytest {} -v 2>&1", p),
            None => "python -m pytest -v 2>&1".to_string(),
        });
    }

    // Check for Node.js project
    if workdir.join("package.json").exists() {
        // Check if there's a test script in package.json
        if let Ok(content) = std::fs::read_to_string(workdir.join("package.json")) {
            if content.contains("\"test\"") {
                return Ok("npm test 2>&1".to_string());
            }
        }
        // Fallback: try common test runners
        if workdir.join("jest.config.js").exists() || workdir.join("jest.config.ts").exists() {
            return Ok(match test_path {
                Some(p) => format!("npx jest {} 2>&1", p),
                None => "npx jest 2>&1".to_string(),
            });
        }
    }

    // Check for Go project
    if workdir.join("go.mod").exists() {
        return Ok(match test_path {
            Some(p) => format!("go test {} -v 2>&1", p),
            None => "go test ./... -v 2>&1".to_string(),
        });
    }

    // Check for Makefile with test target
    if workdir.join("Makefile").exists() {
        if let Ok(makefile) = std::fs::read_to_string(workdir.join("Makefile")) {
            if makefile.contains("test:") {
                return Ok("make test 2>&1".to_string());
            }
        }
    }

    // Fallback: try to find test files and run them
    if test_path.is_some() {
        let p = test_path.unwrap();
        if p.ends_with(".py") {
            return Ok(format!("python -m pytest {} -v 2>&1", p));
        }
        if p.ends_with(".js") || p.ends_with(".ts") {
            return Ok(format!("npx jest {} 2>&1", p));
        }
    }

    Err("Could not detect test framework. Provide a 'command' argument with the test command to run.".to_string())
}
