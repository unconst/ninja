use serde_json::{json, Value};
use std::path::Path;

use crate::agent::api_client::ToolDef;

pub fn definitions() -> Vec<ToolDef> {
    vec![ToolDef {
        name: "web_fetch".to_string(),
        description: "Fetch content from a URL and return it as text. Useful for reading \
                       documentation, GitHub issues/PRs, Stack Overflow answers, and API docs. \
                       HTML is converted to readable text."
            .to_string(),
        input_schema: json!({
            "type": "object",
            "properties": {
                "url": {
                    "type": "string",
                    "description": "The URL to fetch content from"
                },
                "max_length": {
                    "type": "integer",
                    "description": "Maximum characters to return (default: 10000)"
                }
            },
            "required": ["url"]
        }),
    }]
}

pub fn web_fetch(args: &Value, _workdir: &Path) -> Result<String, String> {
    let url = args["url"]
        .as_str()
        .ok_or("Missing 'url' argument")?;
    let max_length = args["max_length"].as_u64().unwrap_or(10000) as usize;

    // Use curl for the actual fetch (universally available)
    let output = std::process::Command::new("curl")
        .arg("-sL") // silent, follow redirects
        .arg("--max-time")
        .arg("15") // 15 second timeout
        .arg("--max-filesize")
        .arg("1048576") // 1MB max
        .arg("-H")
        .arg("User-Agent: Mozilla/5.0 (compatible; NinjaBot/1.0)")
        .arg(url)
        .output()
        .map_err(|e| format!("Failed to run curl: {}", e))?;

    if !output.status.success() {
        let stderr = String::from_utf8_lossy(&output.stderr);
        return Err(format!("Failed to fetch URL: {}", stderr.trim()));
    }

    let body = String::from_utf8_lossy(&output.stdout).to_string();

    if body.is_empty() {
        return Ok("Empty response from URL.".to_string());
    }

    // Convert HTML to readable text
    let text = html_to_text(&body);

    // Truncate if needed
    if text.len() > max_length {
        let mut truncated = text[..max_length].to_string();
        truncated.push_str(&format!("\n\n... (truncated, {} total chars)", text.len()));
        Ok(truncated)
    } else {
        Ok(text)
    }
}

/// Convert HTML to readable plain text by stripping tags and decoding entities.
fn html_to_text(html: &str) -> String {
    let mut result = String::with_capacity(html.len());
    let mut in_tag = false;
    let mut in_script = false;
    let mut in_style = false;
    let mut last_was_whitespace = false;
    let mut tag_name = String::new();
    let mut collecting_tag_name = false;

    let chars: Vec<char> = html.chars().collect();
    let mut i = 0;

    while i < chars.len() {
        let ch = chars[i];

        if ch == '<' {
            in_tag = true;
            tag_name.clear();
            collecting_tag_name = true;
            i += 1;
            continue;
        }

        if ch == '>' && in_tag {
            in_tag = false;
            let lower = tag_name.to_lowercase();
            if lower == "script" {
                in_script = true;
            } else if lower == "/script" {
                in_script = false;
            } else if lower == "style" {
                in_style = true;
            } else if lower == "/style" {
                in_style = false;
            }

            // Add line breaks for block elements
            let block_tags = [
                "br", "br/", "p", "/p", "div", "/div", "h1", "/h1", "h2", "/h2",
                "h3", "/h3", "h4", "/h4", "h5", "/h5", "h6", "/h6", "li", "tr",
                "/tr", "hr", "hr/", "/ul", "/ol", "/table", "/pre",
            ];
            if block_tags.iter().any(|t| lower == *t) {
                if !result.ends_with('\n') {
                    result.push('\n');
                }
                last_was_whitespace = true;
            }

            collecting_tag_name = false;
            i += 1;
            continue;
        }

        if in_tag {
            if collecting_tag_name {
                if ch.is_whitespace() || ch == '/' && tag_name.is_empty() {
                    if !tag_name.is_empty() {
                        collecting_tag_name = false;
                    } else if ch == '/' {
                        tag_name.push(ch);
                    }
                } else {
                    tag_name.push(ch);
                }
            }
            i += 1;
            continue;
        }

        if in_script || in_style {
            i += 1;
            continue;
        }

        // Handle HTML entities
        if ch == '&' {
            let mut entity = String::new();
            let mut j = i + 1;
            while j < chars.len() && j - i < 10 && chars[j] != ';' {
                entity.push(chars[j]);
                j += 1;
            }
            if j < chars.len() && chars[j] == ';' {
                let decoded = match entity.as_str() {
                    "amp" => "&",
                    "lt" => "<",
                    "gt" => ">",
                    "quot" => "\"",
                    "apos" => "'",
                    "nbsp" => " ",
                    "#39" => "'",
                    "#x27" => "'",
                    "#34" => "\"",
                    _ => {
                        // Skip unknown entities
                        i = j + 1;
                        continue;
                    }
                };
                result.push_str(decoded);
                last_was_whitespace = false;
                i = j + 1;
                continue;
            }
        }

        // Collapse whitespace
        if ch.is_whitespace() {
            if !last_was_whitespace {
                result.push(if ch == '\n' { '\n' } else { ' ' });
                last_was_whitespace = true;
            }
        } else {
            result.push(ch);
            last_was_whitespace = false;
        }

        i += 1;
    }

    // Clean up: collapse multiple blank lines
    let mut cleaned = String::new();
    let mut blank_count = 0;
    for line in result.lines() {
        if line.trim().is_empty() {
            blank_count += 1;
            if blank_count <= 2 {
                cleaned.push('\n');
            }
        } else {
            blank_count = 0;
            cleaned.push_str(line.trim());
            cleaned.push('\n');
        }
    }

    cleaned.trim().to_string()
}
