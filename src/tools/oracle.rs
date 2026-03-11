use serde_json::{json, Value};
use std::path::Path;

use crate::agent::api_client::ToolDef;

pub fn definitions() -> Vec<ToolDef> {
    vec![ToolDef {
        name: "oracle".to_string(),
        description: "Get a second opinion from a different AI model. Use this when you're stuck, \
                       unsure about an approach, or want to verify your understanding of a complex \
                       codebase. The oracle sees your question but NOT your conversation history, \
                       so include all relevant context. Useful for: (1) verifying a fix approach, \
                       (2) understanding unfamiliar code patterns, (3) getting unstuck on a tricky \
                       edit. Keep questions focused — the oracle has a limited context window."
            .to_string(),
        input_schema: json!({
            "type": "object",
            "properties": {
                "question": {
                    "type": "string",
                    "description": "Your question with all necessary context. Include relevant code snippets, \
                                    file paths, and what you've tried so far."
                },
                "code_context": {
                    "type": "string",
                    "description": "Optional: relevant code snippets to include for context"
                }
            },
            "required": ["question"]
        }),
    }]
}

pub fn oracle(args: &Value, _workdir: &Path) -> Result<String, String> {
    let question = args["question"]
        .as_str()
        .ok_or("Missing 'question' argument")?;
    let code_context = args["code_context"].as_str().unwrap_or("");

    let api_key = std::env::var("OPENROUTER_API_KEY")
        .or_else(|_| std::env::var("ANTHROPIC_API_KEY"))
        .map_err(|_| "No API key found for oracle (need OPENROUTER_API_KEY or ANTHROPIC_API_KEY)")?;

    let api_base = std::env::var("ANTHROPIC_BASE_URL")
        .unwrap_or_else(|_| "https://openrouter.ai/api".to_string());

    // Use a fast model for the oracle — different from the main agent
    let oracle_model = std::env::var("NINJA_ORACLE_MODEL")
        .unwrap_or_else(|_| "anthropic/claude-sonnet-4-6".to_string());

    let mut prompt = format!("You are a code review oracle. Answer concisely and precisely.\n\n{}", question);
    if !code_context.is_empty() {
        prompt.push_str(&format!("\n\nRelevant code:\n```\n{}\n```", code_context));
    }

    // Make a simple blocking API call
    let client = reqwest::blocking::Client::new();
    let url = if api_base.contains("anthropic.com") {
        format!("{}/v1/messages", api_base.trim_end_matches('/'))
    } else {
        format!("{}/v1/chat/completions", api_base.trim_end_matches('/'))
    };

    let body = if api_base.contains("anthropic.com") {
        json!({
            "model": oracle_model,
            "max_tokens": 1024,
            "messages": [{"role": "user", "content": prompt}]
        })
    } else {
        json!({
            "model": oracle_model,
            "max_tokens": 1024,
            "messages": [{"role": "user", "content": prompt}]
        })
    };

    let mut request = client
        .post(&url)
        .header("Content-Type", "application/json")
        .json(&body);

    if api_base.contains("anthropic.com") {
        request = request
            .header("x-api-key", &api_key)
            .header("anthropic-version", "2023-06-01");
    } else {
        request = request.header("Authorization", format!("Bearer {}", api_key));
    }

    let response = request
        .timeout(std::time::Duration::from_secs(30))
        .send()
        .map_err(|e| format!("Oracle request failed: {}", e))?;

    let status = response.status();
    let body: Value = response
        .json()
        .map_err(|e| format!("Oracle response parse error: {}", e))?;

    if !status.is_success() {
        return Err(format!(
            "Oracle API error ({}): {}",
            status,
            body.to_string().chars().take(200).collect::<String>()
        ));
    }

    // Extract response text (handles both Anthropic and OpenAI formats)
    let text = if let Some(content) = body.get("content") {
        // Anthropic format
        content
            .as_array()
            .and_then(|arr| arr.first())
            .and_then(|block| block.get("text"))
            .and_then(|t| t.as_str())
            .unwrap_or("(no response)")
            .to_string()
    } else if let Some(choices) = body.get("choices") {
        // OpenAI format
        choices
            .as_array()
            .and_then(|arr| arr.first())
            .and_then(|choice| choice.get("message"))
            .and_then(|msg| msg.get("content"))
            .and_then(|c| c.as_str())
            .unwrap_or("(no response)")
            .to_string()
    } else {
        "(Oracle returned unexpected format)".to_string()
    };

    // Truncate long responses
    if text.len() > 4000 {
        Ok(format!("{}\n... (oracle response truncated)", &text[..4000]))
    } else {
        Ok(text)
    }
}
