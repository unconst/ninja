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
    /// Extended thinking budget in tokens (0 = disabled). Anthropic models only.
    pub thinking_budget: u64,
    /// Temperature for generation (None uses model default).
    pub temperature: Option<f64>,
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
    /// MCP server manager for external tool integrations.
    mcp_manager: crate::tools::mcp::McpManager,
}

impl AgentRunner {
    pub fn new(config: AgentConfig) -> Self {
        let mut client = ApiClient::new(&config.api_key, &config.api_base_url, &config.model);
        if config.thinking_budget > 0 {
            client.set_thinking_budget(config.thinking_budget);
        }
        if let Some(temp) = config.temperature {
            client.set_temperature(temp);
        }

        // Initialize MCP connections
        let mut mcp_manager = crate::tools::mcp::McpManager::new();
        let mcp_configs = crate::tools::mcp::McpManager::load_config(&config.workdir);
        if !mcp_configs.is_empty() {
            eprintln!("Connecting to {} MCP server(s)...", mcp_configs.len());
            let errors = mcp_manager.connect_all(mcp_configs);
            for err in &errors {
                eprintln!("  MCP error: {}", err);
            }
        }

        Self {
            config,
            client,
            conversation: Vec::new(),
            system_prompt: None,
            last_was_read_only: true,
            mcp_manager,
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
                | "git_status" | "git_diff" | "git_log"
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
        let mut tool_defs = tools::get_tool_definitions();
        // Append MCP tools
        tool_defs.extend(self.mcp_manager.tool_definitions());
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
            if iteration == 8 {
                let diff_stat = Self::get_git_diff_stat(&self.config.workdir);
                if diff_stat.is_empty() {
                    self.conversation.push(Message {
                        role: "user".to_string(),
                        content: MessageContent::Text(
                            "[SYSTEM] PROGRESS CHECK — You've used 8 iterations without modifying any files. \
                             If the task requires code changes, start implementing now. If you're still \
                             exploring, form a plan and begin editing.".to_string()
                        ),
                    });
                }
            } else if iteration == 10 {
                let diff_stat = Self::get_git_diff_stat(&self.config.workdir);
                if diff_stat.is_empty() {
                    self.conversation.push(Message {
                        role: "user".to_string(),
                        content: MessageContent::Text(
                            "[SYSTEM] CRITICAL — 10 iterations used with ZERO files modified. \
                             You MUST start editing files NOW. Stop reading and start implementing. \
                             You have a plan — execute it. Open the most important file and make \
                             your first edit immediately in your next response.".to_string()
                        ),
                    });
                }
            } else if iteration == 15 {
                let diff_stat = Self::get_git_diff_stat(&self.config.workdir);
                let files_modified = diff_stat.lines()
                    .filter(|l| l.contains('|'))
                    .count();
                let diff_preview = if diff_stat.is_empty() {
                    "WARNING: Still no files modified.".to_string()
                } else {
                    diff_stat.lines().take(15).collect::<Vec<_>>().join("\n")
                };
                let plan_hint = match std::fs::read_to_string("/tmp/.ninja_plan.md") {
                    Ok(plan) if !plan.trim().is_empty() => {
                        let trunc = safe_truncate(plan.trim(), 1000);
                        let urgency = if files_modified <= 1 {
                            " CRITICAL: You've barely started editing. Stop perfecting one file and \
                             make a MINIMAL change to EACH file in your plan before returning to polish."
                        } else {
                            ""
                        };
                        format!("\n\nYour plan:\n```\n{}\n```\n\n\
                                 You've modified {} file(s) so far.{} MOVE ON to untouched files NOW. \
                                 Do NOT perfect one file before touching the others — make a minimal \
                                 change to each planned file first, then come back to refine.", trunc, files_modified, urgency)
                    }
                    _ => format!("\n\nYou've modified {} file(s) so far. If the task requires changes \
                                  to more files, move on to untouched files NOW.", files_modified),
                };
                self.conversation.push(Message {
                    role: "user".to_string(),
                    content: MessageContent::Text(format!(
                        "[SYSTEM] MID-RUN CHECK — Iteration 15 of {}. Half your budget is used.\n\
                         Progress so far:\n```\n{}\n```{}",
                        self.config.max_iterations, diff_preview, plan_hint
                    )),
                });
            } else if iteration == 20 || iteration == 40 {
                let diff_stat = Self::get_git_diff_stat(&self.config.workdir);
                let diff_preview = if diff_stat.is_empty() {
                    "No files modified yet.".to_string()
                } else {
                    diff_stat.lines().take(20).collect::<Vec<_>>().join("\n")
                };
                let plan_recovery = match std::fs::read_to_string("/tmp/.ninja_plan.md") {
                    Ok(plan) if !plan.trim().is_empty() => {
                        let trunc = safe_truncate(plan.trim(), 2000);
                        format!("\n\nYour plan (from /tmp/.ninja_plan.md):\n```\n{}\n```", trunc)
                    }
                    _ => String::new(),
                };
                self.conversation.push(Message {
                    role: "user".to_string(),
                    content: MessageContent::Text(format!(
                        "[SYSTEM] PROGRESS — Iteration {}. Check your todo list and assess:\n\
                         1. What have you completed so far?\n\
                         2. What remains? Are you stuck on anything?\n\
                         3. What's your plan for the remaining {} iterations?\n\
                         4. Have you identified ALL files that need changes? Don't forget: \
                         docs, changelog, config files (pyproject.toml, setup.cfg), \
                         CI workflows, type stubs, __init__.py exports, test output files.\n\n\
                         Current changes:\n```\n{}\n```{}", iteration + 1, remaining, diff_preview, plan_recovery
                    )),
                });
            } else if remaining == 10 {
                let diff_stat = Self::get_git_diff_stat(&self.config.workdir);
                let files_modified = diff_stat.lines()
                    .filter(|l| l.contains('|'))
                    .count();
                if files_modified >= 3 {
                    self.conversation.push(Message {
                        role: "user".to_string(),
                        content: MessageContent::Text(format!(
                            "[SYSTEM] VERIFICATION SWEEP — 10 iterations left, {} files modified.\n\
                             BEFORE finishing, you MUST do a completeness check:\n\
                             1. Re-read your plan from /tmp/.ninja_plan.md\n\
                             2. Run grep_search for any OLD names/patterns that should have been replaced. \
                             Any remaining reference to old names in .py files is a bug — fix it now.\n\
                             3. Run tests if available. If tests fail, fix the failures.\n\
                             4. Check your todo list — any items still pending?\n\n\
                             Current changes:\n```\n{}\n```", files_modified, diff_stat
                        )),
                    });
                }
            } else if remaining == 5 {
                let diff_stat = Self::get_git_diff_stat(&self.config.workdir);
                let diff_section = if diff_stat.is_empty() {
                    "WARNING: No files modified yet.".to_string()
                } else {
                    format!("Current changes:\n```\n{}\n```", diff_stat)
                };
                self.conversation.push(Message {
                    role: "user".to_string(),
                    content: MessageContent::Text(format!(
                        "[SYSTEM] 5 iterations remaining. Wrap up your changes.\n\
                         1. Re-read /tmp/.ninja_plan.md to check your original file list.\n\
                         2. Compare that list against the diff below. Any planned files NOT \
                         in the diff still need editing — even small changes like docstrings or version bumps.\n\
                         3. Complete any pending todo items before finishing.\n\n\
                         {}", diff_section
                    )),
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
                if used_pct < 0.3 && !completion_check_done {
                    completion_check_done = true;
                    self.conversation.push(Message {
                        role: "assistant".to_string(),
                        content: MessageContent::Text(response.text.clone()),
                    });

                    let diff_stat = Self::get_git_diff_stat(&self.config.workdir);
                    let diff_context = if diff_stat.is_empty() {
                        "\n\nNo files modified yet.".to_string()
                    } else {
                        format!("\n\nCurrent changes:\n```\n{}\n```", diff_stat)
                    };

                    self.conversation.push(Message {
                        role: "user".to_string(),
                        content: MessageContent::Text(format!(
                            "[SYSTEM] You stopped very early. Before finishing, double-check:\n\
                             1. Have you addressed all parts of the task?\n\
                             2. Check your todo list — are all items done?\
                             {}\n\n\
                             If truly done, respond with your summary and no tool calls.",
                            diff_context
                        )),
                    });
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
        let mut tool_defs = tools::get_tool_definitions();
        // Append MCP tools
        tool_defs.extend(self.mcp_manager.tool_definitions());

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
        let mut last_idle_nudge: usize = 0;
        let mut edit_successes: usize = 0;
        let mut edit_failures: usize = 0;
        let mut consecutive_edit_failures: usize = 0;
        let mut last_test_checkpoint: usize = 0;
        let mut first_edit_iteration: Option<usize> = None;

        for iteration in 0..self.config.max_iterations {
            rollout.iteration_count = (iteration + 1) as u64;

            let current_model = self.client.model().to_string();
            rollout.log_iteration(iteration + 1, &current_model);

            if self.config.verbose {
                eprintln!("[iteration {}]", iteration + 1);
            }

            // Inject phase transition and urgency reminders
            let remaining = self.config.max_iterations - iteration;
            if iteration == 8 {
                let diff_stat = Self::get_git_diff_stat(&self.config.workdir);
                if diff_stat.is_empty() {
                    messages.push(Message {
                        role: "user".to_string(),
                        content: MessageContent::Text(
                            "[SYSTEM] PROGRESS CHECK — You've used 8 iterations without modifying any files. \
                             If the task requires code changes, start implementing now. If you're still \
                             exploring, form a plan and begin editing.".to_string()
                        ),
                    });
                }
            } else if iteration == 10 {
                let diff_stat = Self::get_git_diff_stat(&self.config.workdir);
                if diff_stat.is_empty() {
                    messages.push(Message {
                        role: "user".to_string(),
                        content: MessageContent::Text(
                            "[SYSTEM] CRITICAL — 10 iterations used with ZERO files modified. \
                             You MUST start editing files NOW. Stop reading and start implementing. \
                             You have a plan — execute it. Open the most important file and make \
                             your first edit immediately in your next response.".to_string()
                        ),
                    });
                }
            } else if iteration == 15 {
                let diff_stat = Self::get_git_diff_stat(&self.config.workdir);
                let files_modified = diff_stat.lines()
                    .filter(|l| l.contains('|'))
                    .count();
                let diff_preview = if diff_stat.is_empty() {
                    "WARNING: Still no files modified.".to_string()
                } else {
                    diff_stat.lines().take(15).collect::<Vec<_>>().join("\n")
                };
                let plan_hint = match std::fs::read_to_string("/tmp/.ninja_plan.md") {
                    Ok(plan) if !plan.trim().is_empty() => {
                        let trunc = safe_truncate(plan.trim(), 1000);
                        let urgency = if files_modified <= 1 {
                            " CRITICAL: You've barely started editing. Stop perfecting one file and \
                             make a MINIMAL change to EACH file in your plan before returning to polish."
                        } else {
                            ""
                        };
                        format!("\n\nYour plan:\n```\n{}\n```\n\n\
                                 You've modified {} file(s) so far.{} MOVE ON to untouched files NOW. \
                                 Do NOT perfect one file before touching the others — make a minimal \
                                 change to each planned file first, then come back to refine.", trunc, files_modified, urgency)
                    }
                    _ => format!("\n\nYou've modified {} file(s) so far. If the task requires changes \
                                  to more files, move on to untouched files NOW.", files_modified),
                };
                messages.push(Message {
                    role: "user".to_string(),
                    content: MessageContent::Text(format!(
                        "[SYSTEM] MID-RUN CHECK — Iteration 15 of {}. Half your budget is used.\n\
                         Progress so far:\n```\n{}\n```{}",
                        self.config.max_iterations, diff_preview, plan_hint
                    )),
                });
            } else if iteration == 20 || iteration == 30 || iteration == 40 || iteration == 60 {
                let diff_stat = Self::get_git_diff_stat(&self.config.workdir);
                let diff_preview = if diff_stat.is_empty() {
                    "No files modified yet.".to_string()
                } else {
                    diff_stat.lines().take(20).collect::<Vec<_>>().join("\n")
                };
                // Auto-recover plan file at major checkpoints
                let plan_recovery = match std::fs::read_to_string("/tmp/.ninja_plan.md") {
                    Ok(plan) if !plan.trim().is_empty() => {
                        let trunc = safe_truncate(plan.trim(), 2000);
                        format!("\n\nYour plan (from /tmp/.ninja_plan.md):\n```\n{}\n```", trunc)
                    }
                    _ => String::new(),
                };
                // Add edit quality stats at checkpoints for longer tasks
                let total_edits_so_far = edit_successes + edit_failures;
                let edit_stats = if total_edits_so_far > 0 {
                    format!("\n\nEdit quality: {}/{} succeeded ({:.0}%), {} consecutive failures",
                        edit_successes, total_edits_so_far,
                        100.0 * edit_successes as f64 / total_edits_so_far as f64,
                        consecutive_edit_failures)
                } else {
                    String::new()
                };
                messages.push(Message {
                    role: "user".to_string(),
                    content: MessageContent::Text(format!(
                        "[SYSTEM] PROGRESS — Iteration {}. Check your todo list and assess:\n\
                         1. What have you completed so far?\n\
                         2. What remains? Are you stuck on anything?\n\
                         3. What's your plan for the remaining {} iterations?\n\
                         4. Have you identified ALL files that need changes? Don't forget: \
                         docs, changelog, config files (pyproject.toml, setup.cfg), \
                         CI workflows, type stubs, __init__.py exports, test output files.\n\n\
                         Current changes:\n```\n{}\n```{}{}", iteration + 1, remaining, diff_preview, plan_recovery, edit_stats
                    )),
                });
            } else if remaining == 10 {
                let diff_stat = Self::get_git_diff_stat(&self.config.workdir);
                let files_modified = diff_stat.lines()
                    .filter(|l| l.contains('|'))
                    .count();
                if files_modified >= 3 {
                    messages.push(Message {
                        role: "user".to_string(),
                        content: MessageContent::Text(format!(
                            "[SYSTEM] VERIFICATION SWEEP — 10 iterations left, {} files modified.\n\
                             BEFORE finishing, you MUST do a completeness check:\n\
                             1. Re-read your plan from /tmp/.ninja_plan.md\n\
                             2. Run grep_search for any OLD names/patterns that should have been replaced. \
                             Any remaining reference to old names in .py files is a bug — fix it now.\n\
                             3. Run tests if available. If tests fail, fix the failures.\n\
                             4. Check your todo list — any items still pending?\n\n\
                             Current changes:\n```\n{}\n```", files_modified, diff_stat
                        )),
                    });
                }
            } else if remaining == 5 {
                let diff_stat = Self::get_git_diff_stat(&self.config.workdir);
                let diff_section = if diff_stat.is_empty() {
                    "WARNING: No files modified yet.".to_string()
                } else {
                    format!("Current changes:\n```\n{}\n```", diff_stat)
                };
                messages.push(Message {
                    role: "user".to_string(),
                    content: MessageContent::Text(format!(
                        "[SYSTEM] 5 iterations remaining. Wrap up your changes.\n\
                         1. Re-read /tmp/.ninja_plan.md to check your original file list.\n\
                         2. Compare that list against the diff below. Any planned files NOT \
                         in the diff still need editing — even small changes like docstrings or version bumps.\n\
                         3. Complete any pending todo items before finishing.\n\n\
                         {}", diff_section
                    )),
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
                if used_pct < 0.3 && !completion_check_done {
                    completion_check_done = true;
                    messages.push(Message {
                        role: "assistant".to_string(),
                        content: MessageContent::Text(response.text.clone()),
                    });

                    let diff_stat = Self::get_git_diff_stat(&self.config.workdir);
                    let diff_context = if diff_stat.is_empty() {
                        "\n\nNo files modified yet.".to_string()
                    } else {
                        format!("\n\nCurrent changes:\n```\n{}\n```", diff_stat)
                    };

                    messages.push(Message {
                        role: "user".to_string(),
                        content: MessageContent::Text(format!(
                            "[SYSTEM] You stopped very early. Before finishing, double-check:\n\
                             1. Have you addressed all parts of the task?\n\
                             2. Check your todo list — are all items done?\
                             {}\n\n\
                             If truly done, respond with your summary and no tool calls.",
                            diff_context
                        )),
                    });
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

                // Save file contents before editing for auto-revert on syntax errors
                let mut pre_edit_contents: Vec<Option<String>> = vec![None; response.tool_calls.len()];
                for (i, tc) in response.tool_calls.iter().enumerate() {
                    if tc.name == "replace_lines" || tc.name == "write_file" {
                        if let Some(path_str) = tc.input.get("path").and_then(|v| v.as_str()) {
                            if path_str.ends_with(".py") {
                                let resolved = if Path::new(path_str).is_absolute() {
                                    PathBuf::from(path_str)
                                } else {
                                    self.config.workdir.join(path_str)
                                };
                                if let Ok(content) = std::fs::read_to_string(&resolved) {
                                    pre_edit_contents[i] = Some(content);
                                }
                            }
                        }
                    }
                }

                // Pre-resolve: handle MCP tools and git clone interception before spawning
                // Each entry: (index, Option<pre-resolved result>)
                let mut pre_resolved: Vec<Option<Result<String, String>>> = vec![None; response.tool_calls.len()];
                for (i, tc) in response.tool_calls.iter().enumerate() {
                    // Git clone interception
                    if tc.name == "shell_exec" {
                        if let Some(command) = tc.input.get("command").and_then(|c| c.as_str()) {
                            if command.starts_with("git clone") {
                                if let Some(recovery_result) = self.check_git_clone_necessity(command) {
                                    pre_resolved[i] = Some(Ok(recovery_result));
                                }
                            }
                        }
                    }
                    // MCP tool routing (MCP connections are not Send, must run on main)
                    if self.mcp_manager.is_mcp_tool(&tc.name) {
                        pre_resolved[i] = Some(self.mcp_manager.execute_tool(&tc.name, &tc.input));
                    }
                }

                let mut handles: Vec<Option<tokio::task::JoinHandle<(String, Result<String, String>, std::time::Duration)>>> = Vec::new();
                for (i, tc) in response.tool_calls.iter().enumerate() {
                    if pre_resolved[i].is_some() {
                        handles.push(None); // Already resolved
                    } else {
                        let name = tc.name.clone();
                        let input = tc.input.clone();
                        let workdir = self.config.workdir.clone();
                        handles.push(Some(tokio::task::spawn_blocking(move || {
                            let start = Instant::now();
                            let result = tools::execute_tool(&name, &input, &workdir);
                            let duration = start.elapsed();
                            (name, result, duration)
                        })));
                    }
                }

                // Collect results from both pre-resolved and spawned tasks
                for (i, handle_opt) in handles.into_iter().enumerate() {
                    let tc = &response.tool_calls[i];
                    let (result, tool_duration) = if let Some(pre) = pre_resolved[i].take() {
                        (pre, std::time::Duration::ZERO)
                    } else if let Some(handle) = handle_opt {
                        match handle.await {
                            Ok((_name, result, dur)) => (result, dur),
                            Err(e) => (Err(format!("Task panicked: {}", e)), std::time::Duration::ZERO),
                        }
                    } else {
                        (Err("Internal error: no handle or pre-resolved result".to_string()), std::time::Duration::ZERO)
                    };

                    // Post-process: edit validation, lint checks, and error recovery
                    let (output, is_error) = match result {
                        Ok(output) => {
                            if tc.name == "edit_file" {
                                if let Some(validated) = self.validate_file_edit(&tc.input, &output) {
                                    (validated, false)
                                } else {
                                    (output, false)
                                }
                            } else if tc.name == "replace_lines" || tc.name == "write_file" {
                                // Lint check for Python files after replace_lines/write_file
                                let path_str = tc.input.get("path").and_then(|v| v.as_str()).unwrap_or("");
                                if path_str.ends_with(".py") {
                                    let resolved = if Path::new(path_str).is_absolute() {
                                        PathBuf::from(path_str)
                                    } else {
                                        self.config.workdir.join(path_str)
                                    };
                                    let lint_msg = self.lint_python_file(&resolved);
                                    if !lint_msg.is_empty() {
                                        // Auto-revert on syntax errors if we have the original content
                                        if (lint_msg.contains("invalid-syntax") || lint_msg.contains("SYNTAX ERROR"))
                                            && pre_edit_contents[i].is_some()
                                        {
                                            let original = pre_edit_contents[i].as_ref().unwrap();
                                            let _ = std::fs::write(&resolved, original);
                                            (format!(
                                                "EDIT REVERTED — your {} introduced a syntax error.\n{}\n\n\
                                                 The file has been restored to its previous state. \
                                                 Please fix the syntax and try again.",
                                                tc.name, lint_msg
                                            ), false)
                                        } else {
                                            (format!("{}{}", output, lint_msg), false)
                                        }
                                    } else {
                                        // Lint passed — check for signature changes on write_file/replace_lines
                                        if tc.name == "write_file" || tc.name == "replace_lines" {
                                            if let Some(ref old_content) = pre_edit_contents[i] {
                                                let new_content = std::fs::read_to_string(&resolved).unwrap_or_default();
                                                let sig_warning = self.check_signature_changes(old_content, &new_content);
                                                if !sig_warning.is_empty() {
                                                    (format!("{}{}", output, sig_warning), false)
                                                } else {
                                                    (output, false)
                                                }
                                            } else {
                                                (output, false)
                                            }
                                        } else {
                                            (output, false)
                                        }
                                    }
                                } else {
                                    (output, false)
                                }
                            } else {
                                (output, false)
                            }
                        }
                        Err(error) => {
                            if let Some(recovered) = self.try_recover_from_error(&tc.name, &tc.input, &error) {
                                (recovered, false)
                            } else {
                                (error, true)
                            }
                        }
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

            // Track edit success/failure from tool results
            for (i, tc) in response.tool_calls.iter().enumerate() {
                if tc.name == "edit_file" || tc.name == "replace_lines" || tc.name == "write_file" {
                    if first_edit_iteration.is_none() {
                        first_edit_iteration = Some(iteration);
                    }
                    if let ContentBlock::ToolResult { content, is_error, .. } = &result_blocks[i] {
                        let failed = *is_error == Some(true)
                            || content.contains("EDIT REVERTED")
                            || content.contains("LINT ERRORS")
                            || content.contains("String not found")
                            || content.contains("not found in file")
                            || content.contains("SYNTAX ERROR");
                        if failed {
                            edit_failures += 1;
                            consecutive_edit_failures += 1;
                        } else {
                            edit_successes += 1;
                            consecutive_edit_failures = 0;
                        }
                    }
                }
            }

            // Strategy switch enforcement: after 3 consecutive edit failures, inject hard directive
            if consecutive_edit_failures >= 3 {
                messages.push(Message {
                    role: "user".to_string(),
                    content: MessageContent::Text(format!(
                        "[SYSTEM] STRATEGY SWITCH REQUIRED — {} consecutive edit failures. STOP your current approach.\n\
                         1. Re-read the target file(s) completely — your cached view is stale.\n\
                         2. Re-read /tmp/.ninja_plan.md to review what you've already tried.\n\
                         3. Use `think` to reason about a fundamentally different approach.\n\
                         4. If edit_file keeps failing, switch to write_file or replace_lines.\n\
                         5. If you're fighting the same code section, step back and check if your \
                         understanding of the problem is correct.\n\
                         Previous edit success rate: {}/{} ({:.0}%)",
                        consecutive_edit_failures,
                        edit_successes,
                        edit_successes + edit_failures,
                        if edit_successes + edit_failures > 0 {
                            100.0 * edit_successes as f64 / (edit_successes + edit_failures) as f64
                        } else { 0.0 }
                    )),
                });
                consecutive_edit_failures = 0; // Reset after injecting
            }

            // Edit quality degradation warning: if success rate drops below 50% after 6+ edits
            let total_edits = edit_successes + edit_failures;
            if total_edits >= 6 && edit_failures > edit_successes {
                let success_rate = 100.0 * edit_successes as f64 / total_edits as f64;
                if total_edits % 4 == 0 { // Don't spam — check every 4 edits
                    messages.push(Message {
                        role: "user".to_string(),
                        content: MessageContent::Text(format!(
                            "[SYSTEM] EDIT QUALITY WARNING — Your edit success rate is {:.0}% ({}/{} edits succeeded). \
                             SLOW DOWN. Before each edit:\n\
                             1. Re-read the FULL target file (not just a section)\n\
                             2. Copy the EXACT text you want to replace (including whitespace)\n\
                             3. Use replace_lines with line numbers when edit_file fails\n\
                             4. After each successful edit, verify with read_file",
                            success_rate, edit_successes, total_edits
                        )),
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

            // Nudge if 7+ consecutive read-only iterations (re-fires every 7)
            let idle_gap = iteration - last_write_iteration;
            if iteration > 7 && idle_gap >= 7 && (last_idle_nudge == 0 || iteration - last_idle_nudge >= 7) {
                last_idle_nudge = iteration;
                messages.push(Message {
                    role: "user".to_string(),
                    content: MessageContent::Text(
                        "[SYSTEM] You haven't modified any files in a while. If your work is complete, \
                         stop and provide your final summary. If there are remaining changes, proceed \
                         with implementing them now.".to_string()
                    ),
                });
            }

            // Periodic test checkpoint: every 15 iterations after first edit,
            // auto-run tests to catch semantic errors early before they cascade.
            if let Some(first_edit) = first_edit_iteration {
                if iteration > first_edit
                    && iteration >= 15
                    && (last_test_checkpoint == 0 || iteration - last_test_checkpoint >= 15)
                    && edit_successes > 0
                {
                    last_test_checkpoint = iteration;
                    // Run a quick test to detect silent regressions
                    let test_input = serde_json::json!({});
                    if let Ok(test_output) = tools::execute_tool("run_tests", &test_input, &self.config.workdir) {
                        let has_failures = test_output.contains("FAILED")
                            || test_output.contains("Error")
                            || test_output.contains("error:");
                        if has_failures {
                            // Extract last 20 lines of test output for context
                            let tail: String = test_output.lines()
                                .rev().take(20).collect::<Vec<_>>()
                                .into_iter().rev().collect::<Vec<_>>().join("\n");
                            messages.push(Message {
                                role: "user".to_string(),
                                content: MessageContent::Text(format!(
                                    "[SYSTEM] TEST CHECKPOINT (iteration {}) — Tests are FAILING. \
                                     Fix these before making more changes. Errors compound when you \
                                     edit more code on top of broken code.\n\
                                     Test output (last 20 lines):\n```\n{}\n```\n\
                                     Re-read the failing files and fix the regressions first.",
                                    iteration + 1, tail
                                )),
                            });
                        }
                    }
                }
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
            "You are Ninja, a fast and capable autonomous coding agent. You solve any software \
             engineering task — bug fixes, new features, refactors, research, devops, and more.\n\n\
             Working directory: {}\n\
             {}\n\n\
             ## Tools\n\
             - read_file: Read file contents (supports offset/limit for large files)\n\
             - write_file: Create or overwrite files\n\
             - edit_file: Replace string matches (with whitespace-fuzzy fallback). old_string MUST \
               be unique — include surrounding context lines. Set replace_all=true for all occurrences.\n\
             - replace_lines: Replace a range of lines by number (1-based, inclusive). \
               More reliable than edit_file for large changes. Read file first for line numbers.\n\
             - list_dir: List directory contents\n\
             - shell_exec: Run shell commands (bash)\n\
             - glob_search: Find files by name pattern\n\
             - grep_search: Search file contents with regex\n\
             - web_fetch: Fetch content from a URL\n\
             - web_search: Search the web for information\n\
             - find_definition: Find where a symbol is defined\n\
             - find_references: Find all references to a symbol\n\
             - run_tests: Run project tests (auto-detects framework, or custom command)\n\
             - spawn_agent: Launch a sub-agent for independent parallel tasks\n\
             - todo_write: Track progress on multi-step tasks\n\
             - think: Reason step-by-step before acting (no side effects)\n\
             - memory_write: Save discoveries or project notes to persistent memory\n\
             - oracle: Get a second opinion from a different AI model\n\
             - git_status, git_diff, git_log, git_commit: Git operations\n\n\
             ## How to Work\n\
             1. **Understand quickly (1-3 iterations).** Read the task. Explore just enough to \
                identify which files need changes — use grep_search, glob_search, find_definition. \
                Don't read every file. Target the specific code you need to change.\n\
             2. **Plan and externalize (1-2 iterations).** Use think to form a concrete plan: \
                root cause, which files to change, what each change is. Write the plan to \
                /tmp/.ninja_plan.md — this survives context compaction. Include a COMPLETE numbered \
                list of ALL files you'll modify — don't just list source code files. Also consider: \
                docs, changelog/HISTORY, config (pyproject.toml, setup.cfg), CI workflows, \
                type stubs, __init__.py exports, test output files. Use todo_write to track each file.\n\
             3. **Implement breadth-first.** Start editing by iteration 5 at the latest. For tasks \
                touching 4+ files, make one pass through ALL files with minimal correct changes \
                before polishing any single file. This ensures every file gets touched even if you \
                run low on iterations. Edit with precision — prefer small targeted edits. For large \
                changes (>20 lines), use replace_lines. Read back after editing to confirm.\n\
             4. **Ripple check.** After making your core changes, use find_references or grep_search to \
                find other files that reference the changed functions/classes/APIs. These files may also \
                need updating — especially: __init__.py __all__ lists and imports, type stubs (.pyi), \
                documentation, and downstream consumers. When you REMOVE a function, also grep for its \
                name in __init__.py files to clean up exports.\n\
             5. **Verify.** Run tests or linters when available. If the task specifies a verification \
                command (like a grep to check for remaining references), run it BEFORE declaring done. \
                If it shows remaining issues, fix them. Never stop while verification fails.\n\
             5b. **Rename verification.** When renaming symbols, classes, or field names: after all \
                edits, grep for the OLD name across ALL files (including tests, configs, docstrings, \
                string literals). Any remaining reference is a bug. Fix it before stopping.\n\
             6. **Summarize.** When done, list every file changed with a brief description.\n\n\
             ## Critical Rules\n\
             - **START EDITING EARLY.** You MUST begin making file changes within your first 5 \
               iterations. Reading and planning beyond that is analysis paralysis.\n\
             - **Bias toward action.** When uncertain between exploring more and editing, choose \
               editing. You can always fix mistakes — but you can't recover wasted iterations.\n\
             - **Multiple tools per response.** Call several tools at once — they run concurrently. \
               Read multiple files at once. Make independent edits at once.\n\
             - **Never fabricate fixes.** If you cannot determine the correct change for a file, \
               do NOT edit a different file as a substitute. Re-read the target file fully, use \
               think to reason about what's needed, try the oracle tool. A wrong edit in the \
               wrong file is worse than no edit at all.\n\
             - **Read in large chunks.** When editing files with repetitive patterns or multiple \
               change sites, read 100+ lines at once to see the full picture. Don't read 20-30 \
               line chunks — that wastes iterations on re-reading.\n\
             - **Propagate patterns.** When you make the same type of change (e.g., updating an import, \
                adding a parameter, changing an API call) in one file, grep for the same pattern in \
                ALL other files. Don't fix it in one place and forget the rest.\n\
             - **Preserve existing names, signatures, and return types.** Do NOT rename fields, methods, \
               attributes, or variables unless the task explicitly asks you to. When rewriting a \
               function or module, keep ALL existing function signatures exactly as they are — same \
               parameter names, same parameter order, same defaults, same return type. If a function \
               returns a User object, the rewritten version must also return a User object (not a \
               plain dict). Before rewriting a file with write_file, read ALL callers first (grep for \
               function names) to understand: (1) what arguments callers pass, (2) what callers do \
               with the return value (do they call .to_dict(), .id, .name on it?). Changing return \
               types from objects to dicts or vice versa breaks callers just as badly as changing \
               parameter names.\n\
             - **Preserve existing structures.** When the task says 'rename X to Y' or 'change X', \
               modify the existing data structure in place — do NOT delete it and rewrite from \
               scratch. Schema dicts, config defaults, class hierarchies should be updated, not \
               replaced with simplified versions.\n\
             - **Preserve module-level public names.** Module-level constants, registries, and \
               dict names (e.g., BACKEND_REGISTRY, DEFAULT_CONFIG, ROUTES) are public API — other \
               files import them by name. When refactoring a module, keep all module-level names \
               that existed before. If tests or other files do `from module import SOME_NAME`, \
               that name must still exist and be importable after your changes.\n\
             - **Minimal test file changes.** When editing test files, ONLY make the specific \
               change needed (e.g., remove specific test functions, update field names). Do NOT \
               restructure the test framework (e.g., don't convert standalone functions to \
               unittest.TestCase), reformat the file, or change the test runner. The output \
               format of test runs must remain the same.\n\n\
             ## Principles\n\
             - **Speed over perfection.** Act decisively. Don't over-explore or over-analyze.\n\
             - **Parallelize aggressively.** Call multiple tools per response — they execute concurrently. \
               For tasks touching 5+ files, use spawn_agent to edit different files in parallel. \
               Give each sub-agent a specific file path, the exact change needed, and enough context. \
               This multiplies your effective iteration budget.\n\
             - **Be precise.** Minimal changes. Don't over-engineer or add unnecessary code.\n\
             - **Read fully.** Don't use offset/limit unless a file is >2000 lines. \
               Config files are small — always read completely.\n\
             - **Recover from errors.** If edit_file fails with 'String not found', re-read the \
               file and copy the EXACT text. After 2 failures, use write_file to overwrite. \
               If stuck on one approach for 3+ iterations, switch strategies entirely.\n\
             - **Efficient renames.** When renaming a symbol across a file, use \
               edit_file with replace_all=true (e.g., old_string=\"DataProcessor\", \
               new_string=\"PipelineExecutor\", replace_all=true). This handles all \
               occurrences in one call — much faster than individual edits. Do this \
               for EACH file separately.\n\
             - **Track progress.** For multi-step tasks, use todo_write to maintain a checklist.\n\
             - **Breadth before depth.** For multi-file changes, make ONE focused pass through \
               each file before returning for second passes. Don't spend 10+ iterations perfecting \
               one file while others remain untouched. If an edit fails twice, move to the next \
               file and come back later.\n\
             - **Externalize state.** Always write your plan to /tmp/.ninja_plan.md before editing. \
               After context compaction, re-read it to stay on track. Also log failed approaches \
               there — what you tried, why it failed, and what to try next.\n\
             - **Use tests.** If tests exist, run them to verify. If a test patch is provided, \
               apply it first, then implement to pass the tests.\n\
             - **Don't give up.** If stuck on an approach, try alternatives. If an edit keeps \
               failing, try write_file, replace_lines, or break into smaller pieces.\n\
             - **Switch strategies after 3 failures.** If the same approach fails 3 times, stop and \
               rethink. Use think to reason about why it's failing, consult your plan file for \
               what you already tried, and choose a fundamentally different strategy.\n\
             - **Use oracle when stuck on reasoning.** If you've read the relevant code but can't \
               determine the correct fix, call oracle with a focused question about the specific \
               code change needed. Don't spin reading the same files repeatedly.\n\
             - **Watch for dead code and duplicate definitions.** In Python, if a function/class is \
               defined twice in the same file, the LAST definition wins — earlier ones are dead code. \
               This applies both to code YOU write and to code that ALREADY EXISTS in the file. \
               When you find a bug in a function that's defined twice, do NOT just patch the buggy \
               copy — DELETE the duplicate entirely so only one canonical definition remains. \
               When your edit doesn't change test results, check: (1) is your code actually being \
               called? (2) grep the file for duplicate definitions of the same name. (3) add a \
               print() to verify execution reaches your code.",
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

        // Include repo map for codebase awareness
        let repo_map = Self::generate_repo_map(&self.config.workdir);
        if !repo_map.is_empty() {
            prompt.push_str(&format!(
                "\n\n## Repository Map\nFiles and symbols in the working directory:\n```\n{}\n```",
                repo_map.trim()
            ));
        }

        // Load persistent memory
        if let Some(memory_section) = crate::tools::memory::load_project_memory(&self.config.workdir) {
            prompt.push_str(&format!("\n\n{}", memory_section));
        }

        prompt
    }

    /// Generate a symbol-aware repository map for the system prompt.
    /// For Python files, extracts class/function definitions using AST parsing.
    /// Shows a compact tree with symbols, capped at ~200 lines.
    fn generate_repo_map(workdir: &Path) -> String {
        use std::collections::BTreeMap;

        let output = match std::process::Command::new("find")
            .args(&[
                ".", "-type", "f",
                "-not", "-path", "./.git/*",
                "-not", "-path", "./node_modules/*",
                "-not", "-path", "./.tox/*",
                "-not", "-path", "./.nox/*",
                "-not", "-path", "./__pycache__/*",
                "-not", "-path", "*/__pycache__/*",
                "-not", "-path", "./.venv/*",
                "-not", "-path", "./venv/*",
                "-not", "-path", "./target/*",
                "-not", "-path", "./.mypy_cache/*",
                "-not", "-path", "./.pytest_cache/*",
                "-not", "-path", "*/.pytest_cache/*",
                "-not", "-path", "./*.egg-info/*",
                "-not", "-path", "*/*.egg-info/*",
                "-not", "-path", "./build/*",
                "-not", "-path", "./dist/*",
                "-not", "-path", "./.eggs/*",
                "-not", "-name", "*.pyc",
                "-not", "-name", "*.pyo",
            ])
            .current_dir(workdir)
            .output()
        {
            Ok(o) if o.status.success() => o,
            _ => return String::new(),
        };

        let stdout = String::from_utf8_lossy(&output.stdout);
        let mut files: Vec<String> = stdout.lines()
            .map(|l| l.strip_prefix("./").unwrap_or(l).to_string())
            .filter(|l| !l.is_empty())
            .collect();
        files.sort();

        if files.is_empty() {
            return String::new();
        }

        // Collect Python source files (non-test, non-config) for symbol extraction
        let py_source_files: Vec<&str> = files.iter()
            .filter(|f| f.ends_with(".py"))
            .filter(|f| {
                // Skip test files, setup/config, and migration files
                let fname = f.rsplit('/').next().unwrap_or(f);
                !fname.starts_with("test_")
                    && !fname.starts_with("conftest")
                    && fname != "setup.py"
                    && fname != "noxfile.py"
                    && fname != "fabfile.py"
                    && !f.contains("/tests/")
                    && !f.contains("/test/")
                    && !f.contains("/migrations/")
            })
            .map(|f| f.as_str())
            .take(80) // Cap to avoid slow AST parsing on huge repos
            .collect();

        // Extract symbols from Python files using ast module
        let symbols = Self::extract_python_symbols(workdir, &py_source_files);

        // Build directory tree with symbol annotations
        let mut tree: BTreeMap<String, Vec<(String, Option<String>)>> = BTreeMap::new();
        for file in &files {
            let parts: Vec<&str> = file.rsplitn(2, '/').collect();
            let (dir, fname) = if parts.len() == 2 {
                (parts[1].to_string(), parts[0].to_string())
            } else {
                (".".to_string(), parts[0].to_string())
            };
            let sym_info = symbols.get(file.as_str()).cloned();
            tree.entry(dir).or_default().push((fname, sym_info));
        }

        let mut result = String::new();
        let mut lines = 0;
        let max_lines = 200;

        for (dir, dir_files) in &tree {
            if lines >= max_lines {
                result.push_str(&format!("... ({} more directories)\n", tree.len()));
                break;
            }
            if dir_files.len() <= 10 {
                for (fname, sym_info) in dir_files {
                    let path = if dir == "." {
                        fname.clone()
                    } else {
                        format!("{}/{}", dir, fname)
                    };
                    if let Some(syms) = sym_info {
                        // Show file with symbols: path: Class, func, func
                        result.push_str(&format!("{}: {}\n", path, syms));
                    } else {
                        result.push_str(&format!("{}\n", path));
                    }
                    lines += 1;
                    if lines >= max_lines {
                        break;
                    }
                }
            } else {
                // Summarize large directories
                result.push_str(&format!("{}/  ({} files)\n", dir, dir_files.len()));
                lines += 1;
            }
        }

        result
    }

    /// Extract top-level class and function definitions from Python files using ast.parse.
    /// Returns a map of file path -> comma-separated symbol string.
    fn extract_python_symbols<'a>(
        workdir: &Path,
        files: &[&'a str],
    ) -> std::collections::HashMap<&'a str, String> {
        use std::collections::HashMap;

        let mut result: HashMap<&str, String> = HashMap::new();
        if files.is_empty() {
            return result;
        }

        // Build a Python script that extracts symbols from multiple files.
        // We avoid Rust format! here since Python uses {} in .format() calls.
        let files_json: Vec<String> = files.iter().map(|f| format!("\"{}\"", f)).collect();
        let files_list = files_json.join(", ");
        let mut script = String::from(
            r#"
import ast, json, sys
files = ["#,
        );
        script.push_str(&files_list);
        script.push_str(
            r#"]
result = {}
for fpath in files:
    try:
        with open(fpath) as f:
            tree = ast.parse(f.read())
        symbols = []
        imports = []
        for node in ast.iter_child_nodes(tree):
            if isinstance(node, ast.ClassDef):
                methods = [n.name for n in ast.iter_child_nodes(node) if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and not n.name.startswith('_')]
                if methods:
                    symbols.append("class {}({})".format(node.name, ", ".join(methods[:5])))
                else:
                    symbols.append("class {}".format(node.name))
            elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                if not node.name.startswith('_'):
                    symbols.append("def {}".format(node.name))
            elif isinstance(node, ast.ImportFrom) and node.module:
                mod = node.module.split('.')[0]
                if mod not in ('os', 'sys', 'typing', 're', 'json', 'collections', 'functools', 'itertools', 'pathlib', 'abc', 'io', 'copy', 'enum', 'dataclasses', 'contextlib', 'warnings', 'logging', 'textwrap', 'inspect', 'importlib', 'unittest', 'pytest', 'math', 'datetime', 'time', 'hashlib', 'base64', 'struct', 'string', 'operator') and not mod.startswith('_'):
                    imports.append(node.module)
            elif isinstance(node, ast.Import):
                for alias in node.names:
                    mod = alias.name.split('.')[0]
                    if mod not in ('os', 'sys', 'typing', 're', 'json', 'collections', 'functools', 'itertools', 'pathlib', 'abc', 'io', 'copy', 'enum', 'dataclasses', 'contextlib', 'warnings', 'logging', 'textwrap', 'inspect', 'importlib', 'unittest', 'pytest', 'math', 'datetime', 'time', 'hashlib', 'base64', 'struct', 'string', 'operator') and not mod.startswith('_'):
                        imports.append(alias.name)
        parts = []
        if symbols:
            parts.append(", ".join(symbols[:8]))
        if imports:
            unique_imports = list(dict.fromkeys(imports))[:4]
            parts.append("imports: " + ", ".join(unique_imports))
        if parts:
            result[fpath] = " | ".join(parts)
    except Exception:
        pass
print(json.dumps(result))
"#,
        );

        if let Ok(output) = std::process::Command::new("python3")
            .args(&["-c", &script])
            .current_dir(workdir)
            .output()
        {
            if output.status.success() {
                let stdout = String::from_utf8_lossy(&output.stdout);
                if let Ok(parsed) = serde_json::from_str::<serde_json::Value>(stdout.trim()) {
                    if let Some(obj) = parsed.as_object() {
                        for (key, val) in obj {
                            if let Some(syms) = val.as_str() {
                                // Find the matching file reference
                                for &f in files {
                                    if f == key {
                                        result.insert(f, syms.to_string());
                                        break;
                                    }
                                }
                            }
                        }
                    }
                }
            }
        }

        result
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

        // Quick repo structure snapshot (top-level dirs + key files, max 2 levels)
        if let Ok(entries) = std::fs::read_dir(&self.config.workdir) {
            let mut dirs = Vec::new();
            let mut files = Vec::new();
            for entry in entries.flatten() {
                let name = entry.file_name().to_string_lossy().to_string();
                if name.starts_with('.') { continue; }
                if entry.metadata().map(|m| m.is_dir()).unwrap_or(false) {
                    // Count files in subdirectory for context
                    let count = std::fs::read_dir(entry.path())
                        .map(|e| e.count())
                        .unwrap_or(0);
                    dirs.push(format!("  {}/  ({} items)", name, count));
                } else {
                    files.push(format!("  {}", name));
                }
            }
            dirs.sort();
            files.sort();
            if !dirs.is_empty() || !files.is_empty() {
                let mut structure = String::from("Repository structure:");
                for d in dirs.iter().take(20) {
                    structure.push_str(&format!("\n{}", d));
                }
                for f in files.iter().take(15) {
                    structure.push_str(&format!("\n{}", f));
                }
                if dirs.len() > 20 || files.len() > 15 {
                    structure.push_str(&format!("\n  ... ({} dirs, {} files total)", dirs.len(), files.len()));
                }
                env_info.push(structure);
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
        
        // Route MCP tool calls through the MCP manager
        if self.mcp_manager.is_mcp_tool(tool_name) {
            return self.mcp_manager.execute_tool(tool_name, input);
        }

        // First attempt to execute the tool
        // Save pre-edit content for replace_lines/write_file auto-revert on syntax errors
        let pre_edit_content = if (tool_name == "replace_lines" || tool_name == "write_file") {
            if let Some(path_str) = input.get("path").and_then(|v| v.as_str()) {
                if path_str.ends_with(".py") {
                    let resolved = if Path::new(path_str).is_absolute() {
                        PathBuf::from(path_str)
                    } else {
                        self.config.workdir.join(path_str)
                    };
                    std::fs::read_to_string(&resolved).ok()
                } else { None }
            } else { None }
        } else { None };

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
                } else if tool_name == "replace_lines" || tool_name == "write_file" {
                    // Lint check for Python files after replace_lines/write_file
                    let path_str = input.get("path").and_then(|v| v.as_str()).unwrap_or("");
                    if path_str.ends_with(".py") {
                        let resolved = if Path::new(path_str).is_absolute() {
                            PathBuf::from(path_str)
                        } else {
                            self.config.workdir.join(path_str)
                        };
                        let lint_msg = self.lint_python_file(&resolved);
                        if !lint_msg.is_empty() {
                            if (lint_msg.contains("invalid-syntax") || lint_msg.contains("SYNTAX ERROR"))
                                && pre_edit_content.is_some()
                            {
                                let original = pre_edit_content.as_ref().unwrap();
                                let _ = std::fs::write(&resolved, original);
                                Ok(format!(
                                    "EDIT REVERTED — your {} introduced a syntax error.\n{}\n\n\
                                     The file has been restored to its previous state. \
                                     Please fix the syntax and try again.",
                                    tool_name, lint_msg
                                ))
                            } else {
                                Ok(format!("{}{}", output, lint_msg))
                            }
                        } else {
                            // Lint passed — check for signature changes on write_file/replace_lines
                            if tool_name == "write_file" || tool_name == "replace_lines" {
                                if let Some(ref old_content) = pre_edit_content {
                                    let new_content = std::fs::read_to_string(&resolved).unwrap_or_default();
                                    let sig_warning = self.check_signature_changes(old_content, &new_content);
                                    if !sig_warning.is_empty() {
                                        Ok(format!("{}{}", output, sig_warning))
                                    } else {
                                        Ok(output)
                                    }
                                } else {
                                    Ok(output)
                                }
                            } else {
                                Ok(output)
                            }
                        }
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

        let resolved_path = if Path::new(path).is_absolute() {
            PathBuf::from(path)
        } else {
            self.config.workdir.join(path)
        };

        // Read the file back to verify the edit was applied
        let read_input = serde_json::json!({
            "path": path
        });

        let mut result = match tools::execute_tool("read_file", &read_input, &self.config.workdir) {
            Ok(actual_content) => {
                if actual_content.contains(new_string.trim()) {
                    format!("{}\n\nValidation: Edit verified — new content found in file.", edit_output)
                } else {
                    let content_preview = if actual_content.len() > 500 {
                        format!("{}...", safe_truncate(&actual_content, 500))
                    } else {
                        actual_content.clone()
                    };

                    format!(
                        "{}\n\nValidation WARNING: The new content was NOT found in the file after editing. \
                         The edit may not have been applied correctly. Read the file to check:\n{}",
                        edit_output,
                        content_preview
                    )
                }
            },
            Err(_) => {
                format!("{}\n\nValidation Warning: Could not read file back to verify changes.", edit_output)
            }
        };

        // Lint check for Python files — auto-revert on syntax errors
        if path.ends_with(".py") {
            let lint_msg = self.lint_python_file(&resolved_path);
            if !lint_msg.is_empty() {
                // Check if there are syntax errors (E9 = invalid syntax in ruff, or SYNTAX ERROR from ast.parse)
                if lint_msg.contains("invalid-syntax") || lint_msg.contains("SYNTAX ERROR") {
                    // Revert by restoring the old_string content
                    if let Some(old_string) = input.get("old_string").and_then(|v| v.as_str()) {
                        if let Ok(current) = std::fs::read_to_string(&resolved_path) {
                            let reverted = current.replacen(new_string.trim(), old_string.trim(), 1);
                            if reverted != current {
                                let _ = std::fs::write(&resolved_path, &reverted);
                                return Some(format!(
                                    "EDIT REVERTED — your edit introduced a syntax error.\n{}\n\n\
                                     The file has been restored to its previous state. \
                                     Please fix the syntax in your edit and try again.",
                                    lint_msg
                                ));
                            }
                        }
                    }
                }
                result.push_str(&lint_msg);
            }
        }

        Some(result)
    }

    /// Run lint checks on a Python file after editing. Returns error message to append, or empty string.
    /// Uses ruff (fast, Rust-based linter) for syntax errors + undefined names + import errors.
    /// Falls back to ast.parse if ruff is not available.
    fn lint_python_file(&self, path: &Path) -> String {
        // Try ruff first: fast, catches more issues than ast.parse
        // E9 = syntax errors, F821 = undefined names, F401 = unused imports, F811 = redefined
        if let Ok(output) = std::process::Command::new("ruff")
            .args(&[
                "check", "--select", "E9,F821,F811",
                "--no-fix", "--output-format", "concise",
                &path.display().to_string(),
            ])
            .current_dir(&self.config.workdir)
            .output()
        {
            let stdout = String::from_utf8_lossy(&output.stdout);
            let stderr = String::from_utf8_lossy(&output.stderr);
            // ruff exits non-zero when it finds errors
            if !output.status.success() && !stdout.trim().is_empty() {
                // Limit to first 8 errors to avoid flooding
                let errors: Vec<&str> = stdout.lines().take(8).collect();
                let total = stdout.lines().count();
                let mut msg = format!("\n\nLINT ERRORS after edit ({} issues):\n{}", total, errors.join("\n"));
                if total > 8 {
                    msg.push_str(&format!("\n... and {} more", total - 8));
                }
                msg.push_str("\nFix these errors before proceeding.");
                return msg;
            }
            // ruff available and no errors — check for duplicate definitions then return
            if stderr.is_empty() || !stderr.contains("not found") {
                return self.check_duplicate_definitions(path);
            }
        }

        // Fallback: ast.parse for syntax-only check
        if let Ok(output) = std::process::Command::new("python3")
            .args(&["-c", &format!("import ast; ast.parse(open('{}').read())", path.display())])
            .current_dir(&self.config.workdir)
            .output()
        {
            if !output.status.success() {
                let stderr = String::from_utf8_lossy(&output.stderr);
                let err_lines: Vec<&str> = stderr.lines().collect();
                let err_msg = if err_lines.len() > 2 {
                    err_lines[err_lines.len()-2..].join("\n")
                } else {
                    stderr.trim().to_string()
                };
                return format!(
                    "\n\nSYNTAX ERROR after edit: {}\nFix this syntax error before proceeding.", err_msg
                );
            }
        }

        self.check_duplicate_definitions(path)
    }

    /// Check for duplicate function/class definitions at the same indentation level in a Python file.
    /// In Python, the last definition wins, making earlier definitions dead code.
    fn check_duplicate_definitions(&self, path: &Path) -> String {
        let content = match std::fs::read_to_string(path) {
            Ok(c) => c,
            Err(_) => return String::new(),
        };

        // Track (indent_level, name) -> count
        let mut defs: std::collections::HashMap<(usize, String), Vec<usize>> = std::collections::HashMap::new();

        for (line_num, line) in content.lines().enumerate() {
            let trimmed = line.trim_start();
            let indent = line.len() - trimmed.len();

            // Match "def name(" or "class name(" or "class name:"
            if let Some(rest) = trimmed.strip_prefix("def ").or_else(|| trimmed.strip_prefix("class ")) {
                if let Some(name_end) = rest.find(|c: char| c == '(' || c == ':') {
                    let name = rest[..name_end].trim().to_string();
                    if !name.is_empty() {
                        defs.entry((indent, name)).or_default().push(line_num + 1);
                    }
                }
            }
        }

        let mut warnings = Vec::new();
        for ((indent, name), lines) in &defs {
            if lines.len() > 1 {
                let last = lines[lines.len() - 1];
                let earlier: Vec<String> = lines[..lines.len()-1].iter().map(|l| l.to_string()).collect();
                warnings.push(format!(
                    "  '{}' defined {} times. Line {} is the active definition. \
                     Lines {} are DEAD CODE (shadowed) — delete them with replace_lines.",
                    name, lines.len(), last, earlier.join(", ")
                ));
            }
        }

        if warnings.is_empty() {
            return String::new();
        }

        format!(
            "\n\nACTION REQUIRED — Duplicate definitions in {}:\n{}\n\
             In Python, only the LAST definition is used. The earlier definitions are dead code \
             that must be removed. Use replace_lines to delete the shadowed definitions NOW.",
            path.file_name().unwrap_or_default().to_string_lossy(),
            warnings.join("\n")
        )
    }

    /// Compare Python function signatures between old and new file content.
    /// Returns a warning string if any signatures changed, empty string otherwise.
    fn check_signature_changes(&self, old_content: &str, new_content: &str) -> String {
        // Extract function signatures: "def name(params) -> return_type"
        fn extract_signatures(
            content: &str,
        ) -> std::collections::HashMap<String, (String, String)> {
            let mut sigs = std::collections::HashMap::new();
            for line in content.lines() {
                let trimmed = line.trim();
                if let Some(rest) = trimmed.strip_prefix("def ") {
                    if let Some(paren_start) = rest.find('(') {
                        let name = rest[..paren_start].trim().to_string();
                        if let Some(paren_end) = rest.find(')') {
                            let params = rest[paren_start..=paren_end].to_string();
                            // Extract return type annotation if present
                            let after_paren = &rest[paren_end + 1..];
                            let ret_type = if let Some(arrow) = after_paren.find("->") {
                                after_paren[arrow + 2..]
                                    .trim()
                                    .trim_end_matches(':')
                                    .trim()
                                    .to_string()
                            } else {
                                String::new()
                            };
                            sigs.entry(name).or_insert((params, ret_type));
                        }
                    }
                }
            }
            sigs
        }

        let old_sigs = extract_signatures(old_content);
        let new_sigs = extract_signatures(new_content);

        let mut changed = Vec::new();
        let mut missing = Vec::new();
        let mut ret_changed = Vec::new();
        for (name, (old_params, old_ret)) in &old_sigs {
            if name.starts_with('_') {
                continue;
            }
            if let Some((new_params, new_ret)) = new_sigs.get(name) {
                if old_params != new_params {
                    let norm_old: String =
                        old_params.split_whitespace().collect::<Vec<_>>().join(" ");
                    let norm_new: String =
                        new_params.split_whitespace().collect::<Vec<_>>().join(" ");
                    if norm_old != norm_new {
                        changed.push(format!(
                            "  CHANGED params: def {}{} → def {}{}",
                            name, old_params, name, new_params
                        ));
                    }
                }
                // Check return type changes
                if !old_ret.is_empty() && old_ret != new_ret {
                    ret_changed.push(format!(
                        "  CHANGED return: def {} -> {} → def {} -> {}",
                        name, old_ret, name, if new_ret.is_empty() { "???" } else { new_ret }
                    ));
                }
            } else {
                missing.push(format!("  MISSING: def {}{}", name, old_params));
            }
        }

        let mut warnings = Vec::new();
        warnings.extend(missing);
        warnings.extend(changed);
        warnings.extend(ret_changed);

        if warnings.is_empty() {
            return String::new();
        }

        format!(
            "\n\nNOTE: This edit changed the file's public API:\n{}\n\
             Verify this is intentional. If the task asks you to remove these functions, this is fine. \
             Otherwise, callers may break with AttributeError or TypeError — grep for the function \
             names in other files to check if anything still references them.",
            warnings.join("\n")
        )
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

        // Auto-read plan file to preserve it through compaction
        let plan_content = std::fs::read_to_string("/tmp/.ninja_plan.md")
            .unwrap_or_default();
        let plan_section = if plan_content.trim().is_empty() {
            String::new()
        } else {
            let truncated_plan = safe_truncate(plan_content.trim(), 3000);
            format!("\n\n## Your Plan (auto-recovered from /tmp/.ninja_plan.md)\n```\n{}\n```\n\
                     Review this plan and continue executing it.", truncated_plan)
        };

        let mut compacted = Vec::new();
        // Keep original prompt
        compacted.push(messages[0].clone());
        // Insert summary as a user message with git diff awareness + plan recovery
        compacted.push(Message {
            role: "user".to_string(),
            content: MessageContent::Text(format!(
                "[SYSTEM] The conversation has been compacted to save context space.\n\n{}{}{}\n\n\
                Continue working on the task. Check your todo list and complete any remaining changes.",
                summary, git_diff_info, plan_section
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
                        // Don't shrink results containing failure signals — these are critical context
                        // for avoiding error compounding in longer-running tasks
                        if content.contains("EDIT REVERTED")
                            || content.contains("LINT ERRORS")
                            || content.contains("SYNTAX ERROR")
                            || content.contains("TEST CHECKPOINT")
                            || content.contains("String not found")
                        {
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