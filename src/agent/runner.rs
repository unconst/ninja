use colored::Colorize;
use futures_util::future::join_all;
use std::path::{Path, PathBuf};
use std::time::Instant;

use super::api_client::{ApiClient, ContentBlock, Message, MessageContent};
use super::rollout::Rollout;
use crate::tools;

/// Soft compaction: aggressively shrink old tool results but keep message structure.
const SOFT_COMPACTION_THRESHOLD: u64 = 80_000;
/// Hard compaction: drop middle messages and replace with summary.
const HARD_COMPACTION_THRESHOLD: u64 = 120_000;

/// Safely truncate a string at a char boundary, never panicking on multi-byte chars.
fn safe_truncate(s: &str, max_bytes: usize) -> &str {
    if s.len() <= max_bytes {
        return s;
    }
    // Walk backward from max_bytes to find a char boundary
    let mut end = max_bytes;
    while end > 0 && !s.is_char_boundary(end) {
        end -= 1;
    }
    &s[..end]
}

/// Configuration for the agent runner.
pub struct AgentConfig {
    pub model: String,
    /// Optional fast/cheap model for exploration-heavy iterations.
    /// When set, the agent uses this model when the previous turn was all read-only tools,
    /// and switches to the main model when edits or complex reasoning is needed.
    pub fast_model: Option<String>,
    pub api_key: String,
    pub api_base_url: String,
    pub workdir: PathBuf,
    pub max_iterations: usize,
    pub verbose: bool,
    pub streaming: bool,
}

/// The main agent runner — drives the model ↔ tool loop.
pub struct AgentRunner {
    config: AgentConfig,
    client: ApiClient,
    /// Persistent message history for multi-turn conversations.
    conversation: Vec<Message>,
    /// System prompt, built once on first run.
    system_prompt: Option<String>,
    /// Whether the last iteration used only read-only tools (for model routing).
    last_was_read_only: bool,
}

impl AgentRunner {
    pub fn new(config: AgentConfig) -> Self {
        let client = ApiClient::new(&config.api_key, &config.api_base_url, &config.model);
        Self {
            config,
            client,
            conversation: Vec::new(),
            system_prompt: None,
            last_was_read_only: true, // Start with fast model for initial exploration
        }
    }

    /// Update the working directory (used by /cd in REPL mode).
    pub fn set_workdir(&mut self, path: PathBuf) {
        self.config.workdir = path;
        // Reset system prompt so it's rebuilt with new workdir
        self.system_prompt = None;
    }

    /// Change the model (used by /model in REPL mode).
    pub fn set_model(&mut self, model: &str) {
        self.config.model = model.to_string();
        self.client.set_model(model);
    }

    /// Manually compact the conversation (used by /compact in REPL mode).
    /// Returns the number of messages before and after compaction.
    pub fn compact(&mut self) -> (usize, usize) {
        let before = self.conversation.len();
        if before > 6 {
            self.conversation = self.compact_messages(&self.conversation);
        }
        let after = self.conversation.len();
        (before, after)
    }

    /// Select the appropriate model for the current iteration based on routing strategy.
    /// Returns true if the model was changed.
    fn route_model(&mut self) -> bool {
        if let Some(ref fast_model) = self.config.fast_model {
            if self.last_was_read_only && self.client.model() != fast_model {
                if self.config.verbose {
                    eprintln!("  [routing: switching to fast model {}]", fast_model);
                }
                self.client.set_model(fast_model);
                return true;
            } else if !self.last_was_read_only && self.client.model() != self.config.model {
                if self.config.verbose {
                    eprintln!("  [routing: switching to main model {}]", self.config.model);
                }
                self.client.set_model(&self.config.model);
                return true;
            }
        }
        false
    }

    /// Check if a set of tool calls are all read-only.
    fn all_tools_read_only(tool_calls: &[super::api_client::ToolCall]) -> bool {
        tool_calls.iter().all(|tc| {
            matches!(tc.name.as_str(),
                "read_file" | "list_dir" | "glob_search" | "grep_search"
                | "find_definition" | "find_references" | "web_fetch" | "web_search"
                | "todo_write" | "think" | "memory_write"
            )
        })
    }

    /// Run a new turn in a multi-turn conversation (used by REPL).
    /// Appends to the existing conversation history.
    pub async fn run_turn(&mut self, prompt: &str) -> Rollout {
        // Build system prompt on first call
        if self.system_prompt.is_none() {
            let env_info = self.validate_initial_environment();
            self.system_prompt = Some(self.build_system_prompt(&env_info));
        }

        // Append new user message to persistent conversation
        self.conversation.push(Message {
            role: "user".to_string(),
            content: MessageContent::Text(prompt.to_string()),
        });

        let start = Instant::now();
        let mut rollout = Rollout::new(&self.config.model);
        let tool_defs = tools::get_tool_definitions();
        let system = self.system_prompt.clone().unwrap();

        let tool_names: Vec<String> = tool_defs.iter()
            .map(|td| td.name.clone())
            .collect();
        rollout.log_system(&system, &self.config.workdir.display().to_string(), &tool_names);
        rollout.log_user(prompt);

        let mut cumulative_input_tokens: u64 = 0;
        let mut completion_check_done = false;

        for iteration in 0..self.config.max_iterations {
            rollout.iteration_count = (iteration + 1) as u64;

            let current_model = self.client.model().to_string();
            rollout.log_iteration(iteration + 1, &current_model);

            if self.config.verbose {
                eprintln!("[iteration {}]", iteration + 1);
            }

            let remaining = self.config.max_iterations - iteration;
            if remaining == 10 {
                self.conversation.push(Message {
                    role: "user".to_string(),
                    content: MessageContent::Text(
                        "[SYSTEM] You have 10 iterations remaining. Focus on completing remaining changes.".to_string()
                    ),
                });
            } else if remaining == 5 {
                self.conversation.push(Message {
                    role: "user".to_string(),
                    content: MessageContent::Text(
                        "[SYSTEM] FILE CHECK — 5 iterations left. Run `git diff --stat` NOW to see which files \
                         you've modified. Compare against the REQUIRED FILES list from the task. If ANY required \
                         file is missing from your diff, modify it NOW.".to_string()
                    ),
                });
            } else if remaining == 3 {
                self.conversation.push(Message {
                    role: "user".to_string(),
                    content: MessageContent::Text(
                        "[SYSTEM] Only 3 iterations left! Wrap up immediately.".to_string()
                    ),
                });
            }

            // Route model selection based on previous turn
            self.route_model();

            let mut response = None;
            for attempt in 0..3u32 {
                let api_result = if self.config.streaming {
                    self.client.chat_streaming(&self.conversation, &tool_defs, &system).await
                } else {
                    self.client.chat(&self.conversation, &tool_defs, &system).await
                };
                match api_result {
                    Ok(r) => { response = Some(r); break; }
                    Err(e) => {
                        rollout.log_error(&format!("API error (attempt {}): {}", attempt + 1, e));
                        eprintln!("API error (attempt {}): {}", attempt + 1, e);
                        if attempt < 2 {
                            let delay_secs = 2u64.pow(attempt);
                            tokio::time::sleep(std::time::Duration::from_secs(delay_secs)).await;
                        }
                    }
                }
            }
            let response = match response {
                Some(r) => r,
                None => { eprintln!("All API retries exhausted."); break; }
            };

            rollout.log_assistant(&response.text, response.input_tokens, response.output_tokens, response.duration);
            cumulative_input_tokens = response.input_tokens;

            if self.config.verbose && !response.text.is_empty() {
                eprintln!("  assistant: {}", safe_truncate(&response.text, 200));
            }

            // Two-stage compaction
            if cumulative_input_tokens > HARD_COMPACTION_THRESHOLD && self.conversation.len() > 6 {
                self.conversation = self.compact_messages(&self.conversation);
            } else if cumulative_input_tokens > SOFT_COMPACTION_THRESHOLD {
                // Soft compaction: aggressively shrink all but last 2 messages
                Self::shrink_old_tool_results(&mut self.conversation, 2);
            }

            if response.tool_calls.is_empty() {
                // Completion check: if agent stops early, verify with diff-stat
                let used_pct = (iteration as f64) / (self.config.max_iterations as f64);
                if used_pct < 0.4 && !completion_check_done {
                    completion_check_done = true;
                    self.conversation.push(Message {
                        role: "assistant".to_string(),
                        content: MessageContent::Text(response.text.clone()),
                    });

                    let diff_stat = Self::get_git_diff_stat(&self.config.workdir);
                    let diff_context = if diff_stat.is_empty() {
                        "\n\nWARNING: `git diff --stat` shows NO modified files!".to_string()
                    } else {
                        format!(
                            "\n\nCurrent `git diff --stat`:\n```\n{}\n```\n\
                             Compare this against the REQUIRED FILES list from the task.",
                            diff_stat
                        )
                    };

                    self.conversation.push(Message {
                        role: "user".to_string(),
                        content: MessageContent::Text(format!(
                            "[SYSTEM] COMPLETION CHECK — You stopped early. Before finishing, verify:\n\
                             1. Have you modified ALL files listed in the REQUIRED FILES?\n\
                             2. Did you create required documentation/changelog entries?\n\
                             3. Did you update type stubs (.pyi) if needed?\
                             {}\n\n\
                             If any REQUIRED FILE is missing from git diff, modify it now. \
                             If truly done, respond with your summary and no tool calls.",
                            diff_context
                        )),
                    });
                    rollout.log_error("Completion check injected — agent tried to stop early");
                    continue;
                }

                // Append assistant's final response to conversation history
                self.conversation.push(Message {
                    role: "assistant".to_string(),
                    content: MessageContent::Text(response.text.clone()),
                });
                rollout.final_result = Some(response.text);
                rollout.success = true;
                break;
            }

            // Build assistant message with tool calls
            let mut assistant_blocks = Vec::new();
            if !response.text.is_empty() {
                assistant_blocks.push(ContentBlock::Text { text: response.text.clone() });
            }
            for tc in &response.tool_calls {
                assistant_blocks.push(ContentBlock::ToolUse {
                    id: tc.id.clone(), name: tc.name.clone(), input: tc.input.clone(),
                });
            }
            self.conversation.push(Message {
                role: "assistant".to_string(),
                content: MessageContent::Blocks(assistant_blocks),
            });

            // Execute tools — all independent tool calls run concurrently
            let mut result_blocks = Vec::new();

            if response.tool_calls.len() > 1 {
                // Concurrent execution for all tool calls
                for tc in &response.tool_calls {
                    rollout.log_tool_call(&tc.name, &tc.input.to_string());
                }
                let tool_descs: Vec<String> = response.tool_calls.iter()
                    .map(|tc| self.format_tool_description(&tc.name, &tc.input))
                    .collect();
                eprintln!("  {} {}", "▶".cyan(), tool_descs.join(" | "));

                let parallel_start = Instant::now();
                let mut handles = Vec::new();
                for tc in &response.tool_calls {
                    let name = tc.name.clone();
                    let input = tc.input.clone();
                    let workdir = self.config.workdir.clone();
                    handles.push(tokio::task::spawn_blocking(move || {
                        let start = Instant::now();
                        let result = tools::execute_tool(&name, &input, &workdir);
                        let duration = start.elapsed();
                        (name, result, duration)
                    }));
                }

                let results = join_all(handles).await;

                for (i, join_result) in results.into_iter().enumerate() {
                    let tc = &response.tool_calls[i];
                    let (tool_name, result, tool_duration) = join_result.unwrap_or_else(|e| {
                        (tc.name.clone(), Err(format!("Task panicked: {}", e)), std::time::Duration::ZERO)
                    });
                    let (output, is_error) = match result {
                        Ok(o) => (o, false),
                        Err(e) => (e, true),
                    };
                    rollout.log_tool_result(&tool_name, &output, tool_duration);

                    if is_error {
                        let preview = safe_truncate(&output, 100);
                        eprintln!("    {} {}", "✗".red(), preview);
                    }

                    let truncated = if output.len() > 15000 {
                        let mut t = safe_truncate(&output, 15000).to_string();
                        t.push_str(&format!("\n\n... (truncated, {} total chars)", output.len()));
                        t
                    } else { output };
                    result_blocks.push(ContentBlock::ToolResult {
                        tool_use_id: tc.id.clone(),
                        content: truncated,
                        is_error: if is_error { Some(true) } else { None },
                    });
                }

                let parallel_elapsed = parallel_start.elapsed();
                eprintln!("    {} {} tools {}", "✓".green(), response.tool_calls.len(), format!("({:.1}s)", parallel_elapsed.as_secs_f64()).dimmed());
            } else {
                // Single tool — sequential execution with recovery
                for tc in &response.tool_calls {
                    let tool_desc = self.format_tool_description(&tc.name, &tc.input);
                    eprintln!("  {} {}", "▶".cyan(), tool_desc);

                    rollout.log_tool_call(&tc.name, &tc.input.to_string());
                    let tool_start = Instant::now();
                    let result = self.execute_tool_with_recovery(&tc.name, &tc.input);
                    let tool_duration = tool_start.elapsed();
                    let (output, is_error) = match result {
                        Ok(o) => (o, false),
                        Err(e) => (e, true),
                    };
                    rollout.log_tool_result(&tc.name, &output, tool_duration);

                    if is_error {
                        let preview = safe_truncate(&output, 100);
                        eprintln!("    {} {}", "✗".red(), preview);
                    } else {
                        let summary = self.summarize_tool_result(&tc.name, &output);
                        eprintln!("    {} {}", "✓".green(), summary.dimmed());
                    }

                    let truncated = if output.len() > 15000 {
                        let mut t = safe_truncate(&output, 15000).to_string();
                        t.push_str(&format!("\n\n... (truncated, {} total chars)", output.len()));
                        t
                    } else { output };
                    result_blocks.push(ContentBlock::ToolResult {
                        tool_use_id: tc.id.clone(),
                        content: truncated,
                        is_error: if is_error { Some(true) } else { None },
                    });
                }
            }

            // Update routing state based on what tools were used
            self.last_was_read_only = Self::all_tools_read_only(&response.tool_calls);

            self.conversation.push(Message {
                role: "user".to_string(),
                content: MessageContent::Blocks(result_blocks),
            });

            // Shrink old tool results to prevent cumulative context bloat
            Self::shrink_old_tool_results(&mut self.conversation, 6);
        }

        rollout.total_duration_ms = start.elapsed().as_millis() as u64;
        rollout.estimate_cost();
        rollout
    }

    pub async fn run(&mut self, prompt: &str) -> Rollout {
        let start = Instant::now();
        let mut rollout = Rollout::new(&self.config.model);
        let tool_defs = tools::get_tool_definitions();

        let env_info = self.validate_initial_environment();
        let system = self.build_system_prompt(&env_info);

        let tool_names: Vec<String> = tool_defs.iter()
            .map(|td| td.name.clone())
            .collect();
        rollout.log_system(&system, &self.config.workdir.display().to_string(), &tool_names);

        let mut messages: Vec<Message> = vec![Message {
            role: "user".to_string(),
            content: MessageContent::Text(prompt.to_string()),
        }];

        rollout.log_user(prompt);

        let mut cumulative_input_tokens: u64 = 0;
        let mut completion_check_done = false;
        let mut last_write_iteration: usize = 0; // Track last iteration with a write/edit tool
        let mut idle_nudge_done = false;

        for iteration in 0..self.config.max_iterations {
            rollout.iteration_count = (iteration + 1) as u64;

            let current_model = self.client.model().to_string();
            rollout.log_iteration(iteration + 1, &current_model);

            if self.config.verbose {
                eprintln!("[iteration {}]", iteration + 1);
            }

            // Inject phase transition and urgency reminders
            let remaining = self.config.max_iterations - iteration;
            if iteration == 5 {
                messages.push(Message {
                    role: "user".to_string(),
                    content: MessageContent::Text(
                        "[SYSTEM] PHASE CHECK — Iteration 5 reached. You should be DONE exploring by now. \
                         If you haven't started editing files, START NOW. State your plan briefly, then \
                         begin implementing. Every iteration spent reading without editing is wasted.".to_string()
                    ),
                });
            } else if iteration == 15 {
                messages.push(Message {
                    role: "user".to_string(),
                    content: MessageContent::Text(
                        "[SYSTEM] MID-RUN CHECK — Iteration 15. How many files from your plan have you \
                         actually modified? If less than half, pick up the pace. Focus on the remaining \
                         files.".to_string()
                    ),
                });
            } else if remaining == 10 {
                messages.push(Message {
                    role: "user".to_string(),
                    content: MessageContent::Text(
                        "[SYSTEM] URGENT — 10 iterations remaining. Review your deliverables checklist — \
                         make sure all required files have been modified/created. Focus on completing \
                         any remaining changes now. Don't waste iterations on testing if dependencies \
                         are missing.".to_string()
                    ),
                });
            } else if remaining == 5 {
                messages.push(Message {
                    role: "user".to_string(),
                    content: MessageContent::Text(
                        "[SYSTEM] FILE CHECK — 5 iterations left. Run `git diff --stat` NOW to see which files \
                         you've modified. Compare against the REQUIRED FILES list from the task. If ANY required \
                         file is missing from your diff, modify it NOW. Common misses: config files (pyproject.toml, \
                         setup.cfg), type stubs (.pyi), documentation files (.rst, .md), and changelog files. \
                         Do NOT stop until every required file appears in git diff.".to_string()
                    ),
                });
            } else if remaining == 3 {
                messages.push(Message {
                    role: "user".to_string(),
                    content: MessageContent::Text(
                        "[SYSTEM] FINAL — Only 3 iterations left! Wrap up immediately. If any files from your \
                         plan are still unmodified, make those changes now. Summarize what you've done.".to_string()
                    ),
                });
            }

            // Route model selection based on previous turn
            self.route_model();

            // Call model API with retry on transient errors
            let mut response = None;
            for attempt in 0..3u32 {
                let api_result = if self.config.streaming {
                    self.client.chat_streaming(&messages, &tool_defs, &system).await
                } else {
                    self.client.chat(&messages, &tool_defs, &system).await
                };
                match api_result {
                    Ok(r) => {
                        response = Some(r);
                        break;
                    }
                    Err(e) => {
                        rollout.log_error(&format!("API error (attempt {}): {}", attempt + 1, e));
                        eprintln!("API error (attempt {}): {}", attempt + 1, e);
                        if attempt < 2 {
                            let delay_secs = 2u64.pow(attempt);
                            eprintln!("  Retrying in {}s...", delay_secs);
                            tokio::time::sleep(std::time::Duration::from_secs(delay_secs)).await;
                        }
                    }
                }
            }
            let response = match response {
                Some(r) => r,
                None => {
                    eprintln!("All API retries exhausted, stopping.");
                    break;
                }
            };

            rollout.log_assistant(
                &response.text,
                response.input_tokens,
                response.output_tokens,
                response.duration,
            );

            cumulative_input_tokens = response.input_tokens;

            if self.config.verbose {
                if !response.text.is_empty() {
                    eprintln!("  assistant: {}", safe_truncate(&response.text, 200));
                }
                eprintln!(
                    "  tokens: in={} out={} tool_calls={} cumulative_in={}",
                    response.input_tokens,
                    response.output_tokens,
                    response.tool_calls.len(),
                    cumulative_input_tokens,
                );
            }

            // Two-stage compaction to manage context window
            if cumulative_input_tokens > HARD_COMPACTION_THRESHOLD && messages.len() > 6 {
                if self.config.verbose {
                    eprintln!("  [hard compaction: {} tokens, {} messages]", cumulative_input_tokens, messages.len());
                }
                messages = self.compact_messages(&messages);
                rollout.log_error(&format!(
                    "Hard compaction at {} tokens, {} messages remaining",
                    cumulative_input_tokens, messages.len()
                ));
            } else if cumulative_input_tokens > SOFT_COMPACTION_THRESHOLD {
                // Soft compaction: aggressively shrink all but last 2 messages
                Self::shrink_old_tool_results(&mut messages, 2);
            }

            // If no tool calls, check completion
            if response.tool_calls.is_empty() {
                // If agent stops early (before using 40% of iterations) and hasn't been
                // nudged yet, inject a completion check to prevent premature stopping
                let used_pct = (iteration as f64) / (self.config.max_iterations as f64);
                if used_pct < 0.4 && !completion_check_done {
                    completion_check_done = true;
                    messages.push(Message {
                        role: "assistant".to_string(),
                        content: MessageContent::Text(response.text.clone()),
                    });

                    // Auto-run git diff --stat for the verification
                    let diff_stat = Self::get_git_diff_stat(&self.config.workdir);
                    let diff_context = if diff_stat.is_empty() {
                        "\n\nWARNING: `git diff --stat` shows NO modified files!".to_string()
                    } else {
                        format!(
                            "\n\nCurrent `git diff --stat`:\n```\n{}\n```\n\
                             Compare this against the REQUIRED FILES list from the task.",
                            diff_stat
                        )
                    };

                    messages.push(Message {
                        role: "user".to_string(),
                        content: MessageContent::Text(format!(
                            "[SYSTEM] COMPLETION CHECK — You stopped early. Before finishing, verify:\n\
                             1. Have you modified ALL files listed in the REQUIRED FILES?\n\
                             2. Did you create required documentation/changelog entries?\n\
                             3. Did you update type stubs (.pyi) if needed?\n\
                             4. Check your todo list — are all items marked done?\
                             {}\n\n\
                             If any REQUIRED FILE is missing from git diff, modify it now. \
                             If truly done, respond with your summary and no tool calls.",
                            diff_context
                        )),
                    });
                    rollout.log_error("Completion check injected — agent tried to stop early");
                    continue;
                }
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

            // Execute tool calls with error handling and recovery
            let mut result_blocks = Vec::new();

            if response.tool_calls.len() > 1 {
                // Concurrent execution for multiple tool calls
                for tc in &response.tool_calls {
                    rollout.log_tool_call(&tc.name, &tc.input.to_string());
                }
                let tool_descs: Vec<String> = response.tool_calls.iter()
                    .map(|tc| self.format_tool_description(&tc.name, &tc.input))
                    .collect();
                eprintln!("  {} {}", "▶".cyan(), tool_descs.join(" | "));

                let parallel_start = Instant::now();
                let mut handles = Vec::new();
                for tc in &response.tool_calls {
                    let name = tc.name.clone();
                    let input = tc.input.clone();
                    let workdir = self.config.workdir.clone();
                    handles.push(tokio::task::spawn_blocking(move || {
                        let start = Instant::now();
                        let result = tools::execute_tool(&name, &input, &workdir);
                        let duration = start.elapsed();
                        (name, result, duration)
                    }));
                }

                let results = join_all(handles).await;

                for (i, join_result) in results.into_iter().enumerate() {
                    let tc = &response.tool_calls[i];
                    let (_tool_name, result, tool_duration) = join_result.unwrap_or_else(|e| {
                        (tc.name.clone(), Err(format!("Task panicked: {}", e)), std::time::Duration::ZERO)
                    });
                    let (output, is_error) = match result {
                        Ok(o) => (o, false),
                        Err(e) => (e, true),
                    };
                    rollout.log_tool_result(&tc.name, &output, tool_duration);

                    if is_error {
                        let preview = safe_truncate(&output, 100);
                        eprintln!("    {} {}", "✗".red(), preview);
                    }

                    let truncated = if output.len() > 15000 {
                        let mut t = safe_truncate(&output, 15000).to_string();
                        t.push_str(&format!("\n\n... (truncated, {} total chars)", output.len()));
                        t
                    } else { output };
                    result_blocks.push(ContentBlock::ToolResult {
                        tool_use_id: tc.id.clone(),
                        content: truncated,
                        is_error: if is_error { Some(true) } else { None },
                    });
                }

                let parallel_elapsed = parallel_start.elapsed();
                eprintln!("    {} {} tools {}", "✓".green(), response.tool_calls.len(), format!("({:.1}s)", parallel_elapsed.as_secs_f64()).dimmed());
            } else {
                // Single tool — sequential with recovery
                for tc in &response.tool_calls {
                    let tool_desc = self.format_tool_description(&tc.name, &tc.input);
                    eprintln!("  {} {}", "▶".cyan(), tool_desc);

                    rollout.log_tool_call(&tc.name, &tc.input.to_string());

                    let tool_start = Instant::now();
                    let result = self.execute_tool_with_recovery(&tc.name, &tc.input);
                    let tool_duration = tool_start.elapsed();

                    let (output, is_error) = match result {
                        Ok(output) => (output, false),
                        Err(err) => (err, true),
                    };

                    rollout.log_tool_result(&tc.name, &output, tool_duration);

                    if is_error {
                        let preview = safe_truncate(&output, 100);
                        eprintln!("    {} {}", "✗".red(), preview);
                    } else {
                        let summary = self.summarize_tool_result(&tc.name, &output);
                        eprintln!("    {} {}", "✓".green(), summary.dimmed());
                    }

                    let truncated_output = if output.len() > 15000 {
                        let mut t = safe_truncate(&output, 15000).to_string();
                        t.push_str(&format!("\n\n... (truncated, {} total chars)", output.len()));
                        t
                    } else {
                        output
                    };

                    result_blocks.push(ContentBlock::ToolResult {
                        tool_use_id: tc.id.clone(),
                        content: truncated_output,
                        is_error: if is_error { Some(true) } else { None },
                    });
                }
            }

            // Update routing state based on what tools were used
            let all_read = Self::all_tools_read_only(&response.tool_calls);
            self.last_was_read_only = all_read;

            // Track last write/edit iteration
            if !all_read {
                last_write_iteration = iteration;
            }

            messages.push(Message {
                role: "user".to_string(),
                content: MessageContent::Blocks(result_blocks),
            });

            // If 10+ iterations since last write and past iteration 20, nudge the agent to finish
            if !idle_nudge_done && iteration > 20 && iteration - last_write_iteration >= 10 {
                idle_nudge_done = true;
                messages.push(Message {
                    role: "user".to_string(),
                    content: MessageContent::Text(
                        "[SYSTEM] IDLE DETECTION — You haven't written or edited any files in the last 10 \
                         iterations. If your changes are complete, stop and provide your final summary. \
                         Don't continue reading/verifying indefinitely. If there are remaining changes, \
                         make them NOW.".to_string()
                    ),
                });
                rollout.log_error("Idle write detection: 10+ iterations without edits");
            }

            // Shrink old tool results to prevent cumulative context bloat.
            // Keep last 6 messages intact (current turn + a bit of recent context).
            Self::shrink_old_tool_results(&mut messages, 6);
        }

        rollout.total_duration_ms = start.elapsed().as_millis() as u64;
        rollout.estimate_cost();
        rollout
    }

    /// Build the system prompt for the agent.
    fn build_system_prompt(&self, env_info: &str) -> String {
        let mut prompt = format!(
            "You are Ninja, a powerful autonomous coding agent. You solve software engineering tasks \
             by reading, understanding, and modifying code.\n\n\
             Working directory: {}\n\
             {}\n\n\
             ## Available Tools\n\
             - read_file: Read file contents (supports offset/limit for large files)\n\
             - write_file: Create or overwrite files\n\
             - edit_file: Replace exact string matches in files. The old_string MUST be unique \
               — include surrounding context lines if needed. Set replace_all=true to replace all occurrences.\n\
             - replace_lines: Replace a range of lines by line number (1-based, inclusive). \
               More reliable than edit_file for large changes. Always read the file first to get line numbers.\n\
             - list_dir: List directory contents\n\
             - shell_exec: Run shell commands (bash)\n\
             - glob_search: Find files by name pattern\n\
             - grep_search: Search file contents with regex\n\
             - web_fetch: Fetch content from a URL (documentation, issues, etc.)\n\
             - web_search: Search the web for information using DuckDuckGo\n\
             - find_definition: Find where a symbol is defined (function, class, etc.)\n\
             - find_references: Find all references to a symbol\n\
             - run_tests: Run project tests (auto-detects framework, or provide custom command)\n\
             - spawn_agent: Launch a sub-agent for independent parallel tasks. Use this to fan out \
               work across multiple files or research tasks simultaneously.\n\
             - todo_write: Track progress on multi-step tasks with a structured todo list\n\
             - think: Reason step-by-step about complex decisions before acting (no side effects)\n\
             - memory_write: Save important discoveries, patterns, or project notes to persistent memory\n\n\
             ## Strategy — STRICT ITERATION BUDGET\n\
             You have a limited number of iterations. Follow this phased approach:\n\n\
             **Phase 1: EXPLORE (iterations 1-5 MAX)**\n\
             - Read the problem statement and any test/solution patches carefully\n\
             - Use grep_search to locate relevant files — read them in FULL (don't use small offset/limit)\n\
             - By iteration 3, you MUST have a written plan: list EVERY file that needs changes\n\
             - Do NOT spend more than 5 iterations exploring. If unsure, start implementing.\n\n\
             **Phase 2: IMPLEMENT (iterations 6-35)**\n\
             - Work through your file list systematically, editing one file at a time\n\
             - Always read a file before editing it\n\
             - For edit_file, include enough surrounding context in old_string to make it unique\n\
             - After each edit, read back the file to confirm it applied correctly\n\
             - Consider backward compatibility and edge cases (try/except for version differences, etc.)\n\
             - Create ALL required files: source code, docs, changelogs, type stubs (.pyi), config\n\
             - If the REQUIRED FILES list includes files that don't exist yet, CREATE them with write_file. \
               Common examples: changelog entries (e.g. changelog/NNNN.type.rst), new modules, new test files.\n\n\
             **Phase 3: VERIFY & FINISH (iterations 36+)**\n\
             - Review your deliverables checklist — every file must be addressed\n\
             - Check for INDIRECT CHANGES needed in config files: when you update a linter, formatter, \
               or dependency version, run the tool to check if new rules/warnings fire. Update \
               pyproject.toml, setup.cfg, .pre-commit-config.yaml with any new ignores or settings.\n\
             - When you change file formats (e.g. PNG→SVG), update ALL references in docs/conf.py, \
               index.rst, README, etc. — don't just add new files, also fix pointers to old ones.\n\
             - Type stubs (.pyi): if you change a function signature in a .pyx/.py file, update the \
               corresponding .pyi stub to match.\n\
             - Run the project's linter or test suite after changes if feasible — new failures often \
               reveal config files you need to update.\n\
             - When done, list every file you changed with a brief summary\n\n\
             ## Rules\n\
             - SPEED OVER PERFECTION: Make changes quickly. Don't over-explore.\n\
             - PARALLELIZE: When you need to read or research multiple independent files/topics, \
               use spawn_agent to fan out the work. When you call multiple tools in one response, \
               they execute concurrently.\n\
             - Read files FULLY — avoid reading tiny chunks (offset/limit). Read the whole file.\n\
             - Be precise and minimal in changes — don't over-engineer\n\
             - When editing, prefer small targeted edits over rewriting entire files\n\
             - If edit_file fails with 'String not found', re-read the file and copy the EXACT text. \
               After 2 failed attempts on the same file, switch to write_file to overwrite it entirely.\n\
             - If a test patch is provided, apply it first, then make source changes to pass the tests\n\
             - If you can't run tests due to missing dependencies, don't waste iterations retrying. \
               Proceed with confidence based on code analysis.\n\
             - Consider BACKWARD COMPATIBILITY: use try/except blocks when adding new API parameters \
               that may not exist in older library versions.\n\
             - When done, list every file you changed and briefly summarize each change",
            self.config.workdir.display(),
            env_info
        );

        // Append NINJA.md project config if present
        for config_name in &["NINJA.md", ".ninja.md", "CLAUDE.md"] {
            let config_path = self.config.workdir.join(config_name);
            if config_path.exists() {
                if let Ok(content) = std::fs::read_to_string(&config_path) {
                    let truncated = if content.len() > 5000 {
                        format!("{}...\n(truncated)", safe_truncate(&content, 5000))
                    } else {
                        content
                    };
                    prompt.push_str(&format!(
                        "\n\n## Project Configuration ({})\n{}",
                        config_name, truncated
                    ));
                }
                break; // Only use the first config file found
            }
        }

        // Load persistent memory
        if let Some(memory_section) = crate::tools::memory::load_project_memory(&self.config.workdir) {
            prompt.push_str(&format!("\n\n{}", memory_section));
        }

        prompt
    }

    /// Run `git diff --stat` to see which files have been modified.
    fn get_git_diff_stat(workdir: &Path) -> String {
        if let Ok(output) = std::process::Command::new("git")
            .args(&["diff", "--stat"])
            .current_dir(workdir)
            .output()
        {
            if output.status.success() {
                let stat = String::from_utf8_lossy(&output.stdout).to_string();
                if !stat.trim().is_empty() {
                    return stat.trim().to_string();
                }
            }
        }
        // Also check for untracked files
        if let Ok(output) = std::process::Command::new("git")
            .args(&["status", "--porcelain"])
            .current_dir(workdir)
            .output()
        {
            if output.status.success() {
                let status = String::from_utf8_lossy(&output.stdout).to_string();
                if !status.trim().is_empty() {
                    return status.trim().to_string();
                }
            }
        }
        String::new()
    }

    /// Validate the initial environment and gather context information.
    /// Uses minimal subprocess calls to keep startup fast.
    fn validate_initial_environment(&self) -> String {
        let mut env_info = Vec::new();

        // Single git status call with branch info (porcelain v2 gives branch + status)
        if let Ok(output) = std::process::Command::new("git")
            .args(&["status", "-b", "--porcelain=v2"])
            .current_dir(&self.config.workdir)
            .output()
        {
            if output.status.success() {
                if let Ok(status_str) = String::from_utf8(output.stdout) {
                    let mut branch = String::new();
                    let mut modified = 0usize;

                    for line in status_str.lines() {
                        if line.starts_with("# branch.head ") {
                            branch = line.trim_start_matches("# branch.head ").to_string();
                        } else if line.starts_with("1 ") || line.starts_with("2 ") || line.starts_with("? ") {
                            modified += 1;
                        }
                    }

                    if !branch.is_empty() {
                        env_info.push(format!("Git branch: {}", branch));
                    }
                    if modified > 0 {
                        env_info.push(format!("{} modified/untracked files", modified));
                    } else {
                        env_info.push("Working directory is clean".to_string());
                    }
                }
            }
        }
        
        // Check for common project files
        let project_indicators = [
            ("package.json", "Node.js project"),
            ("Cargo.toml", "Rust project"),
            ("requirements.txt", "Python project"),
            ("pom.xml", "Maven project"),
            ("build.gradle", "Gradle project"),
            ("Makefile", "Make-based project"),
            ("docker-compose.yml", "Docker Compose project"),
            ("Dockerfile", "Docker project"),
        ];
        
        for (file, description) in &project_indicators {
            if self.config.workdir.join(file).exists() {
                env_info.push(format!("{} detected", description));
            }
        }
        
        if env_info.is_empty() {
            "Environment: Empty or new directory".to_string()
        } else {
            format!("Environment context:\n{}", env_info.join("\n"))
        }
    }

    /// Execute a tool with error handling and recovery mechanisms
    fn execute_tool_with_recovery(&self, tool_name: &str, input: &serde_json::Value) -> Result<String, String> {
        // Check for git clone commands and validate if already in target repository
        if tool_name == "shell_exec" {
            if let Some(command) = input.get("command").and_then(|c| c.as_str()) {
                if command.starts_with("git clone") {
                    if let Some(recovery_result) = self.check_git_clone_necessity(command) {
                        return Ok(recovery_result);
                    }
                }
            }
        }
        
        // First attempt to execute the tool
        let result = tools::execute_tool(tool_name, input, &self.config.workdir);
        
        match result {
            Ok(output) => {
                // For edit_file operations, validate the changes were applied correctly
                if tool_name == "edit_file" {
                    if let Some(validation_result) = self.validate_file_edit(input, &output) {
                        Ok(validation_result)
                    } else {
                        Ok(output)
                    }
                } else {
                    Ok(output)
                }
            },
            Err(error) => {
                // Apply recovery strategies based on tool type and error
                if let Some(recovered_output) = self.try_recover_from_error(tool_name, input, &error) {
                    Ok(recovered_output)
                } else {
                    Err(error)
                }
            }
        }
    }

    /// Validate that file edits were applied correctly by reading back the file
    fn validate_file_edit(&self, input: &serde_json::Value, edit_output: &str) -> Option<String> {
        let path = input.get("path")?.as_str()?;
        // edit_file uses new_string (not content) — verify the new text appears in the file
        let new_string = input.get("new_string").and_then(|v| v.as_str())?;

        // Only validate if the edit operation reported success
        if !edit_output.contains("successfully") && !edit_output.contains("applied") && !edit_output.contains("replaced") {
            return None;
        }

        // Read the file back to verify the edit was applied
        let read_input = serde_json::json!({
            "path": path
        });

        match tools::execute_tool("read_file", &read_input, &self.config.workdir) {
            Ok(actual_content) => {
                if actual_content.contains(new_string.trim()) {
                    // New content found in file — edit verified
                    Some(format!("{}\n\nValidation: Edit verified — new content found in file.", edit_output))
                } else {
                    // new_string not found — edit may have failed silently
                    let content_preview = if actual_content.len() > 500 {
                        format!("{}...", safe_truncate(&actual_content, 500))
                    } else {
                        actual_content.clone()
                    };

                    Some(format!(
                        "{}\n\nValidation WARNING: The new content was NOT found in the file after editing. \
                         The edit may not have been applied correctly. Read the file to check:\n{}",
                        edit_output,
                        content_preview
                    ))
                }
            },
            Err(_) => {
                Some(format!("{}\n\nValidation Warning: Could not read file back to verify changes.", edit_output))
            }
        }
    }

    /// Check if git clone is necessary or if we're already in the target repository
    fn check_git_clone_necessity(&self, command: &str) -> Option<String> {
        let repo_url = self.extract_repo_url_from_clone_command(command)?;
        
        // Check if we're already in a git repository
        if let Ok(output) = std::process::Command::new("git")
            .args(&["remote", "-v"])
            .current_dir(&self.config.workdir)
            .output()
        {
            if output.status.success() {
                if let Ok(remote_info) = String::from_utf8(output.stdout) {
                    // Check if any remote matches the target repository
                    if self.is_matching_repository(&remote_info, &repo_url) {
                        return Some(format!(
                            "Already in target repository '{}'. Current remotes:\n{}",
                            repo_url,
                            remote_info.trim()
                        ));
                    }
                }
            }
        }
        
        None
    }

    /// Check if the current repository matches the target repository URL
    fn is_matching_repository(&self, remote_info: &str, target_url: &str) -> bool {
        let normalized_target = self.normalize_git_url(target_url);
        
        for line in remote_info.lines() {
            if let Some(url_start) = line.find('\t') {
                let url_part = &line[url_start + 1..];
                if let Some(url_end) = url_part.find(' ') {
                    let remote_url = &url_part[..url_end];
                    let normalized_remote = self.normalize_git_url(remote_url);
                    
                    if normalized_remote == normalized_target {
                        return true;
                    }
                }
            }
        }
        
        false
    }

    /// Normalize git URLs for comparison (handle different formats like HTTPS vs SSH)
    fn normalize_git_url(&self, url: &str) -> String {
        let mut normalized = url.to_lowercase();
        
        // Remove .git suffix
        if normalized.ends_with(".git") {
            normalized = normalized[..normalized.len() - 4].to_string();
        }
        
        // Convert SSH to HTTPS format for comparison
        if normalized.starts_with("git@github.com:") {
            normalized = normalized.replace("git@github.com:", "https://github.com/");
        }
        
        // Remove trailing slashes
        normalized = normalized.trim_end_matches('/').to_string();
        
        normalized
    }

    /// Extract repository URL from git clone command
    fn extract_repo_url_from_clone_command(&self, command: &str) -> Option<String> {
        let parts: Vec<&str> = command.split_whitespace().collect();
        
        for (i, part) in parts.iter().enumerate() {
            if part == &"clone" && i + 1 < parts.len() {
                return Some(parts[i + 1].to_string());
            }
        }
        
        None
    }

    /// Attempt to recover from common tool execution errors
    fn try_recover_from_error(&self, tool_name: &str, input: &serde_json::Value, error: &str) -> Option<String> {
        match tool_name {
            "shell_exec" => self.recover_shell_error(input, error),
            "write_file" => self.recover_write_file_error(input, error),
            "edit_file" => self.recover_edit_file_error(input, error),
            "read_file" => self.recover_read_file_error(input, error),
            _ => None,
        }
    }

    /// Recovery strategies for shell command errors
    fn recover_shell_error(&self, input: &serde_json::Value, error: &str) -> Option<String> {
        let command = input.get("command")?.as_str()?;
        
        // Handle git clone directory already exists error
        if command.starts_with("git clone") && error.contains("already exists") {
            let repo_name = self.extract_repo_name_from_clone_command(command)?;
            let repo_path = self.config.workdir.join(&repo_name);
            
            if repo_path.exists() && repo_path.join(".git").exists() {
                return Some(format!(
                    "Repository '{}' already exists and appears to be a valid git repository. Skipping clone.",
                    repo_name
                ));
            }
        }
        
        // Handle permission denied errors by suggesting alternatives
        if error.contains("Permission denied") {
            return Some(format!(
                "Permission denied for command '{}'. Consider using sudo or checking file permissions.",
                command
            ));
        }
        
        // Handle command not found errors
        if error.contains("command not found") || error.contains("not recognized") {
            return Some(format!(
                "Command not found: '{}'. Please ensure the required tool is installed.",
                command
            ));
        }
        
        None
    }

    /// Recovery strategies for file write errors
    fn recover_write_file_error(&self, input: &serde_json::Value, error: &str) -> Option<String> {
        let path = input.get("path")?.as_str()?;
        
        // Handle directory doesn't exist error
        if error.contains("No such file or directory") || error.contains("cannot find the path") {
            if let Some(parent) = std::path::Path::new(path).parent() {
                if !parent.exists() {
                    return Some(format!(
                        "Directory '{}' does not exist. Please create the directory first using mkdir or the shell tool.",
                        parent.display()
                    ));
                }
            }
        }
        
        // Handle permission errors
        if error.contains("Permission denied") {
            return Some(format!(
                "Permission denied writing to '{}'. Check file permissions or try a different location.",
                path
            ));
        }
        
        None
    }

    /// Recovery strategies for file edit errors
    fn recover_edit_file_error(&self, input: &serde_json::Value, error: &str) -> Option<String> {
        let path = input.get("path")?.as_str()?;

        // Handle "String not found" — most common edit failure
        if error.contains("String not found") {
            return Some(format!(
                "Edit failed: old_string not found in '{}'. Recovery steps:\n\
                 1. Re-read the file with read_file to see its CURRENT content\n\
                 2. Copy the EXACT text you want to replace (whitespace matters)\n\
                 3. If the file has changed since you last read it, use the updated content\n\
                 4. If the edit keeps failing, use write_file to overwrite the entire file with the corrected version\n\
                 5. For large files, use edit_file with a smaller, more unique old_string snippet",
                path
            ));
        }

        // Handle "Multiple matches" — old_string appears more than once
        if error.contains("Multiple matches") || error.contains("matches found") {
            return Some(format!(
                "Edit failed: old_string matches multiple locations in '{}'. Include more surrounding \
                 context (extra lines above/below) to make old_string unique, or use replace_all=true \
                 if you want to replace ALL occurrences.",
                path
            ));
        }

        // Handle file not found error - suggest using write_file instead
        if error.contains("No such file or directory") || error.contains("cannot find the path") {
            return Some(format!(
                "File '{}' not found for editing. Use 'write_file' to create a new file, or check if the file path is correct.",
                path
            ));
        }

        // Handle permission errors
        if error.contains("Permission denied") {
            return Some(format!(
                "Permission denied editing '{}'. Check file permissions.",
                path
            ));
        }

        // Handle content too large errors
        if error.contains("too large") || error.contains("size limit") {
            return Some(format!(
                "File '{}' is too large to edit in one operation. Consider using smaller edits or breaking the change into multiple parts.",
                path
            ));
        }

        None
    }

    /// Recovery strategies for file read errors
    fn recover_read_file_error(&self, input: &serde_json::Value, error: &str) -> Option<String> {
        let path = input.get("path")?.as_str()?;
        
        // Handle file not found error with helpful suggestions
        if error.contains("No such file or directory") || error.contains("cannot find the path") {
            return Some(format!(
                "File '{}' not found. Use the 'list_files' tool to explore the directory structure, or check if the file path is correct.",
                path
            ));
        }
        
        // Handle permission errors
        if error.contains("Permission denied") {
            return Some(format!(
                "Permission denied reading '{}'. Check file permissions.",
                path
            ));
        }
        
        None
    }

    /// Compact conversation history by summarizing older tool interactions.
    /// Keeps the first user message (original prompt) and recent messages,
    /// replacing middle messages with a summary.
    fn compact_messages(&self, messages: &[Message]) -> Vec<Message> {
        if messages.len() <= 6 {
            return messages.to_vec();
        }

        // Keep: first message (original prompt) + last 4 messages (recent context)
        let keep_start = 1;  // after original prompt
        let keep_end = messages.len().saturating_sub(4);

        // Build summary of compacted messages
        let mut summary_parts: Vec<String> = Vec::new();
        summary_parts.push("## Conversation History Summary\nThe following actions were taken earlier in this session:\n".to_string());

        for msg in &messages[keep_start..keep_end] {
            match &msg.content {
                MessageContent::Text(text) => {
                    if msg.role == "assistant" {
                        let preview = safe_truncate(text.as_str(), 200);
                        summary_parts.push(format!("- Assistant thought: {}", preview));
                    }
                    // Skip system injection messages in summary
                }
                MessageContent::Blocks(blocks) => {
                    for block in blocks {
                        match block {
                            ContentBlock::ToolUse { name, input, .. } => {
                                let args_preview = input.to_string();
                                let args_short = if args_preview.len() > 100 {
                                    format!("{}...", safe_truncate(&args_preview, 100))
                                } else {
                                    args_preview
                                };
                                summary_parts.push(format!("- Used tool `{}`: {}", name, args_short));
                            }
                            ContentBlock::ToolResult { content, is_error, .. } => {
                                let status = if *is_error == Some(true) { "ERROR" } else { "OK" };
                                let preview = safe_truncate(content.as_str(), 150);
                                summary_parts.push(format!("  Result ({}): {}", status, preview));
                            }
                            ContentBlock::Text { text } => {
                                let preview = safe_truncate(text.as_str(), 200);
                                summary_parts.push(format!("- {}", preview));
                            }
                        }
                    }
                }
            }
        }

        let summary = summary_parts.join("\n");

        // Gather current git diff --stat so the agent knows what it already changed
        let git_diff_info = match std::process::Command::new("git")
            .args(&["diff", "--stat"])
            .current_dir(&self.config.workdir)
            .output()
        {
            Ok(output) if output.status.success() => {
                let stat = String::from_utf8_lossy(&output.stdout);
                if stat.trim().is_empty() {
                    String::new()
                } else {
                    format!("\n\n## Files You Have Already Modified (git diff --stat)\n```\n{}\n```\n\
                            Do NOT re-read or re-edit these files unless you need to make additional changes.",
                            safe_truncate(stat.trim(), 2000))
                }
            }
            _ => String::new(),
        };

        let mut compacted = Vec::new();
        // Keep original prompt
        compacted.push(messages[0].clone());
        // Insert summary as a user message with git diff awareness
        compacted.push(Message {
            role: "user".to_string(),
            content: MessageContent::Text(format!(
                "[SYSTEM] The conversation has been compacted to save context space.\n\n{}{}\n\n\
                Continue working on the task. Review your deliverables checklist and complete any remaining changes.",
                summary, git_diff_info
            )),
        });
        // Keep the recent messages (last 4)
        for msg in &messages[messages.len().saturating_sub(4)..] {
            compacted.push(msg.clone());
        }

        compacted
    }

    /// Format a human-readable description of a tool call.
    fn format_tool_description(&self, tool_name: &str, input: &serde_json::Value) -> String {
        match tool_name {
            "read_file" => {
                let path = input.get("path").and_then(|v| v.as_str()).unwrap_or("?");
                let short = path.rsplit('/').next().unwrap_or(path);
                format!("Read {}", short)
            }
            "write_file" => {
                let path = input.get("path").and_then(|v| v.as_str()).unwrap_or("?");
                let short = path.rsplit('/').next().unwrap_or(path);
                format!("Write {}", short)
            }
            "edit_file" => {
                let path = input.get("path").and_then(|v| v.as_str()).unwrap_or("?");
                let short = path.rsplit('/').next().unwrap_or(path);
                format!("Edit {}", short)
            }
            "list_dir" => {
                let path = input.get("path").and_then(|v| v.as_str()).unwrap_or(".");
                format!("List {}", path)
            }
            "shell_exec" => {
                let cmd = input.get("command").and_then(|v| v.as_str()).unwrap_or("?");
                let preview = safe_truncate(cmd, 60);
                format!("Shell: {}", preview)
            }
            "glob_search" => {
                let pattern = input.get("pattern").and_then(|v| v.as_str()).unwrap_or("?");
                format!("Glob {}", pattern)
            }
            "grep_search" => {
                let pattern = input.get("pattern").and_then(|v| v.as_str()).unwrap_or("?");
                format!("Grep '{}'", pattern)
            }
            "web_fetch" => {
                let url = input.get("url").and_then(|v| v.as_str()).unwrap_or("?");
                let short = safe_truncate(url, 50);
                format!("Fetch {}", short)
            }
            "web_search" => {
                let query = input.get("query").and_then(|v| v.as_str()).unwrap_or("?");
                let short = safe_truncate(query, 50);
                format!("Search '{}'", short)
            }
            "find_definition" => {
                let symbol = input.get("symbol").and_then(|v| v.as_str()).unwrap_or("?");
                format!("Find def '{}'", symbol)
            }
            "find_references" => {
                let symbol = input.get("symbol").and_then(|v| v.as_str()).unwrap_or("?");
                format!("Find refs '{}'", symbol)
            }
            "run_tests" => {
                if let Some(cmd) = input.get("command").and_then(|v| v.as_str()) {
                    let short = safe_truncate(cmd, 40);
                    format!("Test: {}", short)
                } else {
                    "Run tests".to_string()
                }
            }
            "spawn_agent" => {
                let prompt = input.get("prompt").and_then(|v| v.as_str()).unwrap_or("?");
                let short = safe_truncate(prompt, 40);
                format!("Agent: {}", short)
            }
            "todo_write" => "Update todo list".to_string(),
            _ => format!("{}", tool_name),
        }
    }

    /// Create a brief summary of a tool result for display.
    fn summarize_tool_result(&self, tool_name: &str, output: &str) -> String {
        match tool_name {
            "read_file" => {
                let lines = output.lines().count();
                format!("{} lines", lines)
            }
            "write_file" => {
                if output.contains("bytes") {
                    output.to_string()
                } else {
                    "written".to_string()
                }
            }
            "edit_file" => {
                if output.contains("successfully") {
                    "applied".to_string()
                } else {
                    safe_truncate(output, 60).to_string()
                }
            }
            "list_dir" => {
                let entries = output.lines().count();
                format!("{} entries", entries)
            }
            "shell_exec" => {
                let lines = output.lines().count();
                if lines <= 1 {
                    safe_truncate(output, 80).trim().to_string()
                } else {
                    format!("{} lines of output", lines)
                }
            }
            "glob_search" | "grep_search" => {
                let matches = output.lines().count();
                format!("{} matches", matches)
            }
            "web_fetch" => {
                let chars = output.len();
                format!("{} chars fetched", chars)
            }
            "web_search" => {
                // Count the numbered results
                let count = output.lines().filter(|l| l.starts_with(|c: char| c.is_ascii_digit())).count();
                format!("{} results", count)
            }
            "find_definition" | "find_references" => {
                let count = output.lines().count();
                if count == 1 && output.contains("No ") {
                    output.trim().to_string()
                } else {
                    format!("{} results", count)
                }
            }
            "run_tests" => {
                if output.contains("PASSED") {
                    "tests passed".to_string()
                } else if output.contains("FAILED") {
                    "tests failed".to_string()
                } else {
                    "tests completed".to_string()
                }
            }
            "spawn_agent" => {
                let lines = output.lines().count();
                format!("sub-agent returned {} lines", lines)
            }
            "todo_write" => {
                safe_truncate(output, 80).to_string()
            }
            _ => {
                safe_truncate(output, 60).to_string()
            }
        }
    }

    /// Shrink tool results in older messages to reduce context window growth.
    /// Keeps the last `keep_recent` messages untouched; replaces large ToolResult
    /// content in older messages with a compact summary line.
    /// This is the primary mechanism for controlling cumulative input token cost:
    /// without it, a 5000-char file read at iteration 5 is re-sent in all 40+
    /// subsequent API calls. With it, that read becomes ~150 chars after 2 iterations.
    fn shrink_old_tool_results(messages: &mut [Message], keep_recent: usize) {
        let threshold = 500; // chars — results shorter than this are already cheap
        let len = messages.len();
        if len <= keep_recent {
            return;
        }
        let cutoff = len - keep_recent;

        // First pass: build a map of tool_use_id -> tool_name from assistant messages
        let mut tool_name_map: std::collections::HashMap<String, String> = std::collections::HashMap::new();
        for msg in messages.iter().take(cutoff) {
            if let MessageContent::Blocks(blocks) = &msg.content {
                for block in blocks {
                    if let ContentBlock::ToolUse { id, name, .. } = block {
                        tool_name_map.insert(id.clone(), name.clone());
                    }
                }
            }
        }

        // Second pass: shrink large tool results
        for msg in &mut messages[..cutoff] {
            if let MessageContent::Blocks(blocks) = &mut msg.content {
                for block in blocks.iter_mut() {
                    if let ContentBlock::ToolResult { tool_use_id, content, is_error, .. } = block {
                        if content.len() <= threshold {
                            continue;
                        }
                        // Don't shrink error results — they're usually short and important
                        if *is_error == Some(true) {
                            continue;
                        }
                        let tool_name = tool_name_map.get(tool_use_id.as_str())
                            .map(|s| s.as_str()).unwrap_or("tool");
                        let line_count = content.lines().count();
                        let char_count = content.len();

                        // Keep first few lines as preview (structural info, function sigs)
                        // More lines for read_file/grep since those carry important context
                        let preview_lines = match tool_name {
                            "read_file" | "grep_search" | "find_definition" | "find_references" => 5,
                            "shell_exec" | "run_tests" => 3,
                            _ => 2,
                        };
                        let preview: String = content.lines().take(preview_lines)
                            .collect::<Vec<_>>().join("\n");
                        let preview_short = safe_truncate(&preview, 300);
                        *content = format!(
                            "[Previous {} result — {} lines, {} chars]\n{}\n[... truncated from history — use read_file to re-read if needed]",
                            tool_name, line_count, char_count, preview_short
                        );
                    }
                }
            }
        }
    }

    /// Extract repository name from git clone command
    fn extract_repo_name_from_clone_command(&self, command: &str) -> Option<String> {
        // Handle various git clone formats
        let parts: Vec<&str> = command.split_whitespace().collect();
        
        for (i, part) in parts.iter().enumerate() {
            if part == &"clone" && i + 1 < parts.len() {
                let repo_url = parts[i + 1];
                
                // Extract repo name from URL (e.g., "https://github.com/user/repo.git" -> "repo")
                if let Some(last_part) = repo_url.split('/').last() {
                    let repo_name = last_part.trim_end_matches(".git");
                    return Some(repo_name.to_string());
                }
            }
        }
        
        None
    }
}