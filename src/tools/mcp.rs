use serde::{Deserialize, Serialize};
use serde_json::{json, Value};
use std::collections::HashMap;
use std::io::{BufRead, BufReader, Write};
use std::path::Path;
use std::process::{Child, Command, Stdio};
use std::sync::atomic::{AtomicU64, Ordering};
use std::sync::Mutex;

use crate::agent::api_client::ToolDef;

/// MCP server configuration (from .ninja/mcp.json or CLI)
#[derive(Debug, Clone, Deserialize)]
pub struct McpServerConfig {
    /// Display name for this server
    pub name: String,
    /// Command to launch the server
    pub command: String,
    /// Arguments for the command
    #[serde(default)]
    pub args: Vec<String>,
    /// Environment variables to set
    #[serde(default)]
    pub env: HashMap<String, String>,
}

/// A running MCP server connection
pub struct McpConnection {
    config: McpServerConfig,
    child: Child,
    request_id: AtomicU64,
}

/// Global MCP manager holding all active connections
pub struct McpManager {
    connections: Vec<Mutex<McpConnection>>,
    /// Map from tool name -> connection index
    tool_routing: HashMap<String, usize>,
    /// Tool definitions discovered from MCP servers
    tool_defs: Vec<ToolDef>,
}

/// JSON-RPC 2.0 request
#[derive(Serialize)]
struct JsonRpcRequest {
    jsonrpc: String,
    id: u64,
    method: String,
    #[serde(skip_serializing_if = "Option::is_none")]
    params: Option<Value>,
}

/// JSON-RPC 2.0 response
#[derive(Deserialize)]
struct JsonRpcResponse {
    #[allow(dead_code)]
    jsonrpc: String,
    #[allow(dead_code)]
    id: Option<u64>,
    result: Option<Value>,
    error: Option<JsonRpcError>,
}

#[derive(Deserialize)]
struct JsonRpcError {
    #[allow(dead_code)]
    code: i64,
    message: String,
}

impl McpConnection {
    fn new(config: McpServerConfig) -> Result<Self, String> {
        let mut cmd = Command::new(&config.command);
        cmd.args(&config.args)
            .stdin(Stdio::piped())
            .stdout(Stdio::piped())
            .stderr(Stdio::null());

        for (k, v) in &config.env {
            cmd.env(k, v);
        }

        let child = cmd
            .spawn()
            .map_err(|e| format!("Failed to start MCP server '{}': {}", config.name, e))?;

        Ok(Self {
            config,
            child,
            request_id: AtomicU64::new(1),
        })
    }

    fn send_request(&mut self, method: &str, params: Option<Value>) -> Result<Value, String> {
        let id = self.request_id.fetch_add(1, Ordering::SeqCst);
        let request = JsonRpcRequest {
            jsonrpc: "2.0".to_string(),
            id,
            method: method.to_string(),
            params,
        };

        let stdin = self
            .child
            .stdin
            .as_mut()
            .ok_or("MCP server stdin not available")?;
        let request_json = serde_json::to_string(&request)
            .map_err(|e| format!("Failed to serialize request: {}", e))?;

        writeln!(stdin, "{}", request_json)
            .map_err(|e| format!("Failed to write to MCP server: {}", e))?;
        stdin
            .flush()
            .map_err(|e| format!("Failed to flush MCP server stdin: {}", e))?;

        // Read response line from stdout
        let stdout = self
            .child
            .stdout
            .as_mut()
            .ok_or("MCP server stdout not available")?;
        let mut reader = BufReader::new(stdout);
        let mut line = String::new();
        reader
            .read_line(&mut line)
            .map_err(|e| format!("Failed to read from MCP server: {}", e))?;

        if line.is_empty() {
            return Err(format!(
                "MCP server '{}' closed connection",
                self.config.name
            ));
        }

        let response: JsonRpcResponse = serde_json::from_str(&line)
            .map_err(|e| format!("Failed to parse MCP response: {} (raw: {})", e, line.trim()))?;

        if let Some(error) = response.error {
            return Err(format!("MCP error: {}", error.message));
        }

        response.result.ok_or_else(|| "MCP response has no result".to_string())
    }
}

impl Drop for McpConnection {
    fn drop(&mut self) {
        let _ = self.child.kill();
    }
}

impl McpManager {
    pub fn new() -> Self {
        Self {
            connections: Vec::new(),
            tool_routing: HashMap::new(),
            tool_defs: Vec::new(),
        }
    }

    /// Load MCP server configs from .ninja/mcp.json
    pub fn load_config(workdir: &Path) -> Vec<McpServerConfig> {
        let config_path = workdir.join(".ninja/mcp.json");
        if !config_path.exists() {
            return Vec::new();
        }

        match std::fs::read_to_string(&config_path) {
            Ok(content) => {
                // Config format: { "servers": [ { name, command, args, env }, ... ] }
                let parsed: Result<Value, _> = serde_json::from_str(&content);
                match parsed {
                    Ok(val) => {
                        if let Some(servers) = val.get("servers").and_then(|s| s.as_array()) {
                            servers
                                .iter()
                                .filter_map(|s| serde_json::from_value::<McpServerConfig>(s.clone()).ok())
                                .collect()
                        } else {
                            eprintln!("Warning: .ninja/mcp.json missing 'servers' array");
                            Vec::new()
                        }
                    }
                    Err(e) => {
                        eprintln!("Warning: Failed to parse .ninja/mcp.json: {}", e);
                        Vec::new()
                    }
                }
            }
            Err(e) => {
                eprintln!("Warning: Failed to read .ninja/mcp.json: {}", e);
                Vec::new()
            }
        }
    }

    /// Connect to all configured MCP servers and discover their tools
    pub fn connect_all(&mut self, configs: Vec<McpServerConfig>) -> Vec<String> {
        let mut errors = Vec::new();

        for config in configs {
            let server_name = config.name.clone();
            match McpConnection::new(config) {
                Ok(conn) => {
                    let conn_idx = self.connections.len();
                    self.connections.push(Mutex::new(conn));

                    // Initialize the connection
                    if let Err(e) = self.initialize_server(conn_idx) {
                        errors.push(format!("Failed to initialize '{}': {}", server_name, e));
                        continue;
                    }

                    // Discover tools
                    match self.discover_tools(conn_idx, &server_name) {
                        Ok(count) => {
                            eprintln!("  MCP '{}': {} tools discovered", server_name, count);
                        }
                        Err(e) => {
                            errors.push(format!(
                                "Failed to discover tools from '{}': {}",
                                server_name, e
                            ));
                        }
                    }
                }
                Err(e) => {
                    errors.push(e);
                }
            }
        }

        errors
    }

    fn initialize_server(&self, idx: usize) -> Result<(), String> {
        let mut conn = self.connections[idx]
            .lock()
            .map_err(|e| format!("Lock error: {}", e))?;

        let params = json!({
            "protocolVersion": "2024-11-05",
            "capabilities": {},
            "clientInfo": {
                "name": "ninja",
                "version": env!("CARGO_PKG_VERSION")
            }
        });

        conn.send_request("initialize", Some(params))?;

        // Send initialized notification (no response expected, but we send it)
        let notification = json!({
            "jsonrpc": "2.0",
            "method": "notifications/initialized"
        });
        if let Some(stdin) = conn.child.stdin.as_mut() {
            let _ = writeln!(stdin, "{}", serde_json::to_string(&notification).unwrap());
            let _ = stdin.flush();
        }

        Ok(())
    }

    fn discover_tools(&mut self, conn_idx: usize, server_name: &str) -> Result<usize, String> {
        let mut conn = self.connections[conn_idx]
            .lock()
            .map_err(|e| format!("Lock error: {}", e))?;

        let result = conn.send_request("tools/list", None)?;

        let tools = result
            .get("tools")
            .and_then(|t| t.as_array())
            .ok_or("No tools array in response")?;

        let mut count = 0;
        for tool in tools {
            let name = tool
                .get("name")
                .and_then(|n| n.as_str())
                .unwrap_or("unknown");
            let description = tool
                .get("description")
                .and_then(|d| d.as_str())
                .unwrap_or("");
            let input_schema = tool
                .get("inputSchema")
                .cloned()
                .unwrap_or(json!({"type": "object", "properties": {}}));

            // Prefix tool name with server name to avoid collisions
            let prefixed_name = format!("mcp_{}_{}", server_name, name);

            self.tool_defs.push(ToolDef {
                name: prefixed_name.clone(),
                description: format!("[MCP:{}] {}", server_name, description),
                input_schema,
            });

            self.tool_routing.insert(prefixed_name, conn_idx);
            count += 1;
        }

        Ok(count)
    }

    /// Get all MCP tool definitions (to merge with built-in tools)
    pub fn tool_definitions(&self) -> Vec<ToolDef> {
        self.tool_defs.clone()
    }

    /// Check if a tool name is an MCP tool
    pub fn is_mcp_tool(&self, name: &str) -> bool {
        self.tool_routing.contains_key(name)
    }

    /// Execute an MCP tool call
    pub fn execute_tool(&self, name: &str, args: &Value) -> Result<String, String> {
        let conn_idx = self
            .tool_routing
            .get(name)
            .ok_or_else(|| format!("Unknown MCP tool: {}", name))?;

        let mut conn = self.connections[*conn_idx]
            .lock()
            .map_err(|e| format!("Lock error: {}", e))?;

        // Extract the original tool name (strip mcp_servername_ prefix)
        let original_name = name
            .splitn(3, '_')
            .nth(2)
            .unwrap_or(name);

        let params = json!({
            "name": original_name,
            "arguments": args
        });

        let result = conn.send_request("tools/call", Some(params))?;

        // Extract text content from response
        if let Some(content) = result.get("content").and_then(|c| c.as_array()) {
            let texts: Vec<String> = content
                .iter()
                .filter_map(|item| {
                    if item.get("type").and_then(|t| t.as_str()) == Some("text") {
                        item.get("text").and_then(|t| t.as_str()).map(String::from)
                    } else {
                        None
                    }
                })
                .collect();

            if texts.is_empty() {
                Ok(serde_json::to_string_pretty(&result).unwrap_or_default())
            } else {
                Ok(texts.join("\n"))
            }
        } else {
            Ok(serde_json::to_string_pretty(&result).unwrap_or_default())
        }
    }

    /// Check if any MCP servers are configured
    pub fn has_tools(&self) -> bool {
        !self.tool_defs.is_empty()
    }
}
