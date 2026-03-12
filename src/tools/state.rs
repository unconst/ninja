use serde_json::{json, Value};
use std::path::Path;

use crate::agent::api_client::ToolDef;

const STATE_FILE: &str = "/tmp/.ninja_state.json";

pub fn definitions() -> Vec<ToolDef> {
    vec![
        ToolDef {
            name: "state_read".to_string(),
            description: "Read the current RLM state object. The state tracks your plan, subtasks, \
                           observations, and thread results. Use this to check progress, find pending \
                           subtasks, and decide what to do next. Returns the full state as JSON."
                .to_string(),
            input_schema: json!({
                "type": "object",
                "properties": {},
                "required": []
            }),
        },
        ToolDef {
            name: "state_write".to_string(),
            description: "Update the RLM state object. Use this to:\n\
                           - Update your plan after evaluating thread results\n\
                           - Mark subtasks as done/failed/pending\n\
                           - Record observations and strategy changes\n\
                           - Track test results and confidence\n\n\
                           You can update specific fields (merge) or write the entire state.\n\n\
                           Standard state schema:\n\
                           ```json\n\
                           {\n\
                             \"plan\": \"High-level strategy\",\n\
                             \"subtasks\": [{\"id\": 1, \"desc\": \"...\", \"files\": [...], \
                               \"status\": \"pending|done|failed\", \"result\": \"...\"}],\n\
                             \"observations\": [\"key findings...\"],\n\
                             \"test_results\": {\"summary\": \"...\", \"pass\": 0, \"fail\": 0},\n\
                             \"iteration\": 1,\n\
                             \"strategy_changes\": [\"what changed and why\"]\n\
                           }\n\
                           ```"
                .to_string(),
            input_schema: json!({
                "type": "object",
                "properties": {
                    "state": {
                        "type": "object",
                        "description": "The state object to write. Merges with existing state — \
                                        fields you provide overwrite existing fields, fields you \
                                        omit are preserved."
                    },
                    "replace": {
                        "type": "boolean",
                        "description": "If true, replace the entire state instead of merging (default: false)"
                    }
                },
                "required": ["state"]
            }),
        },
    ]
}

pub fn state_read(_args: &Value, _workdir: &Path) -> Result<String, String> {
    match std::fs::read_to_string(STATE_FILE) {
        Ok(content) => {
            // Validate it's valid JSON
            match serde_json::from_str::<Value>(&content) {
                Ok(state) => Ok(serde_json::to_string_pretty(&state).unwrap_or(content)),
                Err(_) => Ok(content), // Return raw even if invalid
            }
        }
        Err(_) => {
            // No state file yet — return empty state template
            let empty_state = json!({
                "plan": "",
                "subtasks": [],
                "observations": [],
                "test_results": null,
                "iteration": 0,
                "strategy_changes": []
            });
            Ok(serde_json::to_string_pretty(&empty_state).unwrap())
        }
    }
}

pub fn state_write(args: &Value, _workdir: &Path) -> Result<String, String> {
    let new_state = args
        .get("state")
        .ok_or("Missing 'state' argument")?;

    let replace = args["replace"].as_bool().unwrap_or(false);

    let final_state = if replace {
        new_state.clone()
    } else {
        // Merge: read existing, overlay new fields
        let existing = std::fs::read_to_string(STATE_FILE)
            .ok()
            .and_then(|s| serde_json::from_str::<Value>(&s).ok())
            .unwrap_or_else(|| json!({}));

        merge_json(&existing, new_state)
    };

    let content = serde_json::to_string_pretty(&final_state)
        .map_err(|e| format!("Failed to serialize state: {}", e))?;

    std::fs::write(STATE_FILE, &content)
        .map_err(|e| format!("Failed to write state file: {}", e))?;

    // Also write a human-readable plan file for backward compatibility
    if let Some(plan) = final_state.get("plan").and_then(|v| v.as_str()) {
        if !plan.is_empty() {
            let mut plan_content = format!("# Plan\n{}\n\n", plan);

            if let Some(subtasks) = final_state.get("subtasks").and_then(|v| v.as_array()) {
                plan_content.push_str("# Subtasks\n");
                for st in subtasks {
                    let status = st.get("status").and_then(|v| v.as_str()).unwrap_or("?");
                    let desc = st.get("desc").and_then(|v| v.as_str()).unwrap_or("?");
                    let marker = match status {
                        "done" => "[x]",
                        "failed" => "[!]",
                        _ => "[ ]",
                    };
                    plan_content.push_str(&format!("- {} {}\n", marker, desc));
                }
            }

            let _ = std::fs::write("/tmp/.ninja_plan.md", &plan_content);
        }
    }

    Ok(format!("State updated. {} top-level fields.",
        final_state.as_object().map(|o| o.len()).unwrap_or(0)))
}

/// Deep merge two JSON values. New fields override existing ones.
/// Arrays are replaced (not appended). Objects are recursively merged.
fn merge_json(base: &Value, overlay: &Value) -> Value {
    match (base, overlay) {
        (Value::Object(base_map), Value::Object(overlay_map)) => {
            let mut result = base_map.clone();
            for (key, value) in overlay_map {
                if let Some(existing) = result.get(key) {
                    // Recursively merge objects, replace everything else
                    if existing.is_object() && value.is_object() {
                        result.insert(key.clone(), merge_json(existing, value));
                    } else {
                        result.insert(key.clone(), value.clone());
                    }
                } else {
                    result.insert(key.clone(), value.clone());
                }
            }
            Value::Object(result)
        }
        // For non-objects, overlay wins
        (_, overlay) => overlay.clone(),
    }
}

/// Read the state file for use in phase checks and system injections.
/// Returns None if no state file exists or it's empty.
pub fn read_state_for_injection() -> Option<Value> {
    std::fs::read_to_string(STATE_FILE)
        .ok()
        .and_then(|s| serde_json::from_str::<Value>(&s).ok())
        .filter(|v| !v.as_object().map(|o| o.is_empty()).unwrap_or(true))
}

/// Generate a compact summary of the state for injection into phase checks.
pub fn summarize_state() -> Option<String> {
    let state = read_state_for_injection()?;

    let mut summary = String::new();

    if let Some(subtasks) = state.get("subtasks").and_then(|v| v.as_array()) {
        if !subtasks.is_empty() {
            let done = subtasks.iter().filter(|s| s.get("status").and_then(|v| v.as_str()) == Some("done")).count();
            let failed = subtasks.iter().filter(|s| s.get("status").and_then(|v| v.as_str()) == Some("failed")).count();
            let pending = subtasks.iter().filter(|s| s.get("status").and_then(|v| v.as_str()) == Some("pending")).count();
            let in_progress = subtasks.len() - done - failed - pending;

            summary.push_str(&format!(
                "Subtask progress: {}/{} done, {} failed, {} pending, {} in-progress\n",
                done, subtasks.len(), failed, pending, in_progress
            ));

            // List pending subtasks
            let pending_tasks: Vec<String> = subtasks.iter()
                .filter(|s| s.get("status").and_then(|v| v.as_str()) != Some("done"))
                .filter_map(|s| s.get("desc").and_then(|v| v.as_str()).map(|d| d.to_string()))
                .collect();
            if !pending_tasks.is_empty() {
                summary.push_str("Remaining:\n");
                for t in pending_tasks.iter().take(10) {
                    summary.push_str(&format!("  - {}\n", t));
                }
            }
        }
    }

    if let Some(observations) = state.get("observations").and_then(|v| v.as_array()) {
        if !observations.is_empty() {
            summary.push_str(&format!("Observations ({}):\n", observations.len()));
            for obs in observations.iter().rev().take(3) {
                if let Some(s) = obs.as_str() {
                    summary.push_str(&format!("  - {}\n", s));
                }
            }
        }
    }

    if let Some(changes) = state.get("strategy_changes").and_then(|v| v.as_array()) {
        if let Some(last) = changes.last().and_then(|v| v.as_str()) {
            summary.push_str(&format!("Latest strategy change: {}\n", last));
        }
    }

    if summary.is_empty() {
        None
    } else {
        Some(summary)
    }
}
