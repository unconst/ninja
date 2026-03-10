use serde_json::{json, Value};
use std::path::Path;

use crate::agent::api_client::ToolDef;

pub fn definitions() -> Vec<ToolDef> {
    vec![ToolDef {
        name: "think".to_string(),
        description: "Use this tool to think through complex decisions step-by-step before acting. \
                       This is useful when you need to analyze tool results carefully, plan multi-step \
                       operations, or reason about which approach to take. The thought is recorded but \
                       has no side effects."
            .to_string(),
        input_schema: json!({
            "type": "object",
            "properties": {
                "thought": {
                    "type": "string",
                    "description": "Your step-by-step reasoning or analysis"
                }
            },
            "required": ["thought"]
        }),
    }]
}

pub fn think(args: &Value, _workdir: &Path) -> Result<String, String> {
    let thought = args["thought"].as_str().unwrap_or("(empty thought)");
    Ok(format!("Thought recorded: {}", thought))
}
