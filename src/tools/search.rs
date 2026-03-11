use serde_json::{json, Value};
use std::path::Path;
use std::process::Command;

use crate::agent::api_client::ToolDef;

pub fn definitions() -> Vec<ToolDef> {
    vec![
        ToolDef {
            name: "glob_search".to_string(),
            description: "Find files matching a glob pattern. Supports ** for recursive matching."
                .to_string(),
            input_schema: json!({
                "type": "object",
                "properties": {
                    "pattern": {
                        "type": "string",
                        "description": "Glob pattern to match (e.g. '**/*.rs', 'src/**/*.py', '*.json')"
                    },
                    "path": {
                        "type": "string",
                        "description": "Directory to search in (default: working directory)"
                    }
                },
                "required": ["pattern"]
            }),
        },
        ToolDef {
            name: "grep_search".to_string(),
            description:
                "Search file contents using a regex pattern. Uses ripgrep for fast searching. \
                 Supports file type filters, output modes, and context lines."
                    .to_string(),
            input_schema: json!({
                "type": "object",
                "properties": {
                    "pattern": {
                        "type": "string",
                        "description": "Regex pattern to search for"
                    },
                    "path": {
                        "type": "string",
                        "description": "File or directory to search in (default: working directory)"
                    },
                    "glob": {
                        "type": "string",
                        "description": "Glob pattern to filter files (e.g. '*.rs', '*.{ts,tsx}')"
                    },
                    "file_type": {
                        "type": "string",
                        "description": "File type filter (e.g. 'py', 'rs', 'js', 'ts', 'go', 'java', 'c', 'cpp')"
                    },
                    "context": {
                        "type": "integer",
                        "description": "Number of context lines to show around matches (default: 2)"
                    },
                    "output_mode": {
                        "type": "string",
                        "description": "Output mode: 'content' (matching lines, default), 'files' (file paths only), 'count' (match counts)"
                    },
                    "case_insensitive": {
                        "type": "boolean",
                        "description": "Case insensitive search (default: false)"
                    }
                },
                "required": ["pattern"]
            }),
        },
    ]
}

pub fn glob_search(args: &Value, workdir: &Path) -> Result<String, String> {
    let pattern = args["pattern"]
        .as_str()
        .ok_or("Missing 'pattern' argument")?;
    let search_dir = args["path"]
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

    // Use rg --files --glob for proper ** support
    let output = Command::new("rg")
        .arg("--files")
        .arg("--glob")
        .arg(pattern)
        .arg("--sort")
        .arg("path")
        .current_dir(&search_dir)
        .output()
        .map_err(|e| format!("Failed to run rg: {}", e))?;

    let result = String::from_utf8_lossy(&output.stdout).to_string();

    if result.trim().is_empty() {
        Ok("No files found matching the pattern.".to_string())
    } else {
        let total = result.lines().count();
        let lines: Vec<&str> = result.lines().take(200).collect();
        let mut output = lines.join("\n");
        if total > 200 {
            output.push_str(&format!(
                "\n\n... ({} total files, showing first 200. Narrow your pattern to see more.)",
                total
            ));
        }
        Ok(output)
    }
}

pub fn grep_search(args: &Value, workdir: &Path) -> Result<String, String> {
    let pattern = args["pattern"]
        .as_str()
        .ok_or("Missing 'pattern' argument")?;
    let search_path = args["path"]
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

    let context = args["context"].as_u64().unwrap_or(2);
    let output_mode = args["output_mode"].as_str().unwrap_or("content");
    let case_insensitive = args["case_insensitive"].as_bool().unwrap_or(false);

    let mut cmd = Command::new("rg");
    cmd.arg("--color=never")
        .arg("--no-heading");

    // Output mode
    match output_mode {
        "files" => {
            cmd.arg("--files-with-matches");
        }
        "count" => {
            cmd.arg("--count");
        }
        _ => {
            // content mode: show line numbers and context
            cmd.arg("-n");
            cmd.arg(&format!("--context={}", context));
        }
    }

    if case_insensitive {
        cmd.arg("-i");
    }

    // File type filter
    if let Some(file_type) = args["file_type"].as_str() {
        cmd.arg("--type").arg(file_type);
    }

    // File glob filter
    if let Some(file_glob) = args["glob"].as_str() {
        cmd.arg("--glob").arg(file_glob);
    }

    cmd.arg(pattern);
    cmd.arg(&search_path);

    let output = cmd
        .output()
        .map_err(|e| format!("Failed to run rg: {}", e))?;

    let result = String::from_utf8_lossy(&output.stdout).to_string();

    if result.trim().is_empty() {
        Ok("No matches found.".to_string())
    } else {
        let lines: Vec<&str> = result.lines().take(500).collect();
        let total = result.lines().count();
        let mut output = lines.join("\n");
        if total > 500 {
            output.push_str(&format!("\n\n... ({} total lines, showing first 500)", total));
        }
        Ok(output)
    }
}
