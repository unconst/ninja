use std::path::PathBuf;
use std::time::Instant;

use super::api_client::{ApiClient, ContentBlock, Message, MessageContent};
use super::rollout::Rollout;
use crate::tools;

/// Threshold in estimated tokens before triggering conversation compaction.
/// Claude's context is ~200K tokens; compact at ~100K to leave room.
const COMPACTION_TOKEN_THRESHOLD: u64 = 100_000;

/// Configuration for the agent runner.
pub struct AgentConfig {
    pub model: String,
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
}

impl AgentRunner {
    pub fn new(config: AgentConfig) -> Self {
        let client = ApiClient::new(&config.api_key, &config.api_base_url, &config.model);
        Self {
            config,
            client,
            conversation: Vec::new(),
            system_prompt: None,
        }
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

        rollout.log_user(prompt);

        let mut cumulative_input_tokens: u64 = 0;

        for iteration in 0..self.config.max_iterations {
            rollout.iteration_count = (iteration + 1) as u64;

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
            } else if remaining == 3 {
                self.conversation.push(Message {
                    role: "user".to_string(),
                    content: MessageContent::Text(
                        "[SYSTEM] Only 3 iterations left! Wrap up immediately.".to_string()
                    ),
                });
            }

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
                eprintln!("  assistant: {}", &response.text[..response.text.len().min(200)]);
            }

            // Compact if needed
            if cumulative_input_tokens > COMPACTION_TOKEN_THRESHOLD && self.conversation.len() > 6 {
                self.conversation = self.compact_messages(&self.conversation);
            }

            if response.tool_calls.is_empty() {
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

            // Execute tools
            let mut result_blocks = Vec::new();
            for tc in &response.tool_calls {
                rollout.log_tool_call(&tc.name, &tc.input.to_string());
                let tool_start = Instant::now();
                let result = self.execute_tool_with_recovery(&tc.name, &tc.input);
                let tool_duration = tool_start.elapsed();
                let (output, is_error) = match result {
                    Ok(o) => (o, false),
                    Err(e) => (e, true),
                };
                rollout.log_tool_result(&tc.name, &output, tool_duration);
                let truncated = if output.len() > 15000 {
                    let mut t = output[..15000].to_string();
                    t.push_str(&format!("\n\n... (truncated, {} total chars)", output.len()));
                    t
                } else { output };
                result_blocks.push(ContentBlock::ToolResult {
                    tool_use_id: tc.id.clone(),
                    content: truncated,
                    is_error: if is_error { Some(true) } else { None },
                });
            }
            self.conversation.push(Message {
                role: "user".to_string(),
                content: MessageContent::Blocks(result_blocks),
            });
        }

        rollout.total_duration_ms = start.elapsed().as_millis() as u64;
        rollout
    }

    pub async fn run(&mut self, prompt: &str) -> Rollout {
        let start = Instant::now();
        let mut rollout = Rollout::new(&self.config.model);
        let tool_defs = tools::get_tool_definitions();

        let env_info = self.validate_initial_environment();
        let system = self.build_system_prompt(&env_info);

        let mut messages: Vec<Message> = vec![Message {
            role: "user".to_string(),
            content: MessageContent::Text(prompt.to_string()),
        }];

        rollout.log_user(prompt);

        let mut cumulative_input_tokens: u64 = 0;

        for iteration in 0..self.config.max_iterations {
            rollout.iteration_count = (iteration + 1) as u64;

            if self.config.verbose {
                eprintln!("[iteration {}]", iteration + 1);
            }

            // Inject urgency reminder when nearing iteration limit
            let remaining = self.config.max_iterations - iteration;
            if remaining == 10 {
                messages.push(Message {
                    role: "user".to_string(),
                    content: MessageContent::Text(
                        "[SYSTEM] You have 10 iterations remaining. Review your deliverables checklist — \
                         make sure all required files have been modified/created. Focus on completing \
                         any remaining changes now. Don't waste iterations on testing if dependencies \
                         are missing.".to_string()
                    ),
                });
            } else if remaining == 3 {
                messages.push(Message {
                    role: "user".to_string(),
                    content: MessageContent::Text(
                        "[SYSTEM] Only 3 iterations left! Wrap up immediately. If any files from your \
                         plan are still unmodified, make those changes now. Summarize what you've done.".to_string()
                    ),
                });
            }

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
                    eprintln!("  assistant: {}", &response.text[..response.text.len().min(200)]);
                }
                eprintln!(
                    "  tokens: in={} out={} tool_calls={} cumulative_in={}",
                    response.input_tokens,
                    response.output_tokens,
                    response.tool_calls.len(),
                    cumulative_input_tokens,
                );
            }

            // Compact conversation history if approaching context limits
            if cumulative_input_tokens > COMPACTION_TOKEN_THRESHOLD && messages.len() > 6 {
                if self.config.verbose {
                    eprintln!("  [compacting conversation: {} tokens, {} messages]", cumulative_input_tokens, messages.len());
                }
                messages = self.compact_messages(&messages);
                rollout.log_error(&format!(
                    "Conversation compacted at {} tokens, {} messages remaining",
                    cumulative_input_tokens, messages.len()
                ));
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

            // Execute tool calls with error handling and recovery
            let mut result_blocks = Vec::new();
            for tc in &response.tool_calls {
                if self.config.verbose {
                    eprintln!("  tool: {}({})", tc.name, &tc.input.to_string()[..tc.input.to_string().len().min(100)]);
                }

                rollout.log_tool_call(&tc.name, &tc.input.to_string());

                let tool_start = Instant::now();
                let result = self.execute_tool_with_recovery(&tc.name, &tc.input);
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

                // Truncate very long tool outputs to manage context window
                let truncated_output = if output.len() > 15000 {
                    let mut t = output[..15000].to_string();
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

            messages.push(Message {
                role: "user".to_string(),
                content: MessageContent::Blocks(result_blocks),
            });
        }

        rollout.total_duration_ms = start.elapsed().as_millis() as u64;
        rollout
    }

    /// Build the system prompt for the agent.
    fn build_system_prompt(&self, env_info: &str) -> String {
        format!(
            "You are Ninja, a powerful autonomous coding agent. You solve software engineering tasks \
             by reading, understanding, and modifying code.\n\n\
             Working directory: {}\n\
             {}\n\n\
             ## Available Tools\n\
             - read_file: Read file contents (supports offset/limit for large files)\n\
             - write_file: Create or overwrite files\n\
             - edit_file: Replace exact string matches in files. The old_string MUST be unique \
               — include surrounding context lines if needed. Set replace_all=true to replace all occurrences.\n\
             - list_dir: List directory contents\n\
             - shell_exec: Run shell commands (bash)\n\
             - glob_search: Find files by name pattern\n\
             - grep_search: Search file contents with regex\n\n\
             ## Strategy\n\
             1. EXPLORE FIRST: Before making any changes, use grep_search and read_file to understand \
                the codebase structure and the specific files involved.\n\
             2. ENUMERATE ALL DELIVERABLES: Before editing anything, write out the COMPLETE list of files \
                that need changes. Include:\n\
                - Source code files (the actual bug fix / feature)\n\
                - Documentation files (changelogs, what's-new, rst/md docs)\n\
                - Configuration files if affected\n\
                Look at the hints and test patch for clues about ALL required files.\n\
             3. EDIT CAREFULLY: Always read a file before editing it. For edit_file, include enough \
                surrounding context in old_string to make it unique. If you get a 'found N times' error, \
                look at the context shown and include more surrounding lines.\n\
             4. VERIFY: After making changes, read the file back to confirm your edits applied correctly.\n\
             5. COMPLETE ALL CHANGES: Work through your deliverables list systematically. Don't stop \
                after modifying one file. After finishing all changes, review your list and confirm \
                every file has been addressed.\n\
             6. FINAL CHECKLIST: Before declaring done, verify:\n\
                - All files from your deliverables list have been modified/created\n\
                - Each edit was applied correctly (read back the file)\n\
                - You haven't missed any documentation or changelog files\n\n\
             ## Rules\n\
             - Be precise and minimal in changes — don't over-engineer\n\
             - When editing, prefer small targeted edits over rewriting entire files\n\
             - If a test patch is provided, apply it first, then make source changes to pass the tests\n\
             - If you can't run tests due to missing dependencies, don't waste iterations retrying. \
               Proceed with confidence based on code analysis.\n\
             - When done, list every file you changed and briefly summarize each change",
            self.config.workdir.display(),
            env_info
        )
    }

    /// Validate the initial environment and gather context information
    fn validate_initial_environment(&self) -> String {
        let mut env_info = Vec::new();
        
        // Check if we're in a git repository
        if let Ok(output) = std::process::Command::new("git")
            .args(&["rev-parse", "--is-inside-work-tree"])
            .current_dir(&self.config.workdir)
            .output()
        {
            if output.status.success() {
                // We're in a git repository, get more info
                if let Ok(remote_output) = std::process::Command::new("git")
                    .args(&["remote", "-v"])
                    .current_dir(&self.config.workdir)
                    .output()
                {
                    if let Ok(remote_info) = String::from_utf8(remote_output.stdout) {
                        if !remote_info.trim().is_empty() {
                            env_info.push(format!("Git repository detected with remotes:\n{}", remote_info.trim()));
                        } else {
                            env_info.push("Git repository detected (no remotes configured)".to_string());
                        }
                    }
                }
                
                // Get current branch
                if let Ok(branch_output) = std::process::Command::new("git")
                    .args(&["branch", "--show-current"])
                    .current_dir(&self.config.workdir)
                    .output()
                {
                    if let Ok(branch_name) = String::from_utf8(branch_output.stdout) {
                        let branch_name = branch_name.trim();
                        if !branch_name.is_empty() {
                            env_info.push(format!("Current branch: {}", branch_name));
                        }
                    }
                }
                
                // Check git status
                if let Ok(status_output) = std::process::Command::new("git")
                    .args(&["status", "--porcelain"])
                    .current_dir(&self.config.workdir)
                    .output()
                {
                    if let Ok(status_info) = String::from_utf8(status_output.stdout) {
                        if status_info.trim().is_empty() {
                            env_info.push("Working directory is clean".to_string());
                        } else {
                            let modified_files = status_info.lines().count();
                            env_info.push(format!("Working directory has {} modified/untracked files", modified_files));
                        }
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
        if tool_name == "shell" {
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
        let expected_content = input.get("content")?.as_str()?;
        
        // Only validate if the edit operation reported success
        if !edit_output.contains("successfully") && !edit_output.contains("written") {
            return None;
        }
        
        // Read the file back to verify the content
        let read_input = serde_json::json!({
            "path": path
        });
        
        match tools::execute_tool("read_file", &read_input, &self.config.workdir) {
            Ok(actual_content) => {
                // Check if the content matches what we expected
                if actual_content.trim() == expected_content.trim() {
                    // Content matches - edit was successful
                    Some(format!("{}\n\nValidation: File content verified successfully.", edit_output))
                } else {
                    // Content doesn't match - there might be an issue
                    let content_preview = if actual_content.len() > 500 {
                        format!("{}...", &actual_content[..500])
                    } else {
                        actual_content.clone()
                    };
                    
                    Some(format!(
                        "{}\n\nValidation Warning: File content differs from expected. Actual content:\n{}",
                        edit_output,
                        content_preview
                    ))
                }
            },
            Err(_) => {
                // Could not read the file back for validation
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
            "shell" => self.recover_shell_error(input, error),
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
                        let preview = if text.len() > 200 { &text[..200] } else { text.as_str() };
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
                                    format!("{}...", &args_preview[..100])
                                } else {
                                    args_preview
                                };
                                summary_parts.push(format!("- Used tool `{}`: {}", name, args_short));
                            }
                            ContentBlock::ToolResult { content, is_error, .. } => {
                                let status = if *is_error == Some(true) { "ERROR" } else { "OK" };
                                let preview = if content.len() > 150 { &content[..150] } else { content.as_str() };
                                summary_parts.push(format!("  Result ({}): {}", status, preview));
                            }
                            ContentBlock::Text { text } => {
                                let preview = if text.len() > 200 { &text[..200] } else { text.as_str() };
                                summary_parts.push(format!("- {}", preview));
                            }
                        }
                    }
                }
            }
        }

        let summary = summary_parts.join("\n");

        let mut compacted = Vec::new();
        // Keep original prompt
        compacted.push(messages[0].clone());
        // Insert summary as a user message
        compacted.push(Message {
            role: "user".to_string(),
            content: MessageContent::Text(format!(
                "[SYSTEM] The conversation has been compacted to save context space.\n\n{}\n\n\
                Continue working on the task. Review your deliverables checklist and complete any remaining changes.",
                summary
            )),
        });
        // Keep the recent messages (last 4)
        for msg in &messages[messages.len().saturating_sub(4)..] {
            compacted.push(msg.clone());
        }

        compacted
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