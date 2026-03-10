use serde_json::{json, Value};
use std::path::Path;
use std::process::Command;

use crate::agent::claude_client::ToolDef;

pub fn definitions() -> Vec<ToolDef> {
    vec![
        ToolDef {
            name: "glob_search".to_string(),
            description: "Find files matching a glob pattern. Returns matching file paths."
                .to_string(),
            input_schema: json!({
                "type": "object",
                "properties": {
                    "pattern": {
                        "type": "string",
                        "description": "Glob pattern to match (e.g. '**/*.rs', 'src/**/*.py')"
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
                "Search file contents using a regex pattern. Returns matching lines with context."
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
                        "description": "Glob pattern to filter files (e.g. '*.rs')"
                    },
                    "context": {
                        "type": "integer",
                        "description": "Number of context lines to show around matches (default: 2)"
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

    let output = Command::new("find")
        .arg(&search_dir)
        .arg("-name")
        .arg(pattern)
        .arg("-not")
        .arg("-path")
        .arg("*/.git/*")
        .arg("-not")
        .arg("-path")
        .arg("*/target/*")
        .arg("-not")
        .arg("-path")
        .arg("*/node_modules/*")
        .output()
        .map_err(|e| format!("Failed to run find: {}", e))?;

    let result = String::from_utf8_lossy(&output.stdout).to_string();

    if result.trim().is_empty() {
        Ok("No files found matching the pattern.".to_string())
    } else {
        let lines: Vec<&str> = result.lines().take(200).collect();
        Ok(lines.join("\n"))
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

    let mut cmd = Command::new("grep");
    cmd.arg("-rn")
        .arg("--color=never")
        .arg("-E")
        .arg(pattern)
        .arg(&search_path)
        .arg(&format!("--context={}", context))
        .arg("--exclude-dir=.git")
        .arg("--exclude-dir=target")
        .arg("--exclude-dir=node_modules");

    if let Some(file_glob) = args["glob"].as_str() {
        cmd.arg(&format!("--include={}", file_glob));
    }

    let output = cmd
        .output()
        .map_err(|e| format!("Failed to run grep: {}", e))?;

    let result = String::from_utf8_lossy(&output.stdout).to_string();

    if result.trim().is_empty() {
        Ok("No matches found.".to_string())
    } else {
        let lines: Vec<&str> = result.lines().take(500).collect();
        Ok(lines.join("\n"))
    }
}
