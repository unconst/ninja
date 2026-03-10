use std::path::PathBuf;
use std::time::Instant;

use super::claude_client::{ClaudeClient, ContentBlock, Message, MessageContent};
use super::rollout::Rollout;
use crate::tools;

/// Configuration for the agent runner.
pub struct AgentConfig {
    pub model: String,
    pub api_key: String,
    pub api_base_url: String,
    pub workdir: PathBuf,
    pub max_iterations: usize,
    pub verbose: bool,
}

/// The main agent runner — drives the Claude ↔ tool loop.
pub struct AgentRunner {
    config: AgentConfig,
    client: ClaudeClient,
}

impl AgentRunner {
    pub fn new(config: AgentConfig) -> Self {
        let client = ClaudeClient::new(&config.api_key, &config.api_base_url, &config.model);
        Self { config, client }
    }

    pub async fn run(&mut self, prompt: &str) -> Rollout {
        let start = Instant::now();
        let mut rollout = Rollout::new(&self.config.model);
        let tool_defs = tools::get_tool_definitions();

        let system = format!(
            "You are Ninja, a powerful coding agent. You help users with software engineering tasks.\n\
             Working directory: {}\n\
             You have access to tools for reading/writing files, searching code, and running shell commands.\n\
             When given a task, break it down and execute step by step.\n\
             Always read relevant files before modifying them.\n\
             Be concise in your responses.",
            self.config.workdir.display()
        );

        let mut messages: Vec<Message> = vec![Message {
            role: "user".to_string(),
            content: MessageContent::Text(prompt.to_string()),
        }];

        rollout.log_user(prompt);

        for iteration in 0..self.config.max_iterations {
            rollout.iteration_count = (iteration + 1) as u64;

            if self.config.verbose {
                eprintln!("[iteration {}]", iteration + 1);
            }

            // Call Claude
            let response = match self.client.chat(&messages, &tool_defs, &system).await {
                Ok(r) => r,
                Err(e) => {
                    rollout.log_error(&format!("API error: {}", e));
                    eprintln!("API error: {}", e);
                    break;
                }
            };

            rollout.log_assistant(
                &response.text,
                response.input_tokens,
                response.output_tokens,
                response.duration,
            );

            if self.config.verbose {
                if !response.text.is_empty() {
                    eprintln!("  assistant: {}", &response.text[..response.text.len().min(200)]);
                }
                eprintln!(
                    "  tokens: in={} out={} tool_calls={}",
                    response.input_tokens,
                    response.output_tokens,
                    response.tool_calls.len()
                );
            }

            // If no tool calls, we're done
            if response.tool_calls.is_empty() {
                rollout.final_result = Some(response.text.clone());
                rollout.success = true;
                break;
            }

            // Build assistant message with tool calls info
            let mut assistant_blocks = Vec::new();
            if !response.text.is_empty() {
                assistant_blocks.push(ContentBlock::Text {
                    text: response.text.clone(),
                });
            }
            for tc in &response.tool_calls {
                assistant_blocks.push(ContentBlock::ToolUse {
                    id: tc.id.clone(),
                    name: tc.name.clone(),
                    input: tc.input.clone(),
                });
            }
            messages.push(Message {
                role: "assistant".to_string(),
                content: MessageContent::Blocks(assistant_blocks),
            });

            // Execute tool calls
            let mut result_blocks = Vec::new();
            for tc in &response.tool_calls {
                if self.config.verbose {
                    eprintln!("  tool: {}({})", tc.name, &tc.input.to_string()[..tc.input.to_string().len().min(100)]);
                }

                rollout.log_tool_call(&tc.name, &tc.input.to_string());

                let tool_start = Instant::now();
                let result = tools::execute_tool(&tc.name, &tc.input, &self.config.workdir);
                let tool_duration = tool_start.elapsed();

                let (output, is_error) = match result {
                    Ok(output) => (output, false),
                    Err(err) => (err, true),
                };

                rollout.log_tool_result(&tc.name, &output, tool_duration);

                if self.config.verbose {
                    let preview = &output[..output.len().min(200)];
                    eprintln!("  result: {}{}", preview, if output.len() > 200 { "..." } else { "" });
                }

                result_blocks.push(ContentBlock::ToolResult {
                    tool_use_id: tc.id.clone(),
                    content: output,
                    is_error: if is_error { Some(true) } else { None },
                });
            }

            messages.push(Message {
                role: "user".to_string(),
                content: MessageContent::Blocks(result_blocks),
            });
        }

        rollout.total_duration_ms = start.elapsed().as_millis() as u64;
        rollout
    }
}
