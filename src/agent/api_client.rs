use futures_util::StreamExt;
use reqwest::Client;
use serde::{Deserialize, Serialize};
use serde_json::{json, Value};
use std::io::Write;
use std::time::{Duration, Instant};

/// Tool definition sent to the model API.
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

/// Response from the model API.
#[derive(Debug, Clone)]
pub struct ApiResponse {
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

pub struct ApiClient {
    client: Client,
    api_key: String,
    api_base_url: String,
    model: String,
}

impl ApiClient {
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
    ) -> Result<ApiResponse, String> {
        let start = Instant::now();

        // Use Messages API format (OpenRouter-compatible)
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

        // Parse Messages API response
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

        Ok(ApiResponse {
            text: text_parts.join("\n"),
            tool_calls,
            stop_reason,
            input_tokens,
            output_tokens,
            duration,
        })
    }

    /// Streaming variant: prints assistant text tokens to stderr as they arrive.
    pub async fn chat_streaming(
        &self,
        messages: &[Message],
        tools: &[ToolDef],
        system: &str,
    ) -> Result<ApiResponse, String> {
        let start = Instant::now();

        let api_messages: Vec<Value> = messages
            .iter()
            .map(|msg| {
                let content = match &msg.content {
                    MessageContent::Text(text) => json!(text),
                    MessageContent::Blocks(blocks) => {
                        let block_values: Vec<Value> = blocks
                            .iter()
                            .map(|b| match b {
                                ContentBlock::Text { text } => json!({"type": "text", "text": text}),
                                ContentBlock::ToolUse { id, name, input } => {
                                    json!({"type": "tool_use", "id": id, "name": name, "input": input})
                                }
                                ContentBlock::ToolResult { tool_use_id, content, is_error } => {
                                    let mut v = json!({"type": "tool_result", "tool_use_id": tool_use_id, "content": content});
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
                json!({"role": msg.role, "content": content})
            })
            .collect();

        let api_tools: Vec<Value> = tools
            .iter()
            .map(|t| json!({"name": t.name, "description": t.description, "input_schema": t.input_schema}))
            .collect();

        let mut body = json!({
            "model": self.model,
            "max_tokens": 16384,
            "messages": api_messages,
            "stream": true,
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
            let body_text = resp.text().await.unwrap_or_default();
            return Err(format!("API error {}: {}", status, &body_text[..body_text.len().min(500)]));
        }

        // Parse SSE stream
        let mut text_parts = Vec::new();
        let mut tool_calls: Vec<ToolCall> = Vec::new();
        let mut input_tokens: u64 = 0;
        let mut output_tokens: u64 = 0;
        let mut stop_reason = String::from("unknown");
        let mut current_tool_json = String::new();
        let mut current_tool_id = String::new();
        let mut current_tool_name = String::new();
        let mut in_tool_input = false;
        let mut stderr = std::io::stderr();

        let mut stream = resp.bytes_stream();
        let mut buffer = String::new();

        while let Some(chunk) = stream.next().await {
            let chunk = chunk.map_err(|e| format!("Stream error: {}", e))?;
            buffer.push_str(&String::from_utf8_lossy(&chunk));

            // Process complete SSE lines
            while let Some(line_end) = buffer.find('\n') {
                let line = buffer[..line_end].trim_end_matches('\r').to_string();
                buffer = buffer[line_end + 1..].to_string();

                if !line.starts_with("data: ") {
                    continue;
                }
                let data_str = &line[6..];
                if data_str == "[DONE]" {
                    continue;
                }

                let event: Value = match serde_json::from_str(data_str) {
                    Ok(v) => v,
                    Err(_) => continue,
                };

                let event_type = event["type"].as_str().unwrap_or("");

                match event_type {
                    "content_block_start" => {
                        let block = &event["content_block"];
                        if block["type"].as_str() == Some("tool_use") {
                            current_tool_id = block["id"].as_str().unwrap_or("").to_string();
                            current_tool_name = block["name"].as_str().unwrap_or("").to_string();
                            current_tool_json.clear();
                            in_tool_input = true;
                        }
                    }
                    "content_block_delta" => {
                        let delta = &event["delta"];
                        match delta["type"].as_str() {
                            Some("text_delta") => {
                                if let Some(text) = delta["text"].as_str() {
                                    text_parts.push(text.to_string());
                                    // Stream text to stderr for live display
                                    let _ = write!(stderr, "{}", text);
                                    let _ = stderr.flush();
                                }
                            }
                            Some("input_json_delta") => {
                                if let Some(partial_json) = delta["partial_json"].as_str() {
                                    current_tool_json.push_str(partial_json);
                                }
                            }
                            _ => {}
                        }
                    }
                    "content_block_stop" => {
                        if in_tool_input {
                            let input: Value = serde_json::from_str(&current_tool_json)
                                .unwrap_or(json!({}));
                            tool_calls.push(ToolCall {
                                id: current_tool_id.clone(),
                                name: current_tool_name.clone(),
                                input,
                            });
                            in_tool_input = false;
                        }
                    }
                    "message_delta" => {
                        if let Some(sr) = event["delta"]["stop_reason"].as_str() {
                            stop_reason = sr.to_string();
                        }
                        if let Some(u) = event["usage"]["output_tokens"].as_u64() {
                            output_tokens = u;
                        }
                    }
                    "message_start" => {
                        if let Some(u) = event["message"]["usage"]["input_tokens"].as_u64() {
                            input_tokens = u;
                        }
                    }
                    _ => {}
                }
            }
        }

        // Newline after streamed text
        if !text_parts.is_empty() {
            let _ = writeln!(stderr);
        }

        let duration = start.elapsed();

        Ok(ApiResponse {
            text: text_parts.join(""),
            tool_calls,
            stop_reason,
            input_tokens,
            output_tokens,
            duration,
        })
    }
}
