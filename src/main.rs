mod agent;
mod tools;

use clap::Parser;
use colored::Colorize;
use std::path::{Path, PathBuf};

/// Ninja — a model-agnostic CLI coding agent
#[derive(Parser, Debug)]
#[command(name = "ninja", version, about)]
struct Cli {
    /// Prompt to send to the agent
    #[arg(short, long)]
    prompt: Option<String>,

    /// Read prompt from a file
    #[arg(long)]
    prompt_file: Option<PathBuf>,

    /// Working directory (default: current directory)
    #[arg(short = 'd', long, default_value = ".")]
    workdir: PathBuf,

    /// Model to use (default: moonshotai/Kimi-K2.5-TEE via Chutes)
    #[arg(short, long, default_value = "moonshotai/Kimi-K2.5-TEE")]
    model: String,

    /// Fast model for exploration steps (auto-routes between fast and main model)
    #[arg(long)]
    fast_model: Option<String>,

    /// Maximum iterations for the agent loop
    #[arg(long, default_value = "50")]
    max_iterations: usize,

    /// Output format: text, json, stream-json
    #[arg(long, default_value = "text")]
    output_format: String,

    /// API key (or set CHUTES_API_KEY / OPENROUTER_API_KEY env var)
    #[arg(long)]
    api_key: Option<String>,

    /// API base URL (or set CHUTES_BASE_URL / OPENROUTER_BASE_URL env var)
    #[arg(long)]
    api_base_url: Option<String>,

    /// Enable verbose output
    #[arg(short, long)]
    verbose: bool,

    /// Save rollout to file
    #[arg(long)]
    rollout: Option<PathBuf>,

    /// Extended thinking budget in tokens (Anthropic models only, min 1024). 0 = disabled.
    #[arg(long, default_value = "0")]
    thinking_budget: u64,

    /// Temperature for generation (0.0-1.0). Lower = more deterministic.
    #[arg(long)]
    temperature: Option<f64>,

    /// Interactive REPL mode (default when no prompt given)
    #[arg(short, long)]
    interactive: bool,
}

fn resolve_api_config(cli: &Cli) -> (String, String) {
    let api_key = cli
        .api_key
        .clone()
        .or_else(|| std::env::var("CHUTES_API_KEY").ok())
        .or_else(|| std::env::var("OPENROUTER_API_KEY").ok())
        .or_else(|| std::env::var("ANTHROPIC_API_KEY").ok())
        .expect("No API key found. Set CHUTES_API_KEY, OPENROUTER_API_KEY, or use --api-key");

    let api_base_url = cli
        .api_base_url
        .clone()
        .or_else(|| std::env::var("CHUTES_BASE_URL").ok())
        .or_else(|| std::env::var("OPENROUTER_BASE_URL").ok())
        .or_else(|| std::env::var("ANTHROPIC_BASE_URL").ok())
        .unwrap_or_else(|| "https://llm.chutes.ai".to_string());

    (api_key, api_base_url)
}

async fn run_oneshot(cli: &Cli, prompt: String) {
    let (api_key, api_base_url) = resolve_api_config(cli);

    let config = agent::AgentConfig {
        model: cli.model.clone(),
        fast_model: cli.fast_model.clone(),
        api_key,
        api_base_url,
        workdir: cli.workdir.clone(),
        max_iterations: cli.max_iterations,
        verbose: cli.verbose,
        streaming: true,
        thinking_budget: cli.thinking_budget,
        temperature: cli.temperature,
    };

    if cli.verbose {
        eprintln!("Ninja v{}", env!("CARGO_PKG_VERSION"));
        eprintln!("Model: {}", config.model);
        eprintln!("Workdir: {}", config.workdir.display());
        eprintln!("Max iterations: {}", config.max_iterations);
    }

    let mut runner = agent::AgentRunner::new(config);
    let rollout = runner.run(&prompt).await;

    // Output
    match cli.output_format.as_str() {
        "json" => {
            println!("{}", serde_json::to_string_pretty(&rollout).unwrap());
        }
        "stream-json" => {
            for entry in &rollout.entries {
                println!("{}", serde_json::to_string(entry).unwrap());
            }
        }
        _ => {
            if let Some(ref result) = rollout.final_result {
                println!("{}", result);
            }
        }
    }

    // Save rollout if requested
    if let Some(ref path) = cli.rollout {
        let data = serde_json::to_string_pretty(&rollout).unwrap();
        std::fs::write(path, data).expect("Failed to write rollout");
        if cli.verbose {
            eprintln!("Rollout saved to {}", path.display());
        }
    }

    std::process::exit(if rollout.success { 0 } else { 1 });
}

async fn run_interactive(cli: &Cli) {
    let (api_key, api_base_url) = resolve_api_config(cli);

    println!("{}", "Ninja — Interactive Mode".bold().cyan());
    println!(
        "Model: {} | Workdir: {}",
        cli.model.green(),
        cli.workdir.display().to_string().green()
    );
    println!(
        "Type your task and press Enter. Type {} to quit.\n",
        "/exit".yellow()
    );

    let mut rl = rustyline::DefaultEditor::new().expect("Failed to initialize readline");

    // Create a persistent runner for multi-turn conversation
    let config = agent::AgentConfig {
        model: cli.model.clone(),
        fast_model: cli.fast_model.clone(),
        api_key: api_key.clone(),
        api_base_url: api_base_url.clone(),
        workdir: cli.workdir.clone(),
        max_iterations: cli.max_iterations,
        verbose: cli.verbose,
        streaming: true,
        thinking_budget: cli.thinking_budget,
        temperature: cli.temperature,
    };
    let mut runner = agent::AgentRunner::new(config);

    loop {
        let readline = rl.readline(&format!("{} ", "ninja>".bold().cyan()));

        match readline {
            Ok(line) => {
                let line = line.trim().to_string();
                if line.is_empty() {
                    continue;
                }
                if line == "/exit" || line == "/quit" || line == "exit" || line == "quit" {
                    println!("{}", "Goodbye!".dimmed());
                    break;
                }
                if line == "/help" {
                    println!("  {}     — Exit interactive mode", "/exit".yellow());
                    println!("  {}     — Show this help", "/help".yellow());
                    println!("  {}    — Start fresh conversation", "/clear".yellow());
                    println!("  {}  — Compact conversation history", "/compact".yellow());
                    println!(
                        "  {}   — Change working directory",
                        "/cd <path>".yellow()
                    );
                    println!(
                        "  {} — Switch model",
                        "/model <name>".yellow()
                    );
                    println!();
                    continue;
                }
                if line == "/compact" {
                    let (before, after) = runner.compact();
                    println!(
                        "  Compacted: {} → {} messages",
                        before, after
                    );
                    continue;
                }
                if line.starts_with("/model ") {
                    let model = line.trim_start_matches("/model ").trim();
                    runner.set_model(model);
                    println!("  Model → {}", model.green());
                    continue;
                }
                if line == "/clear" {
                    let new_config = agent::AgentConfig {
                        model: cli.model.clone(),
                        fast_model: cli.fast_model.clone(),
                        api_key: api_key.clone(),
                        api_base_url: api_base_url.clone(),
                        workdir: cli.workdir.clone(),
                        max_iterations: cli.max_iterations,
                        verbose: cli.verbose,
                        streaming: true,
                        thinking_budget: cli.thinking_budget,
                        temperature: cli.temperature,
                    };
                    runner = agent::AgentRunner::new(new_config);
                    println!("{}", "Conversation cleared.".dimmed());
                    continue;
                }
                if line.starts_with("/cd ") {
                    let path = line.trim_start_matches("/cd ").trim();
                    let new_path = if Path::new(path).is_absolute() {
                        PathBuf::from(path)
                    } else {
                        std::env::current_dir().unwrap_or_default().join(path)
                    };
                    let new_path = new_path.canonicalize().unwrap_or(new_path);
                    if new_path.exists() && new_path.is_dir() {
                        runner.set_workdir(new_path.clone());
                        println!("  Workdir → {}", new_path.display().to_string().green());
                    } else {
                        println!("  {} Directory not found: {}", "Error:".red(), path);
                    }
                    continue;
                }

                let _ = rl.add_history_entry(&line);

                eprintln!();

                let rollout = runner.run_turn(&line).await;

                if let Some(ref result) = rollout.final_result {
                    println!("\n{}", result);
                }

                // Print stats
                let stats = format!(
                    "[{} iterations | {}in/{}out tokens | ${:.4} | {:.1}s]",
                    rollout.iteration_count,
                    rollout.total_input_tokens,
                    rollout.total_output_tokens,
                    rollout.estimated_cost_usd,
                    rollout.total_duration_ms as f64 / 1000.0,
                );
                println!("\n{}\n", stats.dimmed());

                // Save rollout if configured
                if let Some(ref path) = cli.rollout {
                    let data = serde_json::to_string_pretty(&rollout).unwrap();
                    std::fs::write(path, data).expect("Failed to write rollout");
                    println!("  Rollout saved to {}", path.display());
                }
            }
            Err(rustyline::error::ReadlineError::Interrupted) => {
                println!("{}", "\nInterrupted. Type /exit to quit.".dimmed());
            }
            Err(rustyline::error::ReadlineError::Eof) => {
                println!("{}", "\nGoodbye!".dimmed());
                break;
            }
            Err(err) => {
                eprintln!("Error: {:?}", err);
                break;
            }
        }
    }
}

#[tokio::main]
async fn main() {
    let cli = Cli::parse();

    // Determine mode: interactive or oneshot
    let has_prompt = cli.prompt.is_some() || cli.prompt_file.is_some();

    if cli.interactive || !has_prompt {
        // Interactive REPL mode
        if !has_prompt {
            run_interactive(&cli).await;
        } else {
            // --interactive with --prompt: run the prompt then enter REPL
            let prompt = if let Some(ref p) = cli.prompt {
                p.clone()
            } else {
                std::fs::read_to_string(cli.prompt_file.as_ref().unwrap())
                    .expect("Failed to read prompt file")
            };
            // Run the initial prompt first
            let (api_key, api_base_url) = resolve_api_config(&cli);
            let config = agent::AgentConfig {
                model: cli.model.clone(),
                fast_model: cli.fast_model.clone(),
                api_key,
                api_base_url,
                workdir: cli.workdir.clone(),
                max_iterations: cli.max_iterations,
                verbose: cli.verbose,
                streaming: true,
                thinking_budget: cli.thinking_budget,
                temperature: cli.temperature,
            };
            let mut runner = agent::AgentRunner::new(config);
            let rollout = runner.run(&prompt).await;
            if let Some(ref result) = rollout.final_result {
                println!("{}", result);
            }
            // Then enter REPL
            run_interactive(&cli).await;
        }
    } else {
        // One-shot mode
        let prompt = if let Some(ref p) = cli.prompt {
            p.clone()
        } else {
            std::fs::read_to_string(cli.prompt_file.as_ref().unwrap())
                .expect("Failed to read prompt file")
        };
        run_oneshot(&cli, prompt).await;
    }
}
