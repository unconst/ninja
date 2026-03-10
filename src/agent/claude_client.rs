use reqwest::Client;
use serde::{Deserialize, Serialize};
use serde_json::{json, Value};
use std::time::{Duration, Instant};

/// Tool definition sent to the Claude API.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct ToolDef {
    pub name: String,
    pub description: String,
    pub input_schema: Value,
}

/// A message in the conversation.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct Message {
    pub role: String,
    pub content: MessageContent,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(untagged)]
pub enum MessageContent {
    Text(String),
    Blocks(Vec<ContentBlock>),
}

#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(tag = "type")]
pub enum ContentBlock {
    #[serde(rename = "text")]
    Text { text: String },
    #[serde(rename = "tool_use")]
    ToolUse {
        id: String,
        name: String,
        input: Value,
    },
    #[serde(rename = "tool_result")]
    ToolResult {
        tool_use_id: String,
        content: String,
        #[serde(skip_serializing_if = "Option::is_none")]
        is_error: Option<bool>,
    },
}

/// Response from the Claude API.
#[derive(Debug, Clone)]
pub struct ClaudeResponse {
    pub text: String,
    pub tool_calls: Vec<ToolCall>,
    pub stop_reason: String,
    pub input_tokens: u64,
    pub output_tokens: u64,
    pub duration: Duration,
}

/// A tool call from the model.
#[derive(Debug, Clone)]
pub struct ToolCall {
    pub id: String,
    pub name: String,
    pub input: Value,
}

pub struct ClaudeClient {
    client: Client,
    api_key: String,
    api_base_url: String,
    model: String,
}

impl ClaudeClient {
    pub fn new(api_key: &str, api_base_url: &str, model: &str) -> Self {
        Self {
            client: Client::new(),
            api_key: api_key.to_string(),
            api_base_url: api_base_url.to_string(),
            model: model.to_string(),
        }
    }

    pub async fn chat(
        &self,
        messages: &[Message],
        tools: &[ToolDef],
        system: &str,
    ) -> Result<ClaudeResponse, String> {
        let start = Instant::now();

        // Build request body (OpenRouter/OpenAI-compatible format)
        let mut oai_messages: Vec<Value> = Vec::new();

        if !system.is_empty() {
            oai_messages.push(json!({
                "role": "system",
                "content": system,
            }));
        }

        for msg in messages {
            match &msg.content {
                MessageContent::Text(text) => {
                    oai_messages.push(json!({
                        "role": msg.role,
                        "content": text,
                    }));
                }
                MessageContent::Blocks(blocks) => {
                    // Convert blocks to OpenAI format
                    let mut parts: Vec<Value> = Vec::new();
                    let mut tool_results = Vec::new();

                    for block in blocks {
                        match block {
                            ContentBlock::Text { text } => {
                                parts.push(json!({
                                    "type": "text",
                                    "text": text,
                                }));
                            }
                            ContentBlock::ToolUse { id: _, name, input } => {
                                // This becomes an assistant message with tool_calls
                                // Handle separately
                                parts.push(json!({
                                    "type": "text",
                                    "text": format!("[Tool call: {}({})]", name, input),
                                }));
                            }
                            ContentBlock::ToolResult { tool_use_id, content, is_error: _ } => {
                                tool_results.push(json!({
                                    "role": "tool",
                                    "tool_call_id": tool_use_id,
                                    "content": content,
                                }));
                            }
                        }
                    }

                    if !parts.is_empty() {
                        oai_messages.push(json!({
                            "role": msg.role,
                            "content": parts,
                        }));
                    }
                    oai_messages.extend(tool_results);
                }
            }
        }

        // Convert tools to OpenAI function format
        let oai_tools: Vec<Value> = tools.iter().map(|t| {
            json!({
                "type": "function",
                "function": {
                    "name": t.name,
                    "description": t.description,
                    "parameters": t.input_schema,
                }
            })
        }).collect();

        let mut body = json!({
            "model": self.model,
            "messages": oai_messages,
            "max_tokens": 4096,
        });

        if !oai_tools.is_empty() {
            body["tools"] = json!(oai_tools);
        }

        let url = format!("{}/v1/chat/completions", self.api_base_url.trim_end_matches('/'));

        let resp = self
            .client
            .post(&url)
            .header("Authorization", format!("Bearer {}", self.api_key))
            .header("Content-Type", "application/json")
            .json(&body)
            .send()
            .await
            .map_err(|e| format!("HTTP error: {}", e))?;

        if !resp.status().is_success() {
            let status = resp.status();
            let body = resp.text().await.unwrap_or_default();
            return Err(format!("API error {}: {}", status, &body[..body.len().min(500)]));
        }

        let data: Value = resp
            .json()
            .await
            .map_err(|e| format!("JSON parse error: {}", e))?;

        let duration = start.elapsed();

        // Parse response
        let choice = &data["choices"][0];
        let message = &choice["message"];
        let finish_reason = choice["finish_reason"]
            .as_str()
            .unwrap_or("stop")
            .to_string();

        let text = message["content"]
            .as_str()
            .unwrap_or("")
            .to_string();

        let mut tool_calls = Vec::new();
        if let Some(calls) = message["tool_calls"].as_array() {
            for call in calls {
                let func = &call["function"];
                tool_calls.push(ToolCall {
                    id: call["id"].as_str().unwrap_or("").to_string(),
                    name: func["name"].as_str().unwrap_or("").to_string(),
                    input: serde_json::from_str(
                        func["arguments"].as_str().unwrap_or("{}")
                    ).unwrap_or(json!({})),
                });
            }
        }

        let usage = &data["usage"];
        let input_tokens = usage["prompt_tokens"].as_u64().unwrap_or(0);
        let output_tokens = usage["completion_tokens"].as_u64().unwrap_or(0);

        Ok(ClaudeResponse {
            text,
            tool_calls,
            stop_reason: finish_reason,
            input_tokens,
            output_tokens,
            duration,
        })
    }
}
