"""
Universal task schema for the general-purpose task generation system.

Every task defines a complete executable world: a goal, an environment,
allowed tools, hidden ground truth, an automatic evaluator, and capability tags.
"""

from dataclasses import dataclass, field, asdict
from enum import Enum
from typing import Optional
import json
import hashlib
import time


class TaskCategory(str, Enum):
    """Top-level task categories covering the full agent capability space."""
    REPO_DEBUG = "repo_debug"              # Bug fixing, feature implementation in repos
    DOCS_RECONCILIATION = "docs_reconciliation"  # Reading docs, reconciling with code
    WEB_SEARCH = "web_search"              # Web search and synthesis of external info
    LOCAL_OPS = "local_ops"                # File manipulation, scripts, dependencies
    ENV_DEBUG = "env_debug"                # Environment debugging, log inspection
    DATA_ANALYSIS = "data_analysis"        # Data analysis and artifact generation
    MULTI_STEP = "multi_step"              # Long-horizon multi-step planning
    AMBIGUOUS = "ambiguous"                # Incomplete/ambiguous requests requiring investigation
    DIAGNOSTIC = "diagnostic"              # Boundary-probing tasks designed to find failure modes


class Capability(str, Enum):
    """Fine-grained capabilities exercised by tasks."""
    # Search & Navigation
    FILE_SEARCH = "file_search"            # Finding files by name/pattern
    CODE_SEARCH = "code_search"            # Searching code content (grep, ripgrep)
    DIRECTORY_NAVIGATION = "dir_nav"       # Navigating directory structures
    SYMBOL_LOOKUP = "symbol_lookup"        # Finding function/class definitions

    # Reading & Comprehension
    CODE_READING = "code_reading"          # Understanding existing code
    LOG_ANALYSIS = "log_analysis"          # Reading and interpreting log files
    DOC_READING = "doc_reading"            # Reading documentation/READMEs
    CONFIG_READING = "config_reading"      # Understanding config files (yaml, toml, json)
    ERROR_INTERPRETATION = "error_interp"  # Understanding error messages/tracebacks

    # Writing & Modification
    CODE_WRITING = "code_writing"          # Writing new code
    CODE_EDITING = "code_editing"          # Modifying existing code
    FILE_CREATION = "file_creation"        # Creating new files
    CONFIG_EDITING = "config_editing"      # Editing configuration files
    SCRIPT_WRITING = "script_writing"      # Writing shell/automation scripts

    # Execution & Testing
    SHELL_COMMANDS = "shell_commands"      # Running shell commands
    TEST_RUNNING = "test_running"          # Running test suites
    BUILD_SYSTEMS = "build_systems"        # Understanding build tools (make, cargo, npm)
    DEPENDENCY_MGMT = "dep_mgmt"           # Managing dependencies/packages

    # Reasoning & Planning
    ROOT_CAUSE_ANALYSIS = "root_cause"     # Diagnosing why something is broken
    MULTI_FILE_REASONING = "multi_file"    # Reasoning across multiple files
    DECOMPOSITION = "decomposition"        # Breaking problems into steps
    PRIORITIZATION = "prioritization"      # Deciding what to do first
    HYPOTHESIS_TESTING = "hypothesis_test" # Forming and testing hypotheses

    # External Tools
    GIT_OPERATIONS = "git_ops"             # Git commands beyond basic status
    WEB_FETCH = "web_fetch"               # Fetching web content
    WEB_SEARCH_SKILL = "web_search"       # Searching the web for information
    API_INTERACTION = "api_interaction"     # Calling APIs

    # Communication
    CLARIFICATION = "clarification"        # Asking for clarification on ambiguity
    SUMMARY_GENERATION = "summary_gen"     # Summarizing findings
    EXPLANATION = "explanation"            # Explaining code/decisions


class EvalMethod(str, Enum):
    """How a task's success is evaluated."""
    DIFF_MATCH = "diff_match"              # Compare file diffs (existing SWE approach)
    FILE_CONTENT = "file_content"          # Check specific file contents exist
    FILE_EXISTS = "file_exists"            # Check files/dirs were created
    COMMAND_OUTPUT = "command_output"       # Run command, check output matches
    TEST_PASS = "test_pass"               # Run test suite, check pass/fail
    SCRIPT_CHECK = "script_check"          # Run custom validation script
    LLM_JUDGE = "llm_judge"              # LLM evaluates output quality
    COMPOSITE = "composite"               # Multiple eval methods combined


@dataclass
class EnvironmentSetup:
    """Defines how to set up the task environment."""
    # What kind of base environment
    env_type: str = "empty"               # "empty", "git_repo", "directory", "docker"

    # For git_repo type
    repo_url: Optional[str] = None
    base_commit: Optional[str] = None
    clone_depth: Optional[int] = None

    # Setup commands to run in order
    setup_commands: list[str] = field(default_factory=list)

    # Files to create/seed in the environment
    seed_files: dict[str, str] = field(default_factory=dict)  # path -> content

    # Working directory (relative to env root)
    workdir: str = "."

    # Environment variables to set
    env_vars: dict[str, str] = field(default_factory=dict)


@dataclass
class EvalSpec:
    """Defines how to evaluate task success."""
    method: EvalMethod = EvalMethod.COMMAND_OUTPUT

    # For DIFF_MATCH: expected patch
    expected_patch: Optional[str] = None

    # For FILE_CONTENT: file -> expected content substring
    expected_content: dict[str, str] = field(default_factory=dict)

    # For FILE_EXISTS: list of paths that should exist
    expected_files: list[str] = field(default_factory=list)

    # For COMMAND_OUTPUT: command to run and expected output
    check_command: Optional[str] = None
    expected_output: Optional[str] = None
    output_contains: Optional[list[str]] = None  # output must contain all these
    output_not_contains: Optional[list[str]] = None  # must not contain these

    # For TEST_PASS: test command
    test_command: Optional[str] = None

    # For SCRIPT_CHECK: path to validation script (returns 0 for pass)
    check_script: Optional[str] = None
    check_script_content: Optional[str] = None  # inline script content

    # For LLM_JUDGE: rubric for LLM evaluation
    rubric: Optional[str] = None

    # For COMPOSITE: list of sub-evaluations (all must pass)
    sub_evals: Optional[list] = None  # list of EvalSpec dicts

    # Partial credit (0.0 to 1.0 threshold)
    pass_threshold: float = 1.0


@dataclass
class Task:
    """Universal task definition."""
    # Identity
    task_id: str = ""
    category: TaskCategory = TaskCategory.LOCAL_OPS
    title: str = ""
    difficulty: str = "medium"  # easy, medium, hard

    # The problem
    goal: str = ""  # What the agent should do (user-facing prompt)
    hints: Optional[str] = None  # Optional hints (not shown to agent by default)

    # Environment
    environment: EnvironmentSetup = field(default_factory=EnvironmentSetup)

    # Allowed tools (empty = all tools allowed)
    allowed_tools: list[str] = field(default_factory=list)

    # Ground truth (hidden from agent)
    ground_truth: str = ""  # Description of correct solution
    solution_patch: Optional[str] = None  # Optional: exact diff solution

    # Evaluation
    eval_spec: EvalSpec = field(default_factory=EvalSpec)

    # Capability tags
    capabilities: list[Capability] = field(default_factory=list)

    # Metadata
    source: str = ""  # How this task was generated
    generated_at: str = ""
    estimated_minutes: int = 5

    def __post_init__(self):
        if not self.task_id:
            h = hashlib.md5(f"{self.category}:{self.title}:{time.time()}".encode()).hexdigest()[:8]
            self.task_id = f"{self.category.value}_{h}"
        if not self.generated_at:
            from datetime import datetime, timezone
            self.generated_at = datetime.now(timezone.utc).isoformat()

    def to_dict(self) -> dict:
        d = asdict(self)
        d["category"] = self.category.value
        d["capabilities"] = [c.value for c in self.capabilities]
        d["eval_spec"]["method"] = self.eval_spec.method.value
        return d

    def to_json(self, indent: int = 2) -> str:
        return json.dumps(self.to_dict(), indent=indent)

    @classmethod
    def from_dict(cls, d: dict) -> "Task":
        d = d.copy()
        d["category"] = TaskCategory(d["category"])
        d["capabilities"] = [Capability(c) for c in d.get("capabilities", [])]
        env = d.get("environment", {})
        d["environment"] = EnvironmentSetup(**env)
        ev = d.get("eval_spec", {})
        ev["method"] = EvalMethod(ev.get("method", "command_output"))
        d["eval_spec"] = EvalSpec(**ev)
        return cls(**d)

    @classmethod
    def from_json(cls, s: str) -> "Task":
        return cls.from_dict(json.loads(s))
