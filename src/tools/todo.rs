use serde_json::{json, Value};
use std::path::Path;

use crate::agent::api_client::ToolDef;

pub fn definitions() -> Vec<ToolDef> {
    vec![ToolDef {
        name: "todo_write".to_string(),
        description: "Create or update a structured task list. Use this to track progress on \
                       multi-step tasks. Each todo has a content (imperative form), activeForm \
                       (present continuous), and status (pending/in_progress/completed). \
                       Send the FULL todo list each time (not just changes)."
            .to_string(),
        input_schema: json!({
            "type": "object",
            "properties": {
                "todos": {
                    "type": "array",
                    "description": "The complete todo list (replaces any existing list)",
                    "items": {
                        "type": "object",
                        "properties": {
                            "content": {
                                "type": "string",
                                "description": "Task description in imperative form (e.g., 'Fix authentication bug')"
                            },
                            "activeForm": {
                                "type": "string",
                                "description": "Task description in present continuous form (e.g., 'Fixing authentication bug')"
                            },
                            "status": {
                                "type": "string",
                                "enum": ["pending", "in_progress", "completed"],
                                "description": "Task status"
                            }
                        },
                        "required": ["content", "status"]
                    }
                }
            },
            "required": ["todos"]
        }),
    }]
}

pub fn todo_write(args: &Value, _workdir: &Path) -> Result<String, String> {
    let todos = args["todos"]
        .as_array()
        .ok_or("Missing 'todos' array argument")?;

    let mut pending = 0;
    let mut in_progress = 0;
    let mut completed = 0;

    for todo in todos {
        match todo["status"].as_str().unwrap_or("pending") {
            "pending" => pending += 1,
            "in_progress" => in_progress += 1,
            "completed" => completed += 1,
            _ => pending += 1,
        }
    }

    let total = todos.len();
    let mut summary = format!(
        "Todo list updated: {} total ({} completed, {} in progress, {} pending)",
        total, completed, in_progress, pending
    );

    // Show current in-progress items
    for todo in todos {
        if todo["status"].as_str() == Some("in_progress") {
            if let Some(active) = todo["activeForm"].as_str() {
                summary.push_str(&format!("\n  → {}", active));
            } else if let Some(content) = todo["content"].as_str() {
                summary.push_str(&format!("\n  → {}", content));
            }
        }
    }

    Ok(summary)
}
