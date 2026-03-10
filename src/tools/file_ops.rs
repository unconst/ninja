use serde_json::{json, Value};
use std::fs;
use std::path::{Path, PathBuf};

use crate::agent::api_client::ToolDef;

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
            name: "replace_lines".to_string(),
            description: "Replace a range of lines in a file with new content. More reliable than \
                          edit_file for large changes. Line numbers are 1-based and inclusive. \
                          You MUST read the file first to know the correct line numbers."
                .to_string(),
            input_schema: json!({
                "type": "object",
                "properties": {
                    "path": {
                        "type": "string",
                        "description": "Path to the file to edit"
                    },
                    "start_line": {
                        "type": "integer",
                        "description": "First line to replace (1-based, inclusive)"
                    },
                    "end_line": {
                        "type": "integer",
                        "description": "Last line to replace (1-based, inclusive). Use same as start_line to replace a single line."
                    },
                    "new_content": {
                        "type": "string",
                        "description": "The new content to insert (replaces the entire line range). Use empty string to delete lines."
                    }
                },
                "required": ["path", "start_line", "end_line", "new_content"]
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

/// Acquire an advisory file lock for exclusive write access.
/// Lock files are stored in /tmp/ninja-locks/ to avoid polluting the working directory.
/// Returns the lock file handle (lock is released when the handle is dropped).
fn acquire_file_lock(path: &Path) -> Result<fs::File, String> {
    use std::collections::hash_map::DefaultHasher;
    use std::hash::{Hash, Hasher};
    use std::os::unix::io::AsRawFd;

    let lock_dir = Path::new("/tmp/ninja-locks");
    let _ = fs::create_dir_all(lock_dir);

    // Hash the canonical path to get a unique lock file name
    let canonical = path.canonicalize().unwrap_or_else(|_| path.to_path_buf());
    let mut hasher = DefaultHasher::new();
    canonical.hash(&mut hasher);
    let hash = hasher.finish();
    let lock_path = lock_dir.join(format!("{:016x}.lock", hash));

    let lock_file = fs::OpenOptions::new()
        .create(true)
        .write(true)
        .truncate(false)
        .open(&lock_path)
        .map_err(|e| format!("Failed to create lock file: {}", e))?;

    // LOCK_EX — exclusive lock, blocking
    let ret = unsafe { libc::flock(lock_file.as_raw_fd(), libc::LOCK_EX) };
    if ret != 0 {
        return Err(format!(
            "Failed to acquire lock on {}",
            lock_path.display()
        ));
    }

    Ok(lock_file)
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

    // Lock file for exclusive access
    let _lock = acquire_file_lock(&path)?;

    fs::write(&path, content)
        .map_err(|e| format!("Failed to write {}: {}", path.display(), e))?;

    Ok(format!(
        "File written: {} ({} bytes)",
        path.display(),
        content.len()
    ))
}

pub fn edit_file(args: &Value, workdir: &Path) -> Result<String, String> {
    let path_str = args["path"].as_str().ok_or("Missing 'path' argument")?;
    let old_string = args["old_string"]
        .as_str()
        .ok_or("Missing 'old_string' argument")?;
    let new_string = args["new_string"]
        .as_str()
        .ok_or("Missing 'new_string' argument")?;
    let replace_all = args["replace_all"].as_bool().unwrap_or(false);
    let path = resolve_path(path_str, workdir);

    // Lock file for exclusive access (read-modify-write atomically)
    let _lock = acquire_file_lock(&path)?;

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
            let lines: Vec<String> = similar
                .iter()
                .map(|(n, l)| format!("  L{}: {}", n + 1, l))
                .collect();
            format!("\nSimilar lines found:\n{}", lines.join("\n"))
        };
        return Err(format!(
            "String not found in {}.{}",
            path.display(),
            hint
        ));
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
            count,
            path.display(),
            ctx
        ));
    }

    let new_content = if replace_all {
        content.replace(old_string, new_string)
    } else {
        content.replacen(old_string, new_string, 1)
    };
    fs::write(&path, &new_content)
        .map_err(|e| format!("Failed to write {}: {}", path.display(), e))?;

    Ok(format!(
        "File edited: {} ({} replacement{})",
        path.display(),
        count,
        if count > 1 { "s" } else { "" }
    ))
}

pub fn replace_lines(args: &Value, workdir: &Path) -> Result<String, String> {
    let path_str = args["path"].as_str().ok_or("Missing 'path' argument")?;
    let start_line = args["start_line"]
        .as_u64()
        .ok_or("Missing 'start_line' argument")? as usize;
    let end_line = args["end_line"]
        .as_u64()
        .ok_or("Missing 'end_line' argument")? as usize;
    let new_content = args["new_content"]
        .as_str()
        .ok_or("Missing 'new_content' argument")?;
    let path = resolve_path(path_str, workdir);

    if start_line == 0 {
        return Err("start_line must be >= 1 (1-based)".to_string());
    }
    if end_line < start_line {
        return Err(format!(
            "end_line ({}) must be >= start_line ({})",
            end_line, start_line
        ));
    }

    // Lock file for exclusive access
    let _lock = acquire_file_lock(&path)?;

    let content = fs::read_to_string(&path)
        .map_err(|e| format!("Failed to read {}: {}", path.display(), e))?;

    let lines: Vec<&str> = content.lines().collect();
    let total_lines = lines.len();

    if start_line > total_lines {
        return Err(format!(
            "start_line {} exceeds file length ({} lines)",
            start_line, total_lines
        ));
    }

    let effective_end = end_line.min(total_lines);
    let start_idx = start_line - 1; // Convert to 0-based

    // Build new file content
    let mut new_lines: Vec<&str> = Vec::new();
    // Lines before the replacement range
    new_lines.extend_from_slice(&lines[..start_idx]);
    // New content (may be empty for deletion)
    if !new_content.is_empty() {
        for line in new_content.lines() {
            new_lines.push(line);
        }
    }
    // Lines after the replacement range
    if effective_end < total_lines {
        new_lines.extend_from_slice(&lines[effective_end..]);
    }

    let mut result = new_lines.join("\n");
    // Preserve trailing newline if original had one
    if content.ends_with('\n') {
        result.push('\n');
    }

    fs::write(&path, &result)
        .map_err(|e| format!("Failed to write {}: {}", path.display(), e))?;

    let lines_removed = effective_end - start_idx;
    let lines_added = if new_content.is_empty() {
        0
    } else {
        new_content.lines().count()
    };

    Ok(format!(
        "Replaced lines {}-{} in {} ({} lines removed, {} lines added, {} total lines now)",
        start_line,
        effective_end,
        path.display(),
        lines_removed,
        lines_added,
        new_lines.len()
    ))
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
