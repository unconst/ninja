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

        // Use Anthropic Messages API format (native)
        let api_messages: Vec<Value> = messages
            .iter()
            .map(|msg| {
                let content = match &msg.content {
                    MessageContent::Text(text) => json!(text),
                    MessageContent::Blocks(blocks) => {
                        let block_values: Vec<Value> = blocks
                            .iter()
                            .map(|b| match b {
                                ContentBlock::Text { text } => json!({
                                    "type": "text",
                                    "text": text,
                                }),
                                ContentBlock::ToolUse { id, name, input } => json!({
                                    "type": "tool_use",
                                    "id": id,
                                    "name": name,
                                    "input": input,
                                }),
                                ContentBlock::ToolResult {
                                    tool_use_id,
                                    content,
                                    is_error,
                                } => {
                                    let mut v = json!({
                                        "type": "tool_result",
                                        "tool_use_id": tool_use_id,
                                        "content": content,
                                    });
                                    if let Some(true) = is_error {
                                        v["is_error"] = json!(true);
                                    }
                                    v
                                }
                            })
                            .collect();
                        json!(block_values)
                    }
                };
                json!({
                    "role": msg.role,
                    "content": content,
                })
            })
            .collect();

        let api_tools: Vec<Value> = tools
            .iter()
            .map(|t| {
                json!({
                    "name": t.name,
                    "description": t.description,
                    "input_schema": t.input_schema,
                })
            })
            .collect();

        let mut body = json!({
            "model": self.model,
            "max_tokens": 16384,
            "messages": api_messages,
        });

        if !system.is_empty() {
            body["system"] = json!(system);
        }
        if !api_tools.is_empty() {
            body["tools"] = json!(api_tools);
        }

        let url = format!("{}/v1/messages", self.api_base_url.trim_end_matches('/'));

        let resp = self
            .client
            .post(&url)
            .header("x-api-key", &self.api_key)
            .header("anthropic-version", "2023-06-01")
            .header("Content-Type", "application/json")
            .json(&body)
            .send()
            .await
            .map_err(|e| format!("HTTP error: {}", e))?;

        if !resp.status().is_success() {
            let status = resp.status();
            let body = resp.text().await.unwrap_or_default();
            return Err(format!(
                "API error {}: {}",
                status,
                &body[..body.len().min(500)]
            ));
        }

        let data: Value = resp
            .json()
            .await
            .map_err(|e| format!("JSON parse error: {}", e))?;

        let duration = start.elapsed();

        // Parse Anthropic Messages API response
        let stop_reason = data["stop_reason"]
            .as_str()
            .unwrap_or("unknown")
            .to_string();

        let mut text_parts = Vec::new();
        let mut tool_calls = Vec::new();

        if let Some(content) = data["content"].as_array() {
            for block in content {
                match block["type"].as_str() {
                    Some("text") => {
                        if let Some(t) = block["text"].as_str() {
                            text_parts.push(t.to_string());
                        }
                    }
                    Some("tool_use") => {
                        tool_calls.push(ToolCall {
                            id: block["id"].as_str().unwrap_or("").to_string(),
                            name: block["name"].as_str().unwrap_or("").to_string(),
                            input: block["input"].clone(),
                        });
                    }
                    _ => {}
                }
            }
        }

        let usage = &data["usage"];
        let input_tokens = usage["input_tokens"].as_u64().unwrap_or(0);
        let output_tokens = usage["output_tokens"].as_u64().unwrap_or(0);

        Ok(ClaudeResponse {
            text: text_parts.join("\n"),
            tool_calls,
            stop_reason,
            input_tokens,
            output_tokens,
            duration,
        })
    }
}