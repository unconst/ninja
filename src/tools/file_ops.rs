use serde_json::{json, Value};
use std::fs;
use std::path::{Path, PathBuf};

use crate::agent::claude_client::ToolDef;

pub fn definitions() -> Vec<ToolDef> {
    vec![
        ToolDef {
            name: "read_file".to_string(),
            description: "Read the contents of a file. Returns the file content with line numbers."
                .to_string(),
            input_schema: json!({
                "type": "object",
                "properties": {
                    "path": {
                        "type": "string",
                        "description": "Path to the file to read (relative to working directory or absolute)"
                    },
                    "offset": {
                        "type": "integer",
                        "description": "Line number to start reading from (1-based)"
                    },
                    "limit": {
                        "type": "integer",
                        "description": "Maximum number of lines to read"
                    }
                },
                "required": ["path"]
            }),
        },
        ToolDef {
            name: "write_file".to_string(),
            description: "Write content to a file. Creates the file if it doesn't exist, overwrites if it does."
                .to_string(),
            input_schema: json!({
                "type": "object",
                "properties": {
                    "path": {
                        "type": "string",
                        "description": "Path to the file to write"
                    },
                    "content": {
                        "type": "string",
                        "description": "Content to write to the file"
                    }
                },
                "required": ["path", "content"]
            }),
        },
        ToolDef {
            name: "edit_file".to_string(),
            description: "Edit a file by replacing an exact string match with new content. The old_string must be unique in the file unless replace_all is true. Include enough surrounding context to make old_string unique."
                .to_string(),
            input_schema: json!({
                "type": "object",
                "properties": {
                    "path": {
                        "type": "string",
                        "description": "Path to the file to edit"
                    },
                    "old_string": {
                        "type": "string",
                        "description": "The exact string to find and replace. Must be unique in the file (include surrounding context if needed)"
                    },
                    "new_string": {
                        "type": "string",
                        "description": "The string to replace it with"
                    },
                    "replace_all": {
                        "type": "boolean",
                        "description": "If true, replace ALL occurrences of old_string (default: false)"
                    }
                },
                "required": ["path", "old_string", "new_string"]
            }),
        },
        ToolDef {
            name: "list_dir".to_string(),
            description: "List files and directories in a given path.".to_string(),
            input_schema: json!({
                "type": "object",
                "properties": {
                    "path": {
                        "type": "string",
                        "description": "Directory path to list (default: working directory)"
                    }
                },
                "required": []
            }),
        },
    ]
}

fn resolve_path(path_str: &str, workdir: &Path) -> PathBuf {
    let p = Path::new(path_str);
    if p.is_absolute() {
        p.to_path_buf()
    } else {
        workdir.join(p)
    }
}

pub fn read_file(args: &Value, workdir: &Path) -> Result<String, String> {
    let path_str = args["path"].as_str().ok_or("Missing 'path' argument")?;
    let path = resolve_path(path_str, workdir);

    let content = fs::read_to_string(&path)
        .map_err(|e| format!("Failed to read {}: {}", path.display(), e))?;

    let offset = args["offset"].as_u64().unwrap_or(1).max(1) as usize;
    let limit = args["limit"].as_u64().unwrap_or(2000) as usize;

    let lines: Vec<&str> = content.lines().collect();
    let start = (offset - 1).min(lines.len());
    let end = (start + limit).min(lines.len());

    let numbered: Vec<String> = lines[start..end]
        .iter()
        .enumerate()
        .map(|(i, line)| format!("{:>6}\t{}", start + i + 1, line))
        .collect();

    Ok(numbered.join("\n"))
}

pub fn write_file(args: &Value, workdir: &Path) -> Result<String, String> {
    let path_str = args["path"].as_str().ok_or("Missing 'path' argument")?;
    let content = args["content"].as_str().ok_or("Missing 'content' argument")?;
    let path = resolve_path(path_str, workdir);

    // Create parent directories
    if let Some(parent) = path.parent() {
        fs::create_dir_all(parent)
            .map_err(|e| format!("Failed to create directory: {}", e))?;
    }

    fs::write(&path, content)
        .map_err(|e| format!("Failed to write {}: {}", path.display(), e))?;

    Ok(format!("File written: {} ({} bytes)", path.display(), content.len()))
}

pub fn edit_file(args: &Value, workdir: &Path) -> Result<String, String> {
    let path_str = args["path"].as_str().ok_or("Missing 'path' argument")?;
    let old_string = args["old_string"].as_str().ok_or("Missing 'old_string' argument")?;
    let new_string = args["new_string"].as_str().ok_or("Missing 'new_string' argument")?;
    let replace_all = args["replace_all"].as_bool().unwrap_or(false);
    let path = resolve_path(path_str, workdir);

    let content = fs::read_to_string(&path)
        .map_err(|e| format!("Failed to read {}: {}", path.display(), e))?;

    let count = content.matches(old_string).count();
    if count == 0 {
        // Show nearby lines to help the agent find the right string
        let first_line = old_string.lines().next().unwrap_or(old_string);
        let similar: Vec<(usize, &str)> = content
            .lines()
            .enumerate()
            .filter(|(_, line)| {
                let trimmed = first_line.trim();
                !trimmed.is_empty() && line.contains(trimmed)
            })
            .take(5)
            .collect();

        let hint = if similar.is_empty() {
            String::new()
        } else {
            let lines: Vec<String> = similar.iter().map(|(n, l)| format!("  L{}: {}", n + 1, l)).collect();
            format!("\nSimilar lines found:\n{}", lines.join("\n"))
        };
        return Err(format!("String not found in {}.{}", path.display(), hint));
    }
    if count > 1 && !replace_all {
        // Show context around each match to help craft unique edits
        let all_lines: Vec<&str> = content.lines().collect();
        let mut ctx = String::new();
        for (idx, (bp, _)) in content.match_indices(old_string).take(3).enumerate() {
            let ln = content[..bp].matches('\n').count() + 1;
            let s = ln.saturating_sub(2);
            let e = (ln + 2).min(all_lines.len());
            ctx.push_str(&format!("\n  Match {} at L{}:\n", idx + 1, ln));
            for i in s..e {
                let m = if i + 1 == ln { ">>>" } else { "   " };
                ctx.push_str(&format!("    {} L{}: {}\n", m, i + 1, all_lines[i]));
            }
        }
        return Err(format!(
            "String found {} times in {}. Include more surrounding context, or set replace_all to true.{}",
            count, path.display(), ctx
        ));
    }

    let new_content = if replace_all {
        content.replace(old_string, new_string)
    } else {
        content.replacen(old_string, new_string, 1)
    };
    fs::write(&path, &new_content)
        .map_err(|e| format!("Failed to write {}: {}", path.display(), e))?;

    Ok(format!("File edited: {} ({} replacement{})", path.display(), count, if count > 1 { "s" } else { "" }))
}

pub fn list_dir(args: &Value, workdir: &Path) -> Result<String, String> {
    let path_str = args["path"].as_str().unwrap_or(".");
    let path = resolve_path(path_str, workdir);

    let entries = fs::read_dir(&path)
        .map_err(|e| format!("Failed to list {}: {}", path.display(), e))?;

    let mut items: Vec<String> = Vec::new();
    for entry in entries {
        if let Ok(entry) = entry {
            let name = entry.file_name().to_string_lossy().to_string();
            let meta = entry.metadata();
            let suffix = if meta.map(|m| m.is_dir()).unwrap_or(false) {
                "/"
            } else {
                ""
            };
            items.push(format!("{}{}", name, suffix));
        }
    }
    items.sort();

    Ok(items.join("\n"))
}
