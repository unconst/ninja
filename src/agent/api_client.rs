use colored::Colorize;
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
/// Internally we always use Anthropic-style representation:
/// - role: "user" | "assistant"
/// - content: Text or Blocks (with ToolUse / ToolResult)
/// The API client translates to/from OpenAI format when needed.
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
    /// Tokens used for extended thinking (Anthropic only, subset of output_tokens).
    pub thinking_tokens: u64,
    pub duration: Duration,
}

/// A tool call from the model.
#[derive(Debug, Clone)]
pub struct ToolCall {
    pub id: String,
    pub name: String,
    pub input: Value,
}

/// Which wire format to use for API communication.
#[derive(Debug, Clone, Copy, PartialEq)]
enum ApiFormat {
    /// Anthropic Messages API (/v1/messages)
    Anthropic,
    /// OpenAI Chat Completions API (/v1/chat/completions)
    OpenAI,
}

pub struct ApiClient {
    client: Client,
    api_key: String,
    api_base_url: String,
    model: String,
    /// Extended thinking budget in tokens (0 = disabled). Anthropic-only.
    thinking_budget: u64,
}

impl ApiClient {
    pub fn new(api_key: &str, api_base_url: &str, model: &str) -> Self {
        Self {
            client: Client::new(),
            api_key: api_key.to_string(),
            api_base_url: api_base_url.to_string(),
            model: model.to_string(),
            thinking_budget: 0,
        }
    }

    pub fn set_thinking_budget(&mut self, budget: u64) {
        self.thinking_budget = budget;
    }

    pub fn set_model(&mut self, model: &str) {
        self.model = model.to_string();
    }

    pub fn model(&self) -> &str {
        &self.model
    }

    /// Detect the API format to use based on model name and base URL.
    fn detect_format(&self) -> ApiFormat {
        // Direct Anthropic API
        if self.api_base_url.contains("anthropic.com") {
            return ApiFormat::Anthropic;
        }
        // Direct OpenAI API
        if self.api_base_url.contains("openai.com") {
            return ApiFormat::OpenAI;
        }
        // OpenRouter: detect from model prefix
        if self.model.starts_with("anthropic/") {
            ApiFormat::Anthropic
        } else {
            // openai/, google/, meta-llama/, mistralai/, deepseek/, etc.
            ApiFormat::OpenAI
        }
    }

    /// Build the API endpoint URL.
    fn endpoint_url(&self, format: ApiFormat) -> String {
        let base = self.api_base_url.trim_end_matches('/');
        match format {
            ApiFormat::Anthropic => format!("{}/v1/messages", base),
            ApiFormat::OpenAI => format!("{}/v1/chat/completions", base),
        }
    }

    // ── Anthropic format helpers ──

    fn build_anthropic_messages(&self, messages: &[Message]) -> Vec<Value> {
        messages
            .iter()
            .map(|msg| {
                let content = match &msg.content {
                    MessageContent::Text(text) => json!(text),
                    MessageContent::Blocks(blocks) => {
                        let block_values: Vec<Value> = blocks
                            .iter()
                            .map(|b| match b {
                                ContentBlock::Text { text } => {
                                    json!({"type": "text", "text": text})
                                }
                                ContentBlock::ToolUse { id, name, input } => {
                                    json!({"type": "tool_use", "id": id, "name": name, "input": input})
                                }
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
                json!({"role": msg.role, "content": content})
            })
            .collect()
    }

    fn build_anthropic_tools(&self, tools: &[ToolDef]) -> Vec<Value> {
        tools
            .iter()
            .map(|t| {
                json!({
                    "name": t.name,
                    "description": t.description,
                    "input_schema": t.input_schema,
                })
            })
            .collect()
    }

    fn parse_anthropic_response(&self, data: &Value, duration: Duration) -> ApiResponse {
        let stop_reason = data["stop_reason"]
            .as_str()
            .unwrap_or("unknown")
            .to_string();

        let mut text_parts = Vec::new();
        let mut tool_calls = Vec::new();

        if let Some(content) = data["content"].as_array() {
            for block in content {
                match block["type"].as_str() {
                    Some("thinking") => {
                        // Extended thinking block — we log but don't include in text output
                    }
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
        // Anthropic doesn't expose a separate thinking token count in usage;
        // thinking tokens are included in output_tokens. We set 0 here.
        let thinking_tokens = 0u64;

        ApiResponse {
            text: text_parts.join("\n"),
            tool_calls,
            stop_reason,
            input_tokens,
            output_tokens,
            thinking_tokens,
            duration,
        }
    }

    // ── OpenAI format helpers ──

    /// Convert internal Anthropic-style messages to OpenAI Chat Completions format.
    /// Key differences:
    /// - System prompt is a separate message with role "system" (handled by caller)
    /// - Assistant tool calls use `tool_calls` array with `function` objects
    /// - Tool results use role "tool" with `tool_call_id`
    fn build_openai_messages(&self, messages: &[Message], system: &str) -> Vec<Value> {
        let mut openai_msgs = Vec::new();

        // System message first
        if !system.is_empty() {
            openai_msgs.push(json!({"role": "system", "content": system}));
        }

        for msg in messages {
            match &msg.content {
                MessageContent::Text(text) => {
                    openai_msgs.push(json!({"role": msg.role, "content": text}));
                }
                MessageContent::Blocks(blocks) => {
                    if msg.role == "assistant" {
                        // Assistant message with possible tool calls
                        let mut text_parts = Vec::new();
                        let mut oai_tool_calls = Vec::new();

                        for block in blocks {
                            match block {
                                ContentBlock::Text { text } => {
                                    text_parts.push(text.clone());
                                }
                                ContentBlock::ToolUse { id, name, input } => {
                                    oai_tool_calls.push(json!({
                                        "id": id,
                                        "type": "function",
                                        "function": {
                                            "name": name,
                                            "arguments": input.to_string(),
                                        }
                                    }));
                                }
                                ContentBlock::ToolResult { .. } => {
                                    // Tool results don't go in assistant messages
                                }
                            }
                        }

                        let content = if text_parts.is_empty() {
                            Value::Null
                        } else {
                            json!(text_parts.join("\n"))
                        };

                        if oai_tool_calls.is_empty() {
                            openai_msgs.push(json!({
                                "role": "assistant",
                                "content": content,
                            }));
                        } else {
                            openai_msgs.push(json!({
                                "role": "assistant",
                                "content": content,
                                "tool_calls": oai_tool_calls,
                            }));
                        }
                    } else {
                        // User message — could contain tool results
                        let mut has_tool_results = false;
                        let mut text_parts = Vec::new();

                        for block in blocks {
                            match block {
                                ContentBlock::ToolResult {
                                    tool_use_id,
                                    content,
                                    ..
                                } => {
                                    has_tool_results = true;
                                    openai_msgs.push(json!({
                                        "role": "tool",
                                        "tool_call_id": tool_use_id,
                                        "content": content,
                                    }));
                                }
                                ContentBlock::Text { text } => {
                                    text_parts.push(text.clone());
                                }
                                _ => {}
                            }
                        }

                        // If there were also text blocks alongside tool results, add a user msg
                        if !text_parts.is_empty() && !has_tool_results {
                            openai_msgs.push(json!({
                                "role": "user",
                                "content": text_parts.join("\n"),
                            }));
                        }
                    }
                }
            }
        }

        openai_msgs
    }

    fn build_openai_tools(&self, tools: &[ToolDef]) -> Vec<Value> {
        tools
            .iter()
            .map(|t| {
                json!({
                    "type": "function",
                    "function": {
                        "name": t.name,
                        "description": t.description,
                        "parameters": t.input_schema,
                    }
                })
            })
            .collect()
    }

    fn parse_openai_response(&self, data: &Value, duration: Duration) -> ApiResponse {
        let choice = &data["choices"][0];
        let message = &choice["message"];

        let stop_reason = choice["finish_reason"]
            .as_str()
            .unwrap_or("unknown")
            .to_string();

        let text = message["content"]
            .as_str()
            .unwrap_or("")
            .to_string();

        let mut tool_calls = Vec::new();
        if let Some(tcs) = message["tool_calls"].as_array() {
            for tc in tcs {
                let id = tc["id"].as_str().unwrap_or("").to_string();
                let name = tc["function"]["name"]
                    .as_str()
                    .unwrap_or("")
                    .to_string();
                let args_str = tc["function"]["arguments"]
                    .as_str()
                    .unwrap_or("{}");
                let input: Value =
                    serde_json::from_str(args_str).unwrap_or(json!({}));
                tool_calls.push(ToolCall { id, name, input });
            }
        }

        let usage = &data["usage"];
        let input_tokens = usage["prompt_tokens"].as_u64().unwrap_or(0);
        let output_tokens = usage["completion_tokens"].as_u64().unwrap_or(0);

        ApiResponse {
            text,
            tool_calls,
            stop_reason,
            input_tokens,
            output_tokens,
            thinking_tokens: 0,
            duration,
        }
    }

    // ── Public API ──

    pub async fn chat(
        &self,
        messages: &[Message],
        tools: &[ToolDef],
        system: &str,
    ) -> Result<ApiResponse, String> {
        let start = Instant::now();
        let format = self.detect_format();
        let url = self.endpoint_url(format);

        let body = match format {
            ApiFormat::Anthropic => {
                let api_messages = self.build_anthropic_messages(messages);
                let api_tools = self.build_anthropic_tools(tools);
                // When thinking is enabled, max_tokens must be > budget_tokens
                let max_tokens = if self.thinking_budget > 0 {
                    self.thinking_budget + 16384
                } else {
                    16384
                };
                let mut body = json!({
                    "model": self.model,
                    "max_tokens": max_tokens,
                    "messages": api_messages,
                });
                if !system.is_empty() {
                    // Use structured system prompt with cache_control for prompt caching
                    body["system"] = json!([{
                        "type": "text",
                        "text": system,
                        "cache_control": {"type": "ephemeral"}
                    }]);
                }
                if !api_tools.is_empty() {
                    // Mark last tool with cache_control for caching the full tool list
                    let mut cached_tools = api_tools.clone();
                    if let Some(last) = cached_tools.last_mut() {
                        last["cache_control"] = json!({"type": "ephemeral"});
                    }
                    body["tools"] = json!(cached_tools);
                }
                // Extended thinking support
                if self.thinking_budget > 0 {
                    body["thinking"] = json!({
                        "type": "enabled",
                        "budget_tokens": self.thinking_budget
                    });
                }
                body
            }
            ApiFormat::OpenAI => {
                let api_messages = self.build_openai_messages(messages, system);
                let api_tools = self.build_openai_tools(tools);
                let mut body = json!({
                    "model": self.model,
                    "max_tokens": 16384,
                    "messages": api_messages,
                });
                if !api_tools.is_empty() {
                    body["tools"] = json!(api_tools);
                }
                body
            }
        };

        let mut req = self
            .client
            .post(&url)
            .header("Content-Type", "application/json");

        req = match format {
            ApiFormat::Anthropic => {
                let mut r = req
                    .header("x-api-key", &self.api_key)
                    .header("anthropic-version", "2023-06-01")
                    .header("anthropic-beta", "prompt-caching-2024-07-31");
                if self.thinking_budget > 0 {
                    r = r.header("anthropic-beta", "interleaved-thinking-2025-05-14");
                }
                r
            }
            ApiFormat::OpenAI => req.header("Authorization", format!("Bearer {}", self.api_key)),
        };

        let resp = req
            .json(&body)
            .send()
            .await
            .map_err(|e| format!("HTTP error: {}", e))?;

        if !resp.status().is_success() {
            let status = resp.status();
            let body = resp.text().await.unwrap_or_default();
            let end = body
                .char_indices()
                .nth(500)
                .map(|(i, _)| i)
                .unwrap_or(body.len());
            return Err(format!("API error {}: {}", status, &body[..end]));
        }

        let data: Value = resp
            .json()
            .await
            .map_err(|e| format!("JSON parse error: {}", e))?;

        let duration = start.elapsed();

        Ok(match format {
            ApiFormat::Anthropic => self.parse_anthropic_response(&data, duration),
            ApiFormat::OpenAI => self.parse_openai_response(&data, duration),
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
        let format = self.detect_format();
        let url = self.endpoint_url(format);

        let body = match format {
            ApiFormat::Anthropic => {
                let api_messages = self.build_anthropic_messages(messages);
                let api_tools = self.build_anthropic_tools(tools);
                let max_tokens = if self.thinking_budget > 0 {
                    self.thinking_budget + 16384
                } else {
                    16384
                };
                let mut body = json!({
                    "model": self.model,
                    "max_tokens": max_tokens,
                    "messages": api_messages,
                    "stream": true,
                });
                if !system.is_empty() {
                    body["system"] = json!([{
                        "type": "text",
                        "text": system,
                        "cache_control": {"type": "ephemeral"}
                    }]);
                }
                if !api_tools.is_empty() {
                    let mut cached_tools = api_tools.clone();
                    if let Some(last) = cached_tools.last_mut() {
                        last["cache_control"] = json!({"type": "ephemeral"});
                    }
                    body["tools"] = json!(cached_tools);
                }
                if self.thinking_budget > 0 {
                    body["thinking"] = json!({
                        "type": "enabled",
                        "budget_tokens": self.thinking_budget
                    });
                }
                body
            }
            ApiFormat::OpenAI => {
                let api_messages = self.build_openai_messages(messages, system);
                let api_tools = self.build_openai_tools(tools);
                let mut body = json!({
                    "model": self.model,
                    "max_tokens": 16384,
                    "messages": api_messages,
                    "stream": true,
                    "stream_options": {"include_usage": true},
                });
                if !api_tools.is_empty() {
                    body["tools"] = json!(api_tools);
                }
                body
            }
        };

        let mut req = self
            .client
            .post(&url)
            .header("Content-Type", "application/json");

        req = match format {
            ApiFormat::Anthropic => {
                let mut r = req
                    .header("x-api-key", &self.api_key)
                    .header("anthropic-version", "2023-06-01")
                    .header("anthropic-beta", "prompt-caching-2024-07-31");
                if self.thinking_budget > 0 {
                    r = r.header("anthropic-beta", "interleaved-thinking-2025-05-14");
                }
                r
            }
            ApiFormat::OpenAI => req.header("Authorization", format!("Bearer {}", self.api_key)),
        };

        let resp = req
            .json(&body)
            .send()
            .await
            .map_err(|e| format!("HTTP error: {}", e))?;

        if !resp.status().is_success() {
            let status = resp.status();
            let body_text = resp.text().await.unwrap_or_default();
            let end = body_text
                .char_indices()
                .nth(500)
                .map(|(i, _)| i)
                .unwrap_or(body_text.len());
            return Err(format!("API error {}: {}", status, &body_text[..end]));
        }

        match format {
            ApiFormat::Anthropic => self.stream_anthropic(resp, start).await,
            ApiFormat::OpenAI => self.stream_openai(resp, start).await,
        }
    }

    // ── Anthropic streaming ──

    async fn stream_anthropic(
        &self,
        resp: reqwest::Response,
        start: Instant,
    ) -> Result<ApiResponse, String> {
        let mut text_parts = Vec::new();
        let mut tool_calls: Vec<ToolCall> = Vec::new();
        let mut input_tokens: u64 = 0;
        let mut output_tokens: u64 = 0;
        let thinking_tokens: u64 = 0;
        let mut stop_reason = String::from("unknown");
        let mut current_tool_json = String::new();
        let mut current_tool_id = String::new();
        let mut current_tool_name = String::new();
        let mut in_tool_input = false;
        let mut in_thinking = false;
        let mut thinking_started = false;
        let mut stderr = std::io::stderr();

        let mut stream = resp.bytes_stream();
        let mut buffer = String::new();

        while let Some(chunk) = stream.next().await {
            let chunk = chunk.map_err(|e| format!("Stream error: {}", e))?;
            buffer.push_str(&String::from_utf8_lossy(&chunk));

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
                        match block["type"].as_str() {
                            Some("tool_use") => {
                                current_tool_id =
                                    block["id"].as_str().unwrap_or("").to_string();
                                current_tool_name =
                                    block["name"].as_str().unwrap_or("").to_string();
                                current_tool_json.clear();
                                in_tool_input = true;
                            }
                            Some("thinking") => {
                                in_thinking = true;
                                if !thinking_started {
                                    thinking_started = true;
                                    let _ = write!(stderr, "{}", "[thinking...] ".dimmed());
                                    let _ = stderr.flush();
                                }
                            }
                            _ => {}
                        }
                    }
                    "content_block_delta" => {
                        let delta = &event["delta"];
                        match delta["type"].as_str() {
                            Some("thinking_delta") => {
                                // Thinking deltas — count chars as a proxy, actual tokens from usage
                            }
                            Some("text_delta") => {
                                if let Some(text) = delta["text"].as_str() {
                                    text_parts.push(text.to_string());
                                    let _ = write!(stderr, "{}", text);
                                    let _ = stderr.flush();
                                }
                            }
                            Some("input_json_delta") => {
                                if let Some(partial_json) =
                                    delta["partial_json"].as_str()
                                {
                                    current_tool_json.push_str(partial_json);
                                }
                            }
                            _ => {}
                        }
                    }
                    "content_block_stop" => {
                        if in_tool_input {
                            let input: Value =
                                serde_json::from_str(&current_tool_json)
                                    .unwrap_or(json!({}));
                            tool_calls.push(ToolCall {
                                id: current_tool_id.clone(),
                                name: current_tool_name.clone(),
                                input,
                            });
                            in_tool_input = false;
                        }
                        if in_thinking {
                            in_thinking = false;
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
                        if let Some(u) =
                            event["message"]["usage"]["input_tokens"].as_u64()
                        {
                            input_tokens = u;
                        }
                    }
                    _ => {}
                }
            }
        }

        if !text_parts.is_empty() || thinking_started {
            let _ = writeln!(stderr);
        }

        Ok(ApiResponse {
            text: text_parts.join(""),
            tool_calls,
            stop_reason,
            input_tokens,
            output_tokens,
            thinking_tokens,
            duration: start.elapsed(),
        })
    }

    // ── OpenAI streaming ──

    async fn stream_openai(
        &self,
        resp: reqwest::Response,
        start: Instant,
    ) -> Result<ApiResponse, String> {
        let mut text_parts = Vec::new();
        let mut input_tokens: u64 = 0;
        let mut output_tokens: u64 = 0;
        let mut stop_reason = String::from("unknown");
        let mut stderr = std::io::stderr();

        // OpenAI streams tool calls by index; accumulate per-index state
        let mut tc_ids: Vec<String> = Vec::new();
        let mut tc_names: Vec<String> = Vec::new();
        let mut tc_args: Vec<String> = Vec::new();

        let mut stream = resp.bytes_stream();
        let mut buffer = String::new();

        while let Some(chunk) = stream.next().await {
            let chunk = chunk.map_err(|e| format!("Stream error: {}", e))?;
            buffer.push_str(&String::from_utf8_lossy(&chunk));

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

                // Usage chunk (sent with stream_options.include_usage)
                if let Some(usage) = event["usage"].as_object() {
                    if let Some(pt) = usage.get("prompt_tokens").and_then(|v| v.as_u64()) {
                        input_tokens = pt;
                    }
                    if let Some(ct) = usage.get("completion_tokens").and_then(|v| v.as_u64()) {
                        output_tokens = ct;
                    }
                }

                let delta = &event["choices"][0]["delta"];
                if delta.is_null() {
                    // Final chunk with usage only
                    if let Some(fr) = event["choices"][0]["finish_reason"].as_str() {
                        if fr != "null" {
                            stop_reason = fr.to_string();
                        }
                    }
                    continue;
                }

                // Finish reason
                if let Some(fr) = event["choices"][0]["finish_reason"].as_str() {
                    stop_reason = fr.to_string();
                }

                // Text content
                if let Some(content) = delta["content"].as_str() {
                    text_parts.push(content.to_string());
                    let _ = write!(stderr, "{}", content);
                    let _ = stderr.flush();
                }

                // Tool calls (streamed by index)
                if let Some(tcs) = delta["tool_calls"].as_array() {
                    for tc in tcs {
                        let idx = tc["index"].as_u64().unwrap_or(0) as usize;

                        // Grow vectors if needed
                        while tc_ids.len() <= idx {
                            tc_ids.push(String::new());
                            tc_names.push(String::new());
                            tc_args.push(String::new());
                        }

                        if let Some(id) = tc["id"].as_str() {
                            tc_ids[idx] = id.to_string();
                        }
                        if let Some(name) = tc["function"]["name"].as_str() {
                            tc_names[idx] = name.to_string();
                        }
                        if let Some(args) = tc["function"]["arguments"].as_str() {
                            tc_args[idx].push_str(args);
                        }
                    }
                }
            }
        }

        if !text_parts.is_empty() {
            let _ = writeln!(stderr);
        }

        // Build final tool calls
        let mut tool_calls = Vec::new();
        for i in 0..tc_ids.len() {
            if !tc_names[i].is_empty() {
                let input: Value =
                    serde_json::from_str(&tc_args[i]).unwrap_or(json!({}));
                tool_calls.push(ToolCall {
                    id: tc_ids[i].clone(),
                    name: tc_names[i].clone(),
                    input,
                });
            }
        }

        Ok(ApiResponse {
            text: text_parts.join(""),
            tool_calls,
            stop_reason,
            input_tokens,
            output_tokens,
            thinking_tokens: 0,
            duration: start.elapsed(),
        })
    }
}
