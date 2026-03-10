use serde_json::{json, Value};
use std::path::Path;
use std::process::Command;

use crate::agent::api_client::ToolDef;

pub fn definitions() -> Vec<ToolDef> {
    vec![
        ToolDef {
            name: "find_definition".to_string(),
            description: "Find where a symbol (function, class, method, variable) is defined. \
                           Searches for definition patterns across common languages (Python, Rust, \
                           JavaScript, TypeScript, Go, Java, C/C++)."
                .to_string(),
            input_schema: json!({
                "type": "object",
                "properties": {
                    "symbol": {
                        "type": "string",
                        "description": "The symbol name to find the definition of"
                    },
                    "path": {
                        "type": "string",
                        "description": "Directory to search in (default: working directory)"
                    },
                    "language": {
                        "type": "string",
                        "description": "Language hint: python, rust, javascript, typescript, go, java, c, cpp (auto-detected if omitted)"
                    }
                },
                "required": ["symbol"]
            }),
        },
        ToolDef {
            name: "find_references".to_string(),
            description: "Find all references to a symbol across the codebase. Returns file paths \
                           and line numbers where the symbol is used."
                .to_string(),
            input_schema: json!({
                "type": "object",
                "properties": {
                    "symbol": {
                        "type": "string",
                        "description": "The symbol name to find references of"
                    },
                    "path": {
                        "type": "string",
                        "description": "Directory to search in (default: working directory)"
                    }
                },
                "required": ["symbol"]
            }),
        },
    ]
}

/// Build regex patterns that match definition sites for a symbol in various languages.
fn definition_patterns(symbol: &str) -> Vec<String> {
    let s = regex_escape(symbol);
    vec![
        // Python
        format!(r"(def|class)\s+{}\b", s),
        // Rust
        format!(r"(fn|struct|enum|trait|type|const|static|mod)\s+{}\b", s),
        // JavaScript / TypeScript
        format!(r"(function|class|const|let|var|type|interface|enum)\s+{}\b", s),
        format!(r"{}\s*[:=]\s*(function|\(|async)", s), // foo = function, foo: (
        // Go
        format!(r"func\s+(\([^)]*\)\s+)?{}\b", s), // func (r Receiver) Symbol
        format!(r"type\s+{}\b", s),
        // Java / C / C++
        format!(r"(class|interface|enum)\s+{}\b", s),
        // Assignment-style (covers many languages)
        format!(r"^\s*{}\s*=\s*", s),
    ]
}

fn regex_escape(s: &str) -> String {
    let mut escaped = String::with_capacity(s.len() * 2);
    for c in s.chars() {
        if "\\^$.|?*+()[]{}".contains(c) {
            escaped.push('\\');
        }
        escaped.push(c);
    }
    escaped
}

pub fn find_definition(args: &Value, workdir: &Path) -> Result<String, String> {
    let symbol = args["symbol"]
        .as_str()
        .ok_or("Missing 'symbol' argument")?;

    let search_dir = args["path"]
        .as_str()
        .map(|p| {
            let path = Path::new(p);
            if path.is_absolute() { path.to_path_buf() } else { workdir.join(path) }
        })
        .unwrap_or_else(|| workdir.to_path_buf());

    // Build a combined regex pattern
    let patterns = definition_patterns(symbol);
    let combined = patterns.join("|");

    let output = Command::new("grep")
        .arg("-rnE")
        .arg("--color=never")
        .arg(&combined)
        .arg(&search_dir)
        .arg("--exclude-dir=.git")
        .arg("--exclude-dir=target")
        .arg("--exclude-dir=node_modules")
        .arg("--exclude-dir=__pycache__")
        .arg("--exclude-dir=.venv")
        .arg("--exclude-dir=venv")
        .arg("--include=*.py")
        .arg("--include=*.rs")
        .arg("--include=*.js")
        .arg("--include=*.ts")
        .arg("--include=*.tsx")
        .arg("--include=*.jsx")
        .arg("--include=*.go")
        .arg("--include=*.java")
        .arg("--include=*.c")
        .arg("--include=*.h")
        .arg("--include=*.cpp")
        .arg("--include=*.hpp")
        .output()
        .map_err(|e| format!("Failed to run grep: {}", e))?;

    let result = String::from_utf8_lossy(&output.stdout).to_string();

    if result.trim().is_empty() {
        Ok(format!("No definition found for '{}'.", symbol))
    } else {
        // Sort by relevance: exact definition patterns first
        let mut lines: Vec<&str> = result.lines().collect();
        lines.truncate(50);
        Ok(lines.join("\n"))
    }
}

pub fn find_references(args: &Value, workdir: &Path) -> Result<String, String> {
    let symbol = args["symbol"]
        .as_str()
        .ok_or("Missing 'symbol' argument")?;

    let search_dir = args["path"]
        .as_str()
        .map(|p| {
            let path = Path::new(p);
            if path.is_absolute() { path.to_path_buf() } else { workdir.join(path) }
        })
        .unwrap_or_else(|| workdir.to_path_buf());

    // Search for the symbol as a whole word
    let pattern = format!(r"\b{}\b", regex_escape(symbol));

    let output = Command::new("grep")
        .arg("-rnE")
        .arg("--color=never")
        .arg(&pattern)
        .arg(&search_dir)
        .arg("--exclude-dir=.git")
        .arg("--exclude-dir=target")
        .arg("--exclude-dir=node_modules")
        .arg("--exclude-dir=__pycache__")
        .arg("--exclude-dir=.venv")
        .arg("--exclude-dir=venv")
        .output()
        .map_err(|e| format!("Failed to run grep: {}", e))?;

    let result = String::from_utf8_lossy(&output.stdout).to_string();

    if result.trim().is_empty() {
        Ok(format!("No references found for '{}'.", symbol))
    } else {
        let lines: Vec<&str> = result.lines().collect();
        let total = lines.len();
        let display: Vec<&str> = lines.into_iter().take(100).collect();
        let mut output = display.join("\n");
        if total > 100 {
            output.push_str(&format!("\n\n... ({} total references, showing first 100)", total));
        }
        Ok(output)
    }
}
