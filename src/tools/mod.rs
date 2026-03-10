mod file_ops;
mod shell;
mod search;
mod web;
mod navigate;
mod testing;
mod subagent;
mod todo;

use serde_json::Value;
use std::path::Path;

use crate::agent::api_client::ToolDef;

/// Get all tool definitions for the model API.
pub fn get_tool_definitions() -> Vec<ToolDef> {
    let mut tools = Vec::new();
    tools.extend(file_ops::definitions());
    tools.extend(shell::definitions());
    tools.extend(search::definitions());
    tools.extend(web::definitions());
    tools.extend(navigate::definitions());
    tools.extend(testing::definitions());
    tools.extend(subagent::definitions());
    tools.extend(todo::definitions());
    tools
}

/// Execute a tool by name with the given arguments.
pub fn execute_tool(name: &str, args: &Value, workdir: &Path) -> Result<String, String> {
    match name {
        "read_file" => file_ops::read_file(args, workdir),
        "write_file" => file_ops::write_file(args, workdir),
        "edit_file" => file_ops::edit_file(args, workdir),
        "list_dir" => file_ops::list_dir(args, workdir),
        "shell_exec" => shell::shell_exec(args, workdir),
        "glob_search" => search::glob_search(args, workdir),
        "grep_search" => search::grep_search(args, workdir),
        "web_fetch" => web::web_fetch(args, workdir),
        "web_search" => web::web_search(args, workdir),
        "find_definition" => navigate::find_definition(args, workdir),
        "find_references" => navigate::find_references(args, workdir),
        "run_tests" => testing::run_tests(args, workdir),
        "spawn_agent" => subagent::spawn_agent(args, workdir),
        "todo_write" => todo::todo_write(args, workdir),
        _ => Err(format!("Unknown tool: {}", name)),
    }
}
