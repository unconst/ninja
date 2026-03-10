use serde_json::{json, Value};
use std::fs;
use std::path::Path;

use crate::agent::api_client::ToolDef;

/// Memory directory name (relative to workdir)
const MEMORY_DIR: &str = ".ninja/memory";

pub fn definitions() -> Vec<ToolDef> {
    vec![ToolDef {
        name: "memory_write".to_string(),
        description: "Save a fact, pattern, or project note to persistent memory. Memory persists \
                       across sessions in .ninja/memory/. Use this to record: architectural decisions, \
                       key file paths, coding conventions, debugging insights, or anything useful for \
                       future work in this project. Each memory has a key (topic) and value (content). \
                       Writing to an existing key updates it."
            .to_string(),
        input_schema: json!({
            "type": "object",
            "properties": {
                "key": {
                    "type": "string",
                    "description": "Topic/name for this memory (e.g. 'architecture', 'testing', 'db-schema')"
                },
                "content": {
                    "type": "string",
                    "description": "The information to remember"
                }
            },
            "required": ["key", "content"]
        }),
    }]
}

pub fn memory_write(args: &Value, workdir: &Path) -> Result<String, String> {
    let key = args["key"]
        .as_str()
        .ok_or("Missing 'key' argument")?;
    let content = args["content"]
        .as_str()
        .ok_or("Missing 'content' argument")?;

    // Sanitize key to be filesystem-safe
    let safe_key: String = key
        .chars()
        .map(|c| if c.is_alphanumeric() || c == '-' || c == '_' { c } else { '-' })
        .collect();

    let memory_dir = workdir.join(MEMORY_DIR);
    fs::create_dir_all(&memory_dir)
        .map_err(|e| format!("Failed to create memory directory: {}", e))?;

    let file_path = memory_dir.join(format!("{}.md", safe_key));
    fs::write(&file_path, content)
        .map_err(|e| format!("Failed to write memory: {}", e))?;

    Ok(format!("Memory '{}' saved ({} chars)", key, content.len()))
}

/// Load all memory files from the workdir's .ninja/memory/ directory.
/// Returns a formatted string suitable for injection into the system prompt.
pub fn load_project_memory(workdir: &Path) -> Option<String> {
    let memory_dir = workdir.join(MEMORY_DIR);
    if !memory_dir.exists() {
        return None;
    }

    let mut memories = Vec::new();
    let mut total_chars = 0usize;
    const MAX_TOTAL: usize = 8000; // Cap memory in system prompt

    if let Ok(entries) = fs::read_dir(&memory_dir) {
        let mut files: Vec<_> = entries
            .filter_map(|e| e.ok())
            .filter(|e| {
                e.path()
                    .extension()
                    .map(|ext| ext == "md")
                    .unwrap_or(false)
            })
            .collect();
        // Sort by modification time (newest first)
        files.sort_by(|a, b| {
            let a_time = a.metadata().and_then(|m| m.modified()).ok();
            let b_time = b.metadata().and_then(|m| m.modified()).ok();
            b_time.cmp(&a_time)
        });

        for entry in files {
            if total_chars >= MAX_TOTAL {
                memories.push("... (additional memories truncated)".to_string());
                break;
            }
            let key = entry
                .path()
                .file_stem()
                .map(|s| s.to_string_lossy().to_string())
                .unwrap_or_default();
            if let Ok(content) = fs::read_to_string(entry.path()) {
                let trimmed = if content.len() > 2000 {
                    format!("{}...", &content[..2000])
                } else {
                    content.clone()
                };
                total_chars += trimmed.len();
                memories.push(format!("### {}\n{}", key, trimmed));
            }
        }
    }

    if memories.is_empty() {
        None
    } else {
        Some(format!(
            "## Project Memory (persistent across sessions)\n\
             Use memory_write to save important discoveries.\n\n{}",
            memories.join("\n\n")
        ))
    }
}
