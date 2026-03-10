mod agent;
mod tools;

use clap::Parser;
use std::path::PathBuf;

/// Ninja — a CLI coding agent powered by Claude
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

    /// Model to use (default: anthropic/claude-sonnet-4)
    #[arg(short, long, default_value = "anthropic/claude-sonnet-4")]
    model: String,

    /// Maximum iterations for the agent loop
    #[arg(long, default_value = "50")]
    max_iterations: usize,

    /// Output format: text, json, stream-json
    #[arg(long, default_value = "text")]
    output_format: String,

    /// API key (or set ANTHROPIC_API_KEY env var)
    #[arg(long)]
    api_key: Option<String>,

    /// API base URL (or set ANTHROPIC_BASE_URL env var)
    #[arg(long)]
    api_base_url: Option<String>,

    /// Enable verbose output
    #[arg(short, long)]
    verbose: bool,

    /// Save rollout to file
    #[arg(long)]
    rollout: Option<PathBuf>,
}

#[tokio::main]
async fn main() {
    let cli = Cli::parse();

    // Resolve prompt
    let prompt = if let Some(ref p) = cli.prompt {
        p.clone()
    } else if let Some(ref path) = cli.prompt_file {
        std::fs::read_to_string(path).expect("Failed to read prompt file")
    } else {
        eprintln!("Error: provide --prompt or --prompt-file");
        std::process::exit(1);
    };

    // Resolve API key
    let api_key = cli
        .api_key
        .clone()
        .or_else(|| std::env::var("ANTHROPIC_API_KEY").ok())
        .or_else(|| std::env::var("OPENROUTER_API_KEY").ok())
        .expect("No API key found. Set ANTHROPIC_API_KEY or use --api-key");

    let api_base_url = cli
        .api_base_url
        .clone()
        .or_else(|| std::env::var("ANTHROPIC_BASE_URL").ok())
        .unwrap_or_else(|| "https://openrouter.ai/api".to_string());

    let config = agent::AgentConfig {
        model: cli.model.clone(),
        api_key,
        api_base_url,
        workdir: cli.workdir.clone(),
        max_iterations: cli.max_iterations,
        verbose: cli.verbose,
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
            // text output
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
