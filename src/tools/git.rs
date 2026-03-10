use serde_json::{json, Value};
use std::path::Path;
use std::process::Command;

use crate::agent::api_client::ToolDef;

pub fn definitions() -> Vec<ToolDef> {
    vec![
        ToolDef {
            name: "git_status".to_string(),
            description: "Show the working tree status: modified, staged, and untracked files."
                .to_string(),
            input_schema: json!({
                "type": "object",
                "properties": {},
                "required": []
            }),
        },
        ToolDef {
            name: "git_diff".to_string(),
            description: "Show changes in the working directory. Use staged=true to see staged \
                          changes. Use file_path to limit to a specific file."
                .to_string(),
            input_schema: json!({
                "type": "object",
                "properties": {
                    "staged": {
                        "type": "boolean",
                        "description": "If true, show staged (cached) changes instead of unstaged"
                    },
                    "file_path": {
                        "type": "string",
                        "description": "Optional: limit diff to a specific file"
                    },
                    "stat_only": {
                        "type": "boolean",
                        "description": "If true, show only file names and change stats (--stat)"
                    }
                },
                "required": []
            }),
        },
        ToolDef {
            name: "git_log".to_string(),
            description: "Show recent commit history. Default: last 10 commits, one line each."
                .to_string(),
            input_schema: json!({
                "type": "object",
                "properties": {
                    "count": {
                        "type": "integer",
                        "description": "Number of commits to show (default: 10)"
                    },
                    "file_path": {
                        "type": "string",
                        "description": "Optional: show only commits affecting this file"
                    }
                },
                "required": []
            }),
        },
        ToolDef {
            name: "git_commit".to_string(),
            description: "Stage and commit changes. Use 'all' to stage all modified files, or \
                          'files' to stage specific files. Requires a commit message."
                .to_string(),
            input_schema: json!({
                "type": "object",
                "properties": {
                    "message": {
                        "type": "string",
                        "description": "Commit message"
                    },
                    "all": {
                        "type": "boolean",
                        "description": "If true, stage all modified/deleted files (git add -A)"
                    },
                    "files": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Specific files to stage before committing"
                    }
                },
                "required": ["message"]
            }),
        },
    ]
}

fn run_git(args: &[&str], workdir: &Path) -> Result<String, String> {
    let output = Command::new("git")
        .args(args)
        .current_dir(workdir)
        .output()
        .map_err(|e| format!("Failed to run git: {}", e))?;

    let stdout = String::from_utf8_lossy(&output.stdout).to_string();
    let stderr = String::from_utf8_lossy(&output.stderr).to_string();

    if output.status.success() {
        Ok(if stdout.trim().is_empty() {
            stderr.trim().to_string()
        } else {
            stdout.trim().to_string()
        })
    } else {
        Err(format!(
            "git {} failed: {}",
            args.join(" "),
            if stderr.trim().is_empty() {
                stdout.trim().to_string()
            } else {
                stderr.trim().to_string()
            }
        ))
    }
}

pub fn git_status(args: &Value, workdir: &Path) -> Result<String, String> {
    let _ = args; // No args needed
    run_git(&["status", "--short", "--branch"], workdir)
}

pub fn git_diff(args: &Value, workdir: &Path) -> Result<String, String> {
    let staged = args["staged"].as_bool().unwrap_or(false);
    let stat_only = args["stat_only"].as_bool().unwrap_or(false);
    let file_path = args["file_path"].as_str();

    let mut git_args = vec!["diff"];
    if staged {
        git_args.push("--cached");
    }
    if stat_only {
        git_args.push("--stat");
    }

    let fp_owned;
    if let Some(fp) = file_path {
        git_args.push("--");
        fp_owned = fp.to_string();
        git_args.push(&fp_owned);
    }

    let result = run_git(&git_args, workdir)?;

    // Truncate very long diffs
    if result.len() > 50000 {
        Ok(format!(
            "{}...\n\n(diff truncated at 50000 chars, {} total)",
            &result[..50000],
            result.len()
        ))
    } else {
        Ok(result)
    }
}

pub fn git_log(args: &Value, workdir: &Path) -> Result<String, String> {
    let count = args["count"].as_u64().unwrap_or(10);
    let file_path = args["file_path"].as_str();

    let count_str = format!("-{}", count);
    let mut git_args = vec!["log", &count_str, "--oneline", "--no-decorate"];

    let fp_owned;
    if let Some(fp) = file_path {
        git_args.push("--");
        fp_owned = fp.to_string();
        git_args.push(&fp_owned);
    }

    run_git(&git_args, workdir)
}

pub fn git_commit(args: &Value, workdir: &Path) -> Result<String, String> {
    let message = args["message"]
        .as_str()
        .ok_or("Missing 'message' argument")?;
    let all = args["all"].as_bool().unwrap_or(false);

    // Stage files
    if all {
        run_git(&["add", "-A"], workdir)?;
    } else if let Some(files) = args["files"].as_array() {
        let file_strs: Vec<&str> = files
            .iter()
            .filter_map(|f| f.as_str())
            .collect();
        if !file_strs.is_empty() {
            let mut add_args = vec!["add"];
            add_args.extend(file_strs);
            run_git(&add_args, workdir)?;
        }
    }

    // Commit
    run_git(&["commit", "-m", message], workdir)
}
