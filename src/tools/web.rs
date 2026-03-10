use serde_json::{json, Value};
use std::path::Path;

use crate::agent::api_client::ToolDef;

pub fn definitions() -> Vec<ToolDef> {
    vec![
        ToolDef {
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
        },
        ToolDef {
            name: "web_search".to_string(),
            description: "Search the web using DuckDuckGo and return results. Use this to find \
                           up-to-date information, documentation, or answers to questions."
                .to_string(),
            input_schema: json!({
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "The search query"
                    },
                    "max_results": {
                        "type": "integer",
                        "description": "Maximum number of results to return (default: 8)"
                    }
                },
                "required": ["query"]
            }),
        },
    ]
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

pub fn web_search(args: &Value, _workdir: &Path) -> Result<String, String> {
    let query = args["query"]
        .as_str()
        .ok_or("Missing 'query' argument")?;
    let max_results = args["max_results"].as_u64().unwrap_or(8) as usize;

    // Use DuckDuckGo HTML search (no API key needed)
    let encoded_query = query
        .replace(' ', "+")
        .replace('&', "%26")
        .replace('=', "%3D");
    let url = format!("https://html.duckduckgo.com/html/?q={}", encoded_query);

    let output = std::process::Command::new("curl")
        .arg("-sL")
        .arg("--max-time")
        .arg("10")
        .arg("-H")
        .arg("User-Agent: Mozilla/5.0 (compatible; NinjaBot/1.0)")
        .arg(&url)
        .output()
        .map_err(|e| format!("Failed to run curl: {}", e))?;

    if !output.status.success() {
        let stderr = String::from_utf8_lossy(&output.stderr);
        return Err(format!("Search failed: {}", stderr.trim()));
    }

    let body = String::from_utf8_lossy(&output.stdout).to_string();

    if body.is_empty() {
        return Ok("No search results found.".to_string());
    }

    // Parse DuckDuckGo HTML results
    let results = parse_ddg_results(&body, max_results);

    if results.is_empty() {
        Ok("No search results found.".to_string())
    } else {
        Ok(results.join("\n\n"))
    }
}

/// Parse DuckDuckGo HTML search results.
fn parse_ddg_results(html: &str, max_results: usize) -> Vec<String> {
    let mut results = Vec::new();

    // DuckDuckGo HTML results are in <a class="result__a" href="...">title</a>
    // followed by <a class="result__snippet">snippet</a>
    let mut pos = 0;
    while results.len() < max_results {
        // Find result link
        let link_marker = "class=\"result__a\"";
        let link_pos = match html[pos..].find(link_marker) {
            Some(p) => pos + p,
            None => break,
        };

        // Extract href
        let href_start = match html[..link_pos].rfind("href=\"") {
            Some(p) => p + 6,
            None => { pos = link_pos + link_marker.len(); continue; }
        };
        let href_end = match html[href_start..link_pos].find('"') {
            Some(p) => href_start + p,
            None => { pos = link_pos + link_marker.len(); continue; }
        };
        let href = &html[href_start..href_end];

        // Extract title (text between > and </a>)
        let title_start = match html[link_pos..].find('>') {
            Some(p) => link_pos + p + 1,
            None => { pos = link_pos + link_marker.len(); continue; }
        };
        let title_end = match html[title_start..].find("</a>") {
            Some(p) => title_start + p,
            None => { pos = link_pos + link_marker.len(); continue; }
        };
        let title = html_to_text(&html[title_start..title_end]);

        // Extract snippet
        let snippet_marker = "class=\"result__snippet\"";
        let snippet_text = if let Some(sp) = html[title_end..].find(snippet_marker) {
            let snippet_pos = title_end + sp;
            let snippet_start = match html[snippet_pos..].find('>') {
                Some(p) => snippet_pos + p + 1,
                None => snippet_pos,
            };
            let snippet_end = match html[snippet_start..].find("</a>") {
                Some(p) => snippet_start + p,
                None => match html[snippet_start..].find("</span>") {
                    Some(p) => snippet_start + p,
                    None => snippet_start,
                },
            };
            if snippet_end > snippet_start {
                html_to_text(&html[snippet_start..snippet_end])
            } else {
                String::new()
            }
        } else {
            String::new()
        };

        // Decode DuckDuckGo redirect URL
        let actual_url = if href.contains("duckduckgo.com") {
            if let Some(uddg_pos) = href.find("uddg=") {
                let url_start = uddg_pos + 5;
                let url_end = href[url_start..].find('&').map(|p| url_start + p).unwrap_or(href.len());
                url_decode(&href[url_start..url_end])
            } else {
                href.to_string()
            }
        } else {
            href.to_string()
        };

        if !title.trim().is_empty() {
            let mut result = format!("{}. {}\n   {}", results.len() + 1, title.trim(), actual_url);
            if !snippet_text.trim().is_empty() {
                result.push_str(&format!("\n   {}", snippet_text.trim()));
            }
            results.push(result);
        }

        pos = title_end;
    }

    results
}

/// Basic URL decoding for search result URLs.
fn url_decode(s: &str) -> String {
    let mut result = String::with_capacity(s.len());
    let mut chars = s.chars();
    while let Some(ch) = chars.next() {
        if ch == '%' {
            let hex: String = chars.by_ref().take(2).collect();
            if let Ok(byte) = u8::from_str_radix(&hex, 16) {
                result.push(byte as char);
            }
        } else if ch == '+' {
            result.push(' ');
        } else {
            result.push(ch);
        }
    }
    result
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
