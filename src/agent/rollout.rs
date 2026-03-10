use chrono::{DateTime, Utc};
use serde::{Deserialize, Serialize};
use std::time::Duration;

/// A single entry in the rollout log.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct RolloutEntry {
    /// Timestamp of this entry
    pub timestamp: DateTime<Utc>,
    /// Type of entry: "user", "assistant", "tool_call", "tool_result", "error"
    pub entry_type: String,
    /// The content
    pub content: String,
    /// Token counts for LLM calls
    #[serde(skip_serializing_if = "Option::is_none")]
    pub input_tokens: Option<u64>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub output_tokens: Option<u64>,
    /// Duration of this step
    #[serde(skip_serializing_if = "Option::is_none")]
    pub duration_ms: Option<u64>,
    /// Tool name for tool_call/tool_result entries
    #[serde(skip_serializing_if = "Option::is_none")]
    pub tool_name: Option<String>,
    /// Model used
    #[serde(skip_serializing_if = "Option::is_none")]
    pub model: Option<String>,
}

/// Complete rollout of an agent run.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct Rollout {
    /// All entries in order
    pub entries: Vec<RolloutEntry>,
    /// Whether the run succeeded
    pub success: bool,
    /// Final result text
    pub final_result: Option<String>,
    /// Total duration
    pub total_duration_ms: u64,
    /// Total input tokens
    pub total_input_tokens: u64,
    /// Total output tokens
    pub total_output_tokens: u64,
    /// Number of tool calls made
    pub tool_call_count: u64,
    /// Number of LLM iterations
    pub iteration_count: u64,
    /// Model used
    pub model: String,
    /// Estimated cost in USD (based on model pricing)
    pub estimated_cost_usd: f64,
}

impl Rollout {
    pub fn new(model: &str) -> Self {
        Self {
            entries: Vec::new(),
            success: false,
            final_result: None,
            total_duration_ms: 0,
            total_input_tokens: 0,
            total_output_tokens: 0,
            tool_call_count: 0,
            iteration_count: 0,
            model: model.to_string(),
            estimated_cost_usd: 0.0,
        }
    }

    /// Estimate cost based on model and token counts.
    /// Prices are per 1M tokens (approximate OpenRouter prices).
    pub fn estimate_cost(&mut self) {
        let (input_price, output_price) = match self.model.as_str() {
            m if m.contains("opus") => (15.0, 75.0),
            m if m.contains("sonnet") => (3.0, 15.0),
            m if m.contains("haiku") => (0.25, 1.25),
            m if m.contains("gpt-4o") => (2.5, 10.0),
            m if m.contains("gpt-4") => (10.0, 30.0),
            m if m.contains("gpt-3.5") => (0.5, 1.5),
            m if m.contains("deepseek") => (0.14, 0.28),
            _ => (3.0, 15.0), // default to sonnet-level pricing
        };
        self.estimated_cost_usd =
            (self.total_input_tokens as f64 * input_price / 1_000_000.0)
            + (self.total_output_tokens as f64 * output_price / 1_000_000.0);
    }

    pub fn add_entry(&mut self, entry: RolloutEntry) {
        if let Some(input) = entry.input_tokens {
            self.total_input_tokens += input;
        }
        if let Some(output) = entry.output_tokens {
            self.total_output_tokens += output;
        }
        if entry.entry_type == "tool_call" {
            self.tool_call_count += 1;
        }
        self.entries.push(entry);
    }

    pub fn log_user(&mut self, content: &str) {
        self.add_entry(RolloutEntry {
            timestamp: Utc::now(),
            entry_type: "user".to_string(),
            content: content.to_string(),
            input_tokens: None,
            output_tokens: None,
            duration_ms: None,
            tool_name: None,
            model: None,
        });
    }

    pub fn log_assistant(&mut self, content: &str, input_tokens: u64, output_tokens: u64, duration: Duration) {
        self.add_entry(RolloutEntry {
            timestamp: Utc::now(),
            entry_type: "assistant".to_string(),
            content: content.to_string(),
            input_tokens: Some(input_tokens),
            output_tokens: Some(output_tokens),
            duration_ms: Some(duration.as_millis() as u64),
            tool_name: None,
            model: Some(self.model.clone()),
        });
    }

    pub fn log_tool_call(&mut self, tool_name: &str, args: &str) {
        self.add_entry(RolloutEntry {
            timestamp: Utc::now(),
            entry_type: "tool_call".to_string(),
            content: args.to_string(),
            input_tokens: None,
            output_tokens: None,
            duration_ms: None,
            tool_name: Some(tool_name.to_string()),
            model: None,
        });
    }

    pub fn log_tool_result(&mut self, tool_name: &str, result: &str, duration: Duration) {
        self.add_entry(RolloutEntry {
            timestamp: Utc::now(),
            entry_type: "tool_result".to_string(),
            content: result.to_string(),
            input_tokens: None,
            output_tokens: None,
            duration_ms: Some(duration.as_millis() as u64),
            tool_name: Some(tool_name.to_string()),
            model: None,
        });
    }

    pub fn log_error(&mut self, error: &str) {
        self.add_entry(RolloutEntry {
            timestamp: Utc::now(),
            entry_type: "error".to_string(),
            content: error.to_string(),
            input_tokens: None,
            output_tokens: None,
            duration_ms: None,
            tool_name: None,
            model: None,
        });
    }
}
