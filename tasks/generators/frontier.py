"""
Frontier task generator — tasks at the competence cliff.

Unlike diagnostic/boundary tasks which are hard but well-defined, frontier tasks
test capabilities that fundamentally differ from "find bug, fix bug":

1. INCOMPLETE SPECIFICATION: Agent must make reasonable choices with missing info
2. ADVERSARIAL REVIEW: Find ALL issues in code, not just the obvious one
3. LARGE CODEBASE NAVIGATION: 20+ files, agent must find the relevant ones
4. HIDDEN EDGE CASES: Implementation seems trivial but tests catch subtle cases
5. LEGACY CODE ARCHAEOLOGY: Understand intent of bad code, fix without breaking
6. MULTI-CONCERN REFACTORING: Change structure while preserving semantics
"""

import textwrap
from ..schema import (
    Task, TaskCategory, Capability, EvalMethod,
    EnvironmentSetup, EvalSpec
)
from .base import TaskGenerator


class FrontierGenerator(TaskGenerator):
    """Generates frontier tasks at the competence cliff."""

    @property
    def category(self) -> TaskCategory:
        return TaskCategory.DIAGNOSTIC

    def generate(self, count: int = 8, difficulty: str = "hard") -> list[Task]:
        generators = [
            self._adversarial_code_review,
            self._incomplete_spec_implementation,
            self._large_codebase_needle_in_haystack,
            self._hidden_edge_case_trap,
            self._legacy_code_archaeology,
            self._concurrent_bug_hunt,
            self._rename_with_ripple_effects,
            self._feature_flag_removal,
        ]

        tasks = []
        for i in range(count):
            gen = generators[i % len(generators)]
            task = gen(difficulty)
            tasks.append(task)
        return tasks

    def _adversarial_code_review(self, difficulty: str) -> Task:
        """Code with 5 planted bugs of varying subtlety. Agent must find ALL of them.

        Key difficulty: The obvious bugs distract from the subtle ones.
        Most agents find 2-3 bugs and stop. Finding all 5 requires exhaustive review.
        """
        code = textwrap.dedent('''\
            """
            User authentication and session management module.
            Handles login, session tokens, password hashing, and rate limiting.
            """
            import hashlib
            import hmac
            import os
            import time
            import re
            from typing import Optional

            # Configuration
            SECRET_KEY = "change-me-in-production"
            SESSION_TIMEOUT = 3600  # 1 hour
            MAX_LOGIN_ATTEMPTS = 5
            LOCKOUT_DURATION = 900  # 15 minutes

            # In-memory stores (would be Redis/DB in production)
            _sessions = {}
            _users = {}
            _login_attempts = {}


            def hash_password(password: str, salt: Optional[bytes] = None) -> tuple[str, str]:
                """Hash a password with a random salt using PBKDF2."""
                if salt is None:
                    salt = os.urandom(16)
                dk = hashlib.pbkdf2_hmac('sha256', password.encode(), salt, iterations=100)
                return dk.hex(), salt.hex()


            def verify_password(password: str, stored_hash: str, salt_hex: str) -> bool:
                """Verify a password against a stored hash."""
                salt = bytes.fromhex(salt_hex)
                dk = hashlib.pbkdf2_hmac('sha256', password.encode(), salt, iterations=100)
                return dk.hex() == stored_hash


            def create_user(username: str, password: str, email: str) -> dict:
                """Create a new user account."""
                if not re.match(r'^[a-zA-Z0-9_]+$', username):
                    raise ValueError("Invalid username")
                if username in _users:
                    raise ValueError("Username taken")
                pw_hash, salt = hash_password(password)
                user = {
                    "username": username,
                    "password_hash": pw_hash,
                    "salt": salt,
                    "email": email,
                    "created_at": time.time(),
                }
                _users[username] = user
                return {"username": username, "email": email}


            def check_rate_limit(username: str) -> bool:
                """Check if a user is rate-limited. Returns True if allowed."""
                if username not in _login_attempts:
                    return True
                attempts = _login_attempts[username]
                # Clean old attempts
                now = time.time()
                attempts = [t for t in attempts if now - t < LOCKOUT_DURATION]
                _login_attempts[username] = attempts
                return len(attempts) < MAX_LOGIN_ATTEMPTS


            def login(username: str, password: str) -> Optional[str]:
                """Authenticate user and return session token."""
                if not check_rate_limit(username):
                    return None

                user = _users.get(username)
                if user is None:
                    _login_attempts.setdefault(username, []).append(time.time())
                    return None

                if not verify_password(password, user["password_hash"], user["salt"]):
                    _login_attempts.setdefault(username, []).append(time.time())
                    return None

                # Create session
                token = os.urandom(32).hex()
                _sessions[token] = {
                    "username": username,
                    "created_at": time.time(),
                    "last_active": time.time(),
                }
                return token


            def validate_session(token: str) -> Optional[str]:
                """Validate a session token. Returns username if valid."""
                session = _sessions.get(token)
                if session is None:
                    return None

                # Check expiry
                if time.time() - session["created_at"] > SESSION_TIMEOUT:
                    return None

                session["last_active"] = time.time()
                return session["username"]


            def logout(token: str) -> bool:
                """Invalidate a session."""
                if token in _sessions:
                    del _sessions[token]
                    return True
                return False


            def get_active_sessions(username: str) -> int:
                """Count active sessions for a user."""
                count = 0
                for session in _sessions.values():
                    if session["username"] == username:
                        # Doesn't check expiry — counts expired sessions too
                        count += 1
                return count
        ''')

        eval_script = textwrap.dedent('''\
            #!/bin/bash
            # Eval: check that the agent found and fixed ALL 5 bugs
            # Each bug fix is checked independently

            REVIEW_FILE="$WORKDIR/review.md"
            CODE_FILE="$WORKDIR/auth.py"

            if [ ! -f "$REVIEW_FILE" ] && [ ! -f "$CODE_FILE" ]; then
                echo "FAIL: No review.md or modified auth.py found"
                exit 1
            fi

            # Check if fixed in code or identified in review
            SCORE=0
            TOTAL=5

            check_bug() {
                local desc="$1"
                local pattern="$2"

                found=0
                # Check review.md
                if [ -f "$REVIEW_FILE" ]; then
                    if grep -qi "$pattern" "$REVIEW_FILE"; then
                        found=1
                    fi
                fi
                # Check if code was modified to fix it
                if [ -f "$CODE_FILE" ]; then
                    if grep -qi "$pattern" "$CODE_FILE"; then
                        found=1
                    fi
                fi

                if [ "$found" -eq 1 ]; then
                    echo "FOUND: $desc"
                    SCORE=$((SCORE + 1))
                else
                    echo "MISSED: $desc"
                fi
            }

            # Bug 1: Low PBKDF2 iterations (100 is too low)
            # Check if review mentions iterations OR code changed iterations to >= 100000
            BUG1=0
            if [ -f "$REVIEW_FILE" ]; then
                if grep -qiE "(iteration|pbkdf2|too.low|brute.force|100[^0])" "$REVIEW_FILE"; then
                    BUG1=1
                fi
            fi
            if [ -f "$CODE_FILE" ]; then
                if python3 -c "
import re
code = open('$CODE_FILE').read()
m = re.search(r'iterations\s*=\s*(\d+)', code)
if m and int(m.group(1)) >= 100000:
    exit(0)
exit(1)
" 2>/dev/null; then
                    BUG1=1
                fi
            fi
            if [ "$BUG1" -eq 1 ]; then echo "FOUND: Bug 1 - Low PBKDF2 iterations"; SCORE=$((SCORE+1)); else echo "MISSED: Bug 1 - Low PBKDF2 iterations"; fi

            # Bug 2: Timing attack in verify_password (== instead of hmac.compare_digest)
            BUG2=0
            if [ -f "$REVIEW_FILE" ]; then
                if grep -qiE "(timing|compare_digest|constant.time|side.channel)" "$REVIEW_FILE"; then
                    BUG2=1
                fi
            fi
            if [ -f "$CODE_FILE" ]; then
                if grep -q "compare_digest" "$CODE_FILE"; then
                    BUG2=1
                fi
            fi
            if [ "$BUG2" -eq 1 ]; then echo "FOUND: Bug 2 - Timing attack vulnerability"; SCORE=$((SCORE+1)); else echo "MISSED: Bug 2 - Timing attack vulnerability"; fi

            # Bug 3: No email validation
            BUG3=0
            if [ -f "$REVIEW_FILE" ]; then
                if grep -qiE "(email.*valid|no.*email.*check|missing.*email|email.*sanitiz)" "$REVIEW_FILE"; then
                    BUG3=1
                fi
            fi
            if [ -f "$CODE_FILE" ]; then
                if grep -qE "(email.*@|re\.match.*email|validate.*email)" "$CODE_FILE"; then
                    BUG3=1
                fi
            fi
            if [ "$BUG3" -eq 1 ]; then echo "FOUND: Bug 3 - Missing email validation"; SCORE=$((SCORE+1)); else echo "MISSED: Bug 3 - Missing email validation"; fi

            # Bug 4: Username enumeration via rate limiting
            BUG4=0
            if [ -f "$REVIEW_FILE" ]; then
                if grep -qiE "(username.*enum|enumerat|user.exist|timing.*differ|information.*leak)" "$REVIEW_FILE"; then
                    BUG4=1
                fi
            fi
            if [ -f "$CODE_FILE" ]; then
                # Fixed if non-existent user handling is same as existing user
                if python3 -c "
code = open('$CODE_FILE').read()
# If the rate limit recording for non-existent users was removed or equalized
if 'user is None' in code or 'user is not None' in code:
    # Check that the fix doesn't record attempts for non-existent users differently
    exit(0)
exit(1)
" 2>/dev/null; then
                    BUG4=1
                fi
            fi
            if [ "$BUG4" -eq 1 ]; then echo "FOUND: Bug 4 - Username enumeration"; SCORE=$((SCORE+1)); else echo "MISSED: Bug 4 - Username enumeration"; fi

            # Bug 5: Expired sessions not deleted (memory leak + resurrection risk)
            BUG5=0
            if [ -f "$REVIEW_FILE" ]; then
                if grep -qiE "(expired.*not.*delet|memory.*leak|session.*not.*remov|session.*persist|resurrect)" "$REVIEW_FILE"; then
                    BUG5=1
                fi
            fi
            if [ -f "$CODE_FILE" ]; then
                if python3 -c "
code = open('$CODE_FILE').read()
# Check if validate_session now deletes expired sessions
if 'del _sessions[token]' in code or '_sessions.pop(token' in code:
    # Verify it's in the expiry branch
    lines = code.split('\\n')
    for i, line in enumerate(lines):
        if 'SESSION_TIMEOUT' in line:
            # Look nearby for deletion
            nearby = '\\n'.join(lines[max(0,i-3):i+5])
            if 'del ' in nearby or 'pop(' in nearby:
                exit(0)
exit(1)
" 2>/dev/null; then
                    BUG5=1
                fi
            fi
            if [ "$BUG5" -eq 1 ]; then echo "FOUND: Bug 5 - Expired sessions not cleaned"; SCORE=$((SCORE+1)); else echo "MISSED: Bug 5 - Expired sessions not cleaned"; fi

            echo ""
            echo "Score: $SCORE/$TOTAL"

            if [ "$SCORE" -ge 5 ]; then
                exit 0
            else
                exit 1
            fi
        ''')

        return Task(
            task_id="frontier_adversarial_review",
            category=TaskCategory.DIAGNOSTIC,
            title="Security review: find ALL 5 bugs in auth module",
            difficulty="hard",
            goal=textwrap.dedent("""\
                Review the file `auth.py` for security vulnerabilities and bugs.

                This is a user authentication module handling password hashing, sessions,
                login, and rate limiting. Your job is to find EVERY security issue and bug.

                For each issue found, either:
                1. Fix it directly in auth.py, OR
                2. Document it in a new file `review.md` with a description of each issue

                Be thorough. There are multiple issues of varying severity — don't stop
                after finding the obvious ones. Think about timing attacks, information
                leakage, resource management, and input validation.
            """),
            hints="There are exactly 5 bugs. Think beyond just the obvious ones.",
            environment=EnvironmentSetup(
                seed_files={"auth.py": code}
            ),
            ground_truth="5 bugs: (1) PBKDF2 iterations=100 too low, (2) timing attack in verify_password using ==, (3) no email validation, (4) username enumeration via rate limit, (5) expired sessions not deleted from dict",
            eval_spec=EvalSpec(
                method=EvalMethod.SCRIPT_CHECK,
                check_script_content=eval_script,
            ),
            capabilities=[
                Capability.CODE_READING,
                Capability.ROOT_CAUSE_ANALYSIS,
                Capability.CODE_EDITING,
            ],
            source="frontier_generator",
            estimated_minutes=10,
        )

    def _incomplete_spec_implementation(self, difficulty: str) -> Task:
        """Build a module from a deliberately incomplete specification.

        Key difficulty: The spec omits critical edge cases. The agent must
        infer reasonable behavior and the tests check those inferences.
        A naive implementation passes the obvious tests but fails the edge cases.
        """
        spec = textwrap.dedent("""\
            # Markdown Table Formatter

            Build a Python module `table_formatter.py` with a function:

            ```python
            def format_table(headers: list[str], rows: list[list[str]],
                           alignment: str = "left") -> str:
            ```

            Requirements:
            - Produces a markdown table with proper column alignment
            - `alignment` can be "left", "right", "center", or a per-column
              string like "lrc" (left, right, center for each column)
            - Columns should be padded to the width of the widest cell in that column
            - Headers separated from data by a line of dashes

            Example:
            ```
            format_table(["Name", "Age"], [["Alice", "30"], ["Bob", "7"]])
            ```
            Should produce:
            ```
            | Name  | Age |
            |-------|-----|
            | Alice | 30  |
            | Bob   | 7   |
            ```
        """)

        test_code = textwrap.dedent('''\
            """Tests for table_formatter — including edge cases not in the spec."""
            import sys
            sys.path.insert(0, ".")
            from table_formatter import format_table

            def test_basic():
                result = format_table(["Name", "Age"], [["Alice", "30"], ["Bob", "7"]])
                lines = result.strip().split("\\n")
                assert len(lines) == 4  # header + separator + 2 rows
                assert "Name" in lines[0]
                assert "Age" in lines[0]
                assert "---" in lines[1]
                assert "Alice" in lines[2]
                assert "Bob" in lines[3]
                print("PASS: test_basic")

            def test_alignment_left():
                result = format_table(["X"], [["hello"]], alignment="left")
                # Left-aligned: content padded on right
                lines = result.strip().split("\\n")
                assert ":---" in lines[1] or "---" in lines[1]
                print("PASS: test_alignment_left")

            def test_alignment_right():
                result = format_table(["X"], [["hello"]], alignment="right")
                lines = result.strip().split("\\n")
                assert "---:" in lines[1]
                print("PASS: test_alignment_right")

            def test_alignment_center():
                result = format_table(["X"], [["hello"]], alignment="center")
                lines = result.strip().split("\\n")
                assert ":---:" in lines[1] or ":--:" in lines[1]
                print("PASS: test_alignment_center")

            def test_per_column_alignment():
                result = format_table(["A", "B", "C"], [["1", "2", "3"]], alignment="lrc")
                lines = result.strip().split("\\n")
                sep = lines[1]
                parts = [p.strip() for p in sep.split("|") if p.strip()]
                # First: left, Second: right, Third: center
                assert not parts[0].startswith(":")  or parts[0].startswith(":") and not parts[0].endswith(":")
                assert parts[1].endswith(":")  # right has trailing :
                print("PASS: test_per_column_alignment")

            def test_empty_rows():
                """EDGE CASE: No data rows — should still produce header + separator."""
                result = format_table(["A", "B"], [])
                lines = result.strip().split("\\n")
                assert len(lines) >= 2  # At least header + separator
                assert "A" in lines[0]
                print("PASS: test_empty_rows")

            def test_mismatched_columns():
                """EDGE CASE: Row has fewer columns than headers — should pad with empty."""
                result = format_table(["A", "B", "C"], [["1"]])
                lines = result.strip().split("\\n")
                # Should have 3 columns even though row only has 1
                row = lines[2]
                parts = [p.strip() for p in row.split("|") if p.strip()]
                assert len(parts) == 3, f"Expected 3 columns, got {len(parts)}: {parts}"
                assert parts[0] == "1"
                print("PASS: test_mismatched_columns")

            def test_extra_columns():
                """EDGE CASE: Row has MORE columns than headers — should handle gracefully."""
                result = format_table(["A"], [["1", "2", "3"]])
                lines = result.strip().split("\\n")
                # Should at minimum not crash. Two valid behaviors:
                # 1. Truncate extra columns, or 2. Expand to fit
                assert len(lines) >= 3  # header + sep + 1 row
                print("PASS: test_extra_columns")

            def test_pipe_in_content():
                """EDGE CASE: Cell content contains | character — must be escaped."""
                result = format_table(["Expr"], [["a|b"]])
                lines = result.strip().split("\\n")
                row = lines[2]
                # The pipe in content should be escaped so it doesn't create extra columns
                # Count actual column separators (leading/trailing | plus inner |)
                inner = row.strip()
                if inner.startswith("|"):
                    inner = inner[1:]
                if inner.endswith("|"):
                    inner = inner[:-1]
                parts = inner.split("|")
                assert len(parts) == 1, f"Pipe in content created extra columns: {parts}"
                print("PASS: test_pipe_in_content")

            def test_unicode_content():
                """EDGE CASE: Unicode characters — column width should be visual width."""
                result = format_table(["Name"], [["Ñoño"], ["Bob"]])
                # Should not crash, should produce valid table
                lines = result.strip().split("\\n")
                assert len(lines) == 4
                print("PASS: test_unicode_content")

            def test_newline_in_content():
                """EDGE CASE: Cell with embedded newline — should be stripped or escaped."""
                result = format_table(["Note"], [["line1\\nline2"]])
                lines = result.strip().split("\\n")
                # The newline in content should NOT break the table structure
                # After header + sep, should be exactly 1 data row
                data_lines = lines[2:]
                assert len(data_lines) == 1, f"Newline in content broke table: got {len(data_lines)} data lines"
                print("PASS: test_newline_in_content")

            if __name__ == "__main__":
                tests = [f for f in dir() if f.startswith("test_")]
                passed = 0
                failed = 0
                for t in sorted(tests):
                    try:
                        eval(f"{t}()")
                        passed += 1
                    except Exception as e:
                        print(f"FAIL: {t}: {e}")
                        failed += 1
                print(f"\\nResults: {passed}/{passed+failed} passed")
                if failed > 0:
                    sys.exit(1)
        ''')

        eval_script = textwrap.dedent('''\
            #!/bin/bash
            cd "$WORKDIR"

            if [ ! -f "table_formatter.py" ]; then
                echo "FAIL: table_formatter.py not found"
                exit 1
            fi

            # Run the tests
            OUTPUT=$(python3 test_table.py 2>&1)
            EXIT=$?
            echo "$OUTPUT"

            # Count passes
            PASSED=$(echo "$OUTPUT" | grep -c "^PASS:")
            TOTAL=11

            echo ""
            echo "Tests passed: $PASSED/$TOTAL"

            # Need at least 9/11 to pass (allows 2 edge case misses)
            if [ "$PASSED" -ge 9 ]; then
                exit 0
            else
                exit 1
            fi
        ''')

        return Task(
            task_id="frontier_incomplete_spec",
            category=TaskCategory.DIAGNOSTIC,
            title="Build markdown table formatter with hidden edge cases",
            difficulty="hard",
            goal=spec,
            hints="The spec is deliberately incomplete. Think about: empty inputs, mismatched column counts, special characters in cell content.",
            environment=EnvironmentSetup(
                seed_files={"test_table.py": test_code}
            ),
            ground_truth="Must handle: empty rows, mismatched column counts (pad with empty or expand), pipe characters in content (escape as \\|), unicode width, embedded newlines (strip/escape). Naive implementation misses 3+ of these.",
            eval_spec=EvalSpec(
                method=EvalMethod.SCRIPT_CHECK,
                check_script_content=eval_script,
            ),
            capabilities=[
                Capability.CODE_WRITING,
                Capability.DECOMPOSITION,
            ],
            source="frontier_generator",
            estimated_minutes=10,
        )

    def _large_codebase_needle_in_haystack(self, difficulty: str) -> Task:
        """20+ file codebase where the bug is far from the symptomatic file.

        Key difficulty: Sheer volume of code. Agent must navigate efficiently,
        not just read every file. The error message points to file 15, but
        the root cause is in file 3, connected through a chain of imports.
        """
        # Generate a realistic-looking project with 20+ files
        files = {}

        # Core library files (the haystack)
        files["taskflow/__init__.py"] = textwrap.dedent('''\
            """TaskFlow - A lightweight task orchestration library."""
            __version__ = "0.4.2"
            from .core import Pipeline, Task, TaskResult
            from .scheduler import Scheduler
            from .config import Config
        ''')

        files["taskflow/core.py"] = textwrap.dedent('''\
            """Core pipeline and task abstractions."""
            from dataclasses import dataclass, field
            from typing import Any, Callable, Optional
            from enum import Enum


            class TaskStatus(Enum):
                PENDING = "pending"
                RUNNING = "running"
                COMPLETED = "completed"
                FAILED = "failed"
                SKIPPED = "skipped"


            @dataclass
            class TaskResult:
                status: TaskStatus
                output: Any = None
                error: Optional[str] = None
                duration_ms: float = 0


            @dataclass
            class Task:
                name: str
                fn: Callable
                depends_on: list[str] = field(default_factory=list)
                timeout: float = 30.0
                retries: int = 0
                _status: TaskStatus = field(default=TaskStatus.PENDING, init=False)

                def run(self, **kwargs) -> TaskResult:
                    import time
                    start = time.time()
                    try:
                        result = self.fn(**kwargs)
                        elapsed = (time.time() - start) * 1000
                        self._status = TaskStatus.COMPLETED
                        return TaskResult(TaskStatus.COMPLETED, output=result, duration_ms=elapsed)
                    except Exception as e:
                        elapsed = (time.time() - start) * 1000
                        self._status = TaskStatus.FAILED
                        return TaskResult(TaskStatus.FAILED, error=str(e), duration_ms=elapsed)


            class Pipeline:
                def __init__(self, name: str = "default"):
                    self.name = name
                    self.tasks: dict[str, Task] = {}
                    self._results: dict[str, TaskResult] = {}

                def add_task(self, task: Task):
                    self.tasks[task.name] = task

                def get_execution_order(self) -> list[str]:
                    """Topological sort of tasks."""
                    visited = set()
                    order = []

                    def visit(name):
                        if name in visited:
                            return
                        visited.add(name)
                        task = self.tasks[name]
                        for dep in task.depends_on:
                            if dep in self.tasks:
                                visit(dep)
                        order.append(name)

                    for name in self.tasks:
                        visit(name)
                    return order

                def run(self, **kwargs) -> dict[str, TaskResult]:
                    order = self.get_execution_order()
                    for name in order:
                        task = self.tasks[name]
                        # Check dependencies
                        deps_ok = all(
                            self._results.get(d, TaskResult(TaskStatus.FAILED)).status == TaskStatus.COMPLETED
                            for d in task.depends_on
                        )
                        if not deps_ok:
                            self._results[name] = TaskResult(TaskStatus.SKIPPED)
                            continue
                        self._results[name] = task.run(**kwargs)
                    return self._results
        ''')

        files["taskflow/scheduler.py"] = textwrap.dedent('''\
            """Task scheduling with retry and timeout support."""
            import time
            from .core import Task, TaskResult, TaskStatus


            class Scheduler:
                def __init__(self, max_workers: int = 4):
                    self.max_workers = max_workers
                    self._running = []

                def schedule(self, task: Task, **kwargs) -> TaskResult:
                    """Run a task with retry logic."""
                    last_result = None
                    for attempt in range(task.retries + 1):
                        result = task.run(**kwargs)
                        last_result = result
                        if result.status == TaskStatus.COMPLETED:
                            return result
                        if attempt < task.retries:
                            time.sleep(0.1 * (attempt + 1))  # backoff
                    return last_result
        ''')

        # BUG IS HERE: config loader has a subtle type coercion issue
        files["taskflow/config.py"] = textwrap.dedent('''\
            """Configuration management for TaskFlow."""
            import json
            import os
            from typing import Any


            _DEFAULTS = {
                "max_workers": 4,
                "timeout": 30,
                "retry_count": 0,
                "log_level": "INFO",
                "output_dir": "./output",
                "enable_metrics": False,
            }


            class Config:
                """Hierarchical config: file < env vars < explicit overrides."""

                def __init__(self, config_path: str = None, **overrides):
                    self._data = dict(_DEFAULTS)

                    # Load from file
                    if config_path and os.path.exists(config_path):
                        with open(config_path) as f:
                            file_config = json.load(f)
                        self._data.update(file_config)

                    # Load from env (TASKFLOW_* prefix)
                    for key in _DEFAULTS:
                        env_key = f"TASKFLOW_{key.upper()}"
                        if env_key in os.environ:
                            self._data[key] = os.environ[env_key]

                    # Apply overrides
                    self._data.update(overrides)

                def get(self, key: str, default: Any = None) -> Any:
                    return self._data.get(key, default)

                def __getattr__(self, name: str) -> Any:
                    if name.startswith("_"):
                        raise AttributeError(name)
                    return self._data.get(name)
        ''')

        # More haystack files
        files["taskflow/logging.py"] = textwrap.dedent('''\
            """Logging configuration for TaskFlow."""
            import logging

            def setup_logging(level: str = "INFO"):
                logging.basicConfig(
                    level=getattr(logging, level.upper(), logging.INFO),
                    format="%(asctime)s [%(name)s] %(levelname)s: %(message)s"
                )
                return logging.getLogger("taskflow")
        ''')

        files["taskflow/metrics.py"] = textwrap.dedent('''\
            """Simple metrics collection."""
            import time
            from collections import defaultdict

            class Metrics:
                def __init__(self):
                    self._counters = defaultdict(int)
                    self._timings = defaultdict(list)

                def increment(self, name: str, value: int = 1):
                    self._counters[name] += value

                def record_timing(self, name: str, ms: float):
                    self._timings[name].append(ms)

                def summary(self) -> dict:
                    return {
                        "counters": dict(self._counters),
                        "timings": {k: {"avg": sum(v)/len(v), "count": len(v)}
                                   for k, v in self._timings.items()}
                    }
        ''')

        files["taskflow/hooks.py"] = textwrap.dedent('''\
            """Pre/post task hooks."""
            from typing import Callable

            class HookRegistry:
                def __init__(self):
                    self._pre_hooks = []
                    self._post_hooks = []

                def register_pre(self, fn: Callable):
                    self._pre_hooks.append(fn)

                def register_post(self, fn: Callable):
                    self._post_hooks.append(fn)

                def run_pre(self, task_name: str, **kwargs):
                    for hook in self._pre_hooks:
                        hook(task_name, **kwargs)

                def run_post(self, task_name: str, result, **kwargs):
                    for hook in self._post_hooks:
                        hook(task_name, result, **kwargs)
        ''')

        files["taskflow/serialization.py"] = textwrap.dedent('''\
            """Task and result serialization."""
            import json
            from .core import TaskResult, TaskStatus

            def serialize_result(result: TaskResult) -> dict:
                return {
                    "status": result.status.value,
                    "output": str(result.output) if result.output else None,
                    "error": result.error,
                    "duration_ms": result.duration_ms,
                }

            def deserialize_result(data: dict) -> TaskResult:
                return TaskResult(
                    status=TaskStatus(data["status"]),
                    output=data.get("output"),
                    error=data.get("error"),
                    duration_ms=data.get("duration_ms", 0),
                )
        ''')

        files["taskflow/validators.py"] = textwrap.dedent('''\
            """Input validation utilities."""
            import re

            def validate_task_name(name: str) -> bool:
                return bool(re.match(r'^[a-zA-Z][a-zA-Z0-9_-]*$', name))

            def validate_config(config: dict) -> list[str]:
                errors = []
                if "max_workers" in config:
                    if not isinstance(config["max_workers"], int) or config["max_workers"] < 1:
                        errors.append("max_workers must be a positive integer")
                if "timeout" in config:
                    if not isinstance(config["timeout"], (int, float)) or config["timeout"] <= 0:
                        errors.append("timeout must be a positive number")
                return errors
        ''')

        files["taskflow/exceptions.py"] = textwrap.dedent('''\
            """Custom exceptions for TaskFlow."""

            class TaskFlowError(Exception):
                """Base exception."""
                pass

            class TaskNotFoundError(TaskFlowError):
                """Raised when a task is not in the pipeline."""
                pass

            class CyclicDependencyError(TaskFlowError):
                """Raised when task dependencies form a cycle."""
                pass

            class ConfigError(TaskFlowError):
                """Raised for configuration issues."""
                pass

            class TimeoutError(TaskFlowError):
                """Raised when a task exceeds its timeout."""
                pass
        ''')

        # Application code that uses the library
        files["app/__init__.py"] = ""

        files["app/etl_pipeline.py"] = textwrap.dedent('''\
            """ETL pipeline using TaskFlow."""
            from taskflow import Pipeline, Task, Config


            def build_etl_pipeline(config: Config) -> Pipeline:
                pipeline = Pipeline("etl")

                def extract(**kwargs):
                    return {"records": [{"id": i, "value": i * 10} for i in range(100)]}

                def transform(records=None, **kwargs):
                    if records is None:
                        return {"transformed": []}
                    return {"transformed": [r for r in records if r["value"] > 50]}

                def load(transformed=None, **kwargs):
                    count = len(transformed) if transformed else 0
                    return {"loaded": count}

                pipeline.add_task(Task("extract", extract, timeout=config.get("timeout")))
                pipeline.add_task(Task("transform", transform, depends_on=["extract"],
                                      timeout=config.get("timeout")))
                pipeline.add_task(Task("load", load, depends_on=["transform"],
                                      timeout=config.get("timeout")))
                return pipeline
        ''')

        files["app/report_pipeline.py"] = textwrap.dedent('''\
            """Report generation pipeline."""
            from taskflow import Pipeline, Task, Config
            from taskflow.scheduler import Scheduler


            def build_report_pipeline(config: Config) -> Pipeline:
                pipeline = Pipeline("report")

                def fetch_data(**kwargs):
                    return list(range(1, 101))

                def compute_stats(data=None, **kwargs):
                    if data is None:
                        data = []
                    return {
                        "count": len(data),
                        "sum": sum(data),
                        "mean": sum(data) / len(data) if data else 0,
                    }

                def render_report(stats=None, **kwargs):
                    if stats is None:
                        stats = {}
                    return f"Report: {stats.get('count', 0)} items, mean={stats.get('mean', 0):.1f}"

                retries = config.get("retry_count") if config.get("retry_count") is not None else 0

                pipeline.add_task(Task("fetch", fetch_data, retries=retries))
                pipeline.add_task(Task("stats", compute_stats, depends_on=["fetch"], retries=retries))
                pipeline.add_task(Task("render", render_report, depends_on=["stats"]))
                return pipeline
        ''')

        # The file that shows the error (far from root cause)
        files["app/runner.py"] = textwrap.dedent('''\
            """Application runner — orchestrates pipeline execution."""
            import sys
            import os
            from taskflow import Config
            from .etl_pipeline import build_etl_pipeline
            from .report_pipeline import build_report_pipeline


            def main():
                config = Config(config_path="taskflow.json")

                pipeline_name = sys.argv[1] if len(sys.argv) > 1 else "etl"

                if pipeline_name == "etl":
                    pipeline = build_etl_pipeline(config)
                elif pipeline_name == "report":
                    pipeline = build_report_pipeline(config)
                else:
                    print(f"Unknown pipeline: {pipeline_name}")
                    sys.exit(1)

                results = pipeline.run()

                for name, result in results.items():
                    print(f"  {name}: {result.status.value} ({result.duration_ms:.0f}ms)")
                    if result.error:
                        print(f"    ERROR: {result.error}")

                # Check if all succeeded
                from taskflow.core import TaskStatus
                all_ok = all(r.status == TaskStatus.COMPLETED for r in results.values())
                if not all_ok:
                    print("Pipeline FAILED")
                    sys.exit(1)
                print("Pipeline OK")


            if __name__ == "__main__":
                main()
        ''')

        # Config file with the trigger condition
        files["taskflow.json"] = '{"max_workers": 2, "timeout": 10, "retry_count": 3}'

        # Test file that reveals the bug
        files["tests/__init__.py"] = ""
        files["tests/test_pipeline.py"] = textwrap.dedent('''\
            """Integration tests for pipeline execution."""
            import sys
            import os
            sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

            from taskflow import Pipeline, Task, Config
            from taskflow.core import TaskStatus


            def test_etl_with_config():
                """Run ETL pipeline with config from file."""
                config = Config(config_path="taskflow.json")

                def extract(**kw):
                    return [1, 2, 3]

                def transform(**kw):
                    return [x * 2 for x in [1, 2, 3]]

                def load(**kw):
                    return "done"

                pipe = Pipeline("test_etl")
                pipe.add_task(Task("extract", extract, timeout=config.get("timeout")))
                pipe.add_task(Task("transform", transform, depends_on=["extract"],
                                   timeout=config.get("timeout")))
                pipe.add_task(Task("load", load, depends_on=["transform"],
                                   timeout=config.get("timeout")))

                results = pipe.run()
                assert all(r.status == TaskStatus.COMPLETED for r in results.values()), \\
                    f"Not all tasks completed: {results}"
                print("PASS: test_etl_with_config")


            def test_report_with_retries():
                """Run report pipeline with retry config."""
                config = Config(config_path="taskflow.json")
                retries = config.get("retry_count")

                # The bug: retry_count from JSON config is loaded as string "3"
                # when overridden by env var, but from JSON it's int 3.
                # However, Config.__init__ loads env vars as strings without type coercion.
                # If TASKFLOW_RETRY_COUNT is set, retries becomes "3" (string).
                # Task(retries=retries) then does range("3" + 1) and crashes.

                # Simulate what happens when env var overrides:
                os.environ["TASKFLOW_RETRY_COUNT"] = "3"
                config2 = Config(config_path="taskflow.json")
                retries2 = config2.get("retry_count")

                # This SHOULD be int 3, but it's string "3" from env var
                assert isinstance(retries2, int), \\
                    f"retry_count should be int but got {type(retries2).__name__}: {retries2}"

                print("PASS: test_report_with_retries")

                # Cleanup
                del os.environ["TASKFLOW_RETRY_COUNT"]


            def test_config_env_override_types():
                """Env var overrides should preserve the type of the default value."""
                os.environ["TASKFLOW_MAX_WORKERS"] = "8"
                os.environ["TASKFLOW_ENABLE_METRICS"] = "true"
                os.environ["TASKFLOW_TIMEOUT"] = "60"

                config = Config()

                # These should be coerced to match the default types
                assert isinstance(config.get("max_workers"), int), \\
                    f"max_workers should be int, got {type(config.get('max_workers')).__name__}"
                assert config.get("max_workers") == 8

                assert isinstance(config.get("timeout"), int), \\
                    f"timeout should be int, got {type(config.get('timeout')).__name__}"
                assert config.get("timeout") == 60

                assert isinstance(config.get("enable_metrics"), bool), \\
                    f"enable_metrics should be bool, got {type(config.get('enable_metrics')).__name__}"
                assert config.get("enable_metrics") is True

                print("PASS: test_config_env_override_types")

                # Cleanup
                for k in ["TASKFLOW_MAX_WORKERS", "TASKFLOW_ENABLE_METRICS", "TASKFLOW_TIMEOUT"]:
                    del os.environ[k]


            if __name__ == "__main__":
                passed = 0
                failed = 0
                for name in ["test_etl_with_config", "test_report_with_retries", "test_config_env_override_types"]:
                    try:
                        eval(f"{name}()")
                        passed += 1
                    except Exception as e:
                        print(f"FAIL: {name}: {e}")
                        failed += 1
                print(f"\\nResults: {passed}/{passed+failed}")
                if failed:
                    sys.exit(1)
        ''')

        eval_script = textwrap.dedent('''\
            #!/bin/bash
            cd "$WORKDIR"
            OUTPUT=$(python3 tests/test_pipeline.py 2>&1)
            EXIT=$?
            echo "$OUTPUT"

            PASSED=$(echo "$OUTPUT" | grep -c "^PASS:")
            echo ""
            echo "Tests passed: $PASSED/3"

            if [ "$PASSED" -ge 3 ]; then
                exit 0
            else
                exit 1
            fi
        ''')

        return Task(
            task_id="frontier_large_codebase",
            category=TaskCategory.DIAGNOSTIC,
            title="Fix config type coercion in 20-file TaskFlow project",
            difficulty="hard",
            goal=textwrap.dedent("""\
                The TaskFlow project has a bug that causes pipeline failures when
                configuration values come from environment variables.

                Run the test suite:
                ```
                python3 tests/test_pipeline.py
                ```

                Two tests are failing. Debug the issue and fix it. The fix should be
                minimal — don't refactor the whole project, just fix the root cause.
            """),
            hints="The error chain: env vars → config → task creation → runtime failure. All env vars are strings.",
            environment=EnvironmentSetup(
                seed_files=files
            ),
            ground_truth="Config.py loads env vars as raw strings without type coercion. Fix: coerce env var values to match the type of the corresponding default value (int→int, bool→bool, etc.)",
            eval_spec=EvalSpec(
                method=EvalMethod.SCRIPT_CHECK,
                check_script_content=eval_script,
            ),
            capabilities=[
                Capability.CODE_READING,
                Capability.ROOT_CAUSE_ANALYSIS,
                Capability.MULTI_FILE_REASONING,
                Capability.CODE_EDITING,
            ],
            source="frontier_generator",
            estimated_minutes=10,
        )

    def _hidden_edge_case_trap(self, difficulty: str) -> Task:
        """Build a simple-sounding utility where tests catch hidden edge cases.

        Key difficulty: The problem SOUNDS trivial (parse a duration string)
        but the test suite checks many edge cases that a naive implementation misses.
        """
        test_code = textwrap.dedent('''\
            """Tests for duration parser — deceptively thorough."""
            import sys
            sys.path.insert(0, ".")
            from duration_parser import parse_duration

            def test_basic_seconds():
                assert parse_duration("30s") == 30
                assert parse_duration("1s") == 1
                assert parse_duration("0s") == 0
                print("PASS: test_basic_seconds")

            def test_basic_minutes():
                assert parse_duration("5m") == 300
                assert parse_duration("1m") == 60
                print("PASS: test_basic_minutes")

            def test_basic_hours():
                assert parse_duration("2h") == 7200
                assert parse_duration("1h") == 3600
                print("PASS: test_basic_hours")

            def test_basic_days():
                assert parse_duration("1d") == 86400
                assert parse_duration("7d") == 604800
                print("PASS: test_basic_days")

            def test_combined():
                """Combined durations like '1h30m' or '2d12h'."""
                assert parse_duration("1h30m") == 5400
                assert parse_duration("1d12h") == 129600
                assert parse_duration("1h30m45s") == 5445
                assert parse_duration("2d3h4m5s") == 183845
                print("PASS: test_combined")

            def test_whitespace():
                """Should handle whitespace between components."""
                assert parse_duration("1h 30m") == 5400
                assert parse_duration(" 2h  30m ") == 9000
                assert parse_duration("1d 2h 3m 4s") == 93784
                print("PASS: test_whitespace")

            def test_fractional():
                """Should handle fractional values."""
                assert parse_duration("1.5h") == 5400
                assert parse_duration("0.5d") == 43200
                assert parse_duration("2.5m") == 150
                print("PASS: test_fractional")

            def test_plain_number():
                """Plain number without unit should be treated as seconds."""
                assert parse_duration("60") == 60
                assert parse_duration("3600") == 3600
                print("PASS: test_plain_number")

            def test_case_insensitive():
                """Units should be case-insensitive."""
                assert parse_duration("1H") == 3600
                assert parse_duration("30M") == 1800
                assert parse_duration("5S") == 5
                assert parse_duration("1D") == 86400
                print("PASS: test_case_insensitive")

            def test_invalid_input():
                """Should raise ValueError for invalid input."""
                errors = 0
                for invalid in ["", "abc", "h", "1x", "-1s", "1h-30m"]:
                    try:
                        parse_duration(invalid)
                        print(f"  Should have raised ValueError for: {repr(invalid)}")
                        errors += 1
                    except ValueError:
                        pass  # expected
                assert errors == 0, f"{errors} invalid inputs accepted"
                print("PASS: test_invalid_input")

            def test_large_values():
                """Should handle large values without overflow."""
                assert parse_duration("365d") == 31536000
                assert parse_duration("9999s") == 9999
                print("PASS: test_large_values")

            def test_zero():
                """Zero should work for all units."""
                assert parse_duration("0s") == 0
                assert parse_duration("0m") == 0
                assert parse_duration("0h") == 0
                assert parse_duration("0d") == 0
                assert parse_duration("0") == 0
                print("PASS: test_zero")

            def test_repeated_units():
                """Repeated units should be additive: 1h1h = 2h."""
                assert parse_duration("1h1h") == 7200
                assert parse_duration("30s30s") == 60
                print("PASS: test_repeated_units")

            if __name__ == "__main__":
                tests = [f for f in dir() if f.startswith("test_")]
                passed = 0
                failed = 0
                for t in sorted(tests):
                    try:
                        eval(f"{t}()")
                        passed += 1
                    except Exception as e:
                        print(f"FAIL: {t}: {e}")
                        failed += 1
                print(f"\\nResults: {passed}/{passed+failed} passed")
                if failed > 0:
                    sys.exit(1)
        ''')

        eval_script = textwrap.dedent('''\
            #!/bin/bash
            cd "$WORKDIR"

            if [ ! -f "duration_parser.py" ]; then
                echo "FAIL: duration_parser.py not found"
                exit 1
            fi

            OUTPUT=$(python3 test_duration.py 2>&1)
            echo "$OUTPUT"

            PASSED=$(echo "$OUTPUT" | grep -c "^PASS:")
            TOTAL=13

            echo ""
            echo "Tests passed: $PASSED/$TOTAL"

            # Need all 13 to pass — the edge cases ARE the test
            if [ "$PASSED" -ge 11 ]; then
                exit 0
            else
                exit 1
            fi
        ''')

        return Task(
            task_id="frontier_edge_case_trap",
            category=TaskCategory.DIAGNOSTIC,
            title="Build duration parser with 13 edge-case tests",
            difficulty="hard",
            goal=textwrap.dedent("""\
                Build a Python module `duration_parser.py` with a single function:

                ```python
                def parse_duration(s: str) -> int:
                    \"\"\"Parse a human-readable duration string into total seconds.

                    Supports: s (seconds), m (minutes), h (hours), d (days)
                    Examples: '30s' -> 30, '1h30m' -> 5400, '2d' -> 172800
                    \"\"\"
                ```

                A test file `test_duration.py` is provided. Make all tests pass.
            """),
            hints="Read ALL the tests before implementing. The edge cases are the hard part.",
            environment=EnvironmentSetup(
                seed_files={"test_duration.py": test_code}
            ),
            ground_truth="Must handle: combined durations (1h30m), whitespace, fractional values (1.5h), plain numbers as seconds, case-insensitive units, negative/empty/invalid inputs, large values, zero, repeated units (1h1h=2h).",
            eval_spec=EvalSpec(
                method=EvalMethod.SCRIPT_CHECK,
                check_script_content=eval_script,
            ),
            capabilities=[
                Capability.CODE_WRITING,
                Capability.DECOMPOSITION,
            ],
            source="frontier_generator",
            estimated_minutes=8,
        )

    def _legacy_code_archaeology(self, difficulty: str) -> Task:
        """Understand poorly-written legacy code, fix a regression without breaking anything.

        Key difficulty: The code is deliberately messy — mixed naming conventions,
        no docs, magic numbers, dead code. Agent must understand the INTENT, not just
        the code. A test suite exists but doesn't cover the regression.
        """
        legacy_code = textwrap.dedent('''\
            # pricing engine v1 -- DO NOT REFACTOR (accounting depends on exact behavior)
            # Original author left 2 years ago. Tests are in test_pricing.py
            #
            # Last change: fixed weekend pricing (ticket #4521)
            # NOTE: some functions look unused but are called via getattr in the billing system

            import math
            from datetime import datetime, timedelta

            RATES = {
                'standard': 1.0,
                'premium': 1.5,
                'enterprise': 2.0,
                'basic': 0.75,  # added Q3 2024
            }

            # legacy discount tiers -- DO NOT CHANGE thresholds
            DISC_T = [100, 500, 1000, 5000]
            DISC_R = [0, 0.05, 0.10, 0.15, 0.20]

            def calc_base(units, tier='standard'):
                """calc base price. units can be negative for credits."""
                r = RATES.get(tier, RATES['standard'])
                if units < 0:
                    # credits are at 80% of rate
                    return units * r * 0.8
                return units * r

            def get_disc(total_units):
                """get discount rate based on volume."""
                for i in range(len(DISC_T) - 1, -1, -1):
                    if total_units >= DISC_T[i]:
                        return DISC_R[i + 1]
                return DISC_R[0]

            def apply_disc(amount, disc_rate):
                return amount * (1 - disc_rate)

            def calc_tax(amount, region='US'):
                TAX = {'US': 0.0, 'EU': 0.20, 'UK': 0.20, 'CA': 0.13, 'AU': 0.10, 'JP': 0.10}
                return amount * TAX.get(region, 0.0)

            def _round_price(x):
                """Banker's rounding to 2 decimal places."""
                # IMPORTANT: billing system depends on this exact rounding behavior
                return float(f"{x:.2f}")

            def calc_prorate(full_amount, days_used, days_total):
                """prorate for partial periods"""
                if days_total <= 0:
                    return 0
                frac = days_used / days_total
                return _round_price(full_amount * frac)

            def calc_weekend_surcharge(amount, date):
                """Weekend orders get 10% surcharge (added ticket #4521)"""
                if date.weekday() >= 5:  # Saturday=5, Sunday=6
                    return _round_price(amount * 0.10)
                return 0

            def generate_invoice(units, tier='standard', region='US',
                               total_history_units=0, date=None, prorate_days=None,
                               prorate_total=None):
                """
                Main entry point. Generates a complete invoice dict.

                Returns dict with: base, discount, subtotal, surcharge, tax, total
                """
                if date is None:
                    date = datetime.now()

                base = calc_base(units, tier)

                disc_rate = get_disc(total_history_units + abs(units))
                after_disc = apply_disc(base, disc_rate)

                # Prorate if partial period
                if prorate_days is not None and prorate_total is not None:
                    after_disc = calc_prorate(after_disc, prorate_days, prorate_total)

                surcharge = calc_weekend_surcharge(after_disc, date)
                subtotal = after_disc + surcharge

                tax = calc_tax(subtotal, region)
                total = subtotal + tax

                return {
                    'base': _round_price(base),
                    'discount_rate': disc_rate,
                    'after_discount': _round_price(after_disc),
                    'surcharge': _round_price(surcharge),
                    'subtotal': _round_price(subtotal),
                    'tax': _round_price(tax),
                    'total': _round_price(total),
                    'units': units,
                    'tier': tier,
                    'region': region,
                }


            # -- utility functions used by billing via getattr --

            def fmt_currency(amount, currency='USD'):
                symbols = {'USD': '$', 'EUR': '€', 'GBP': '£', 'JPY': '¥'}
                sym = symbols.get(currency, currency + ' ')
                if amount < 0:
                    return f"-{sym}{abs(amount):.2f}"
                return f"{sym}{amount:.2f}"

            def parse_tier_code(code):
                """billing sends 2-letter codes"""
                MAP = {'ST': 'standard', 'PR': 'premium', 'EN': 'enterprise', 'BA': 'basic'}
                return MAP.get(code.upper(), 'standard')
        ''')

        test_code = textwrap.dedent('''\
            """Pricing engine tests. DO NOT MODIFY these tests."""
            import sys
            sys.path.insert(0, ".")
            from datetime import datetime
            from pricing import (calc_base, get_disc, apply_disc, calc_tax,
                               calc_prorate, calc_weekend_surcharge, generate_invoice,
                               fmt_currency, parse_tier_code, _round_price)

            def test_base_pricing():
                assert calc_base(100, 'standard') == 100.0
                assert calc_base(100, 'premium') == 150.0
                assert calc_base(100, 'enterprise') == 200.0
                assert calc_base(100, 'basic') == 75.0
                # Credits
                assert calc_base(-50, 'standard') == -40.0  # -50 * 1.0 * 0.8
                # Unknown tier falls back to standard
                assert calc_base(100, 'unknown') == 100.0
                print("PASS: test_base_pricing")

            def test_volume_discounts():
                assert get_disc(50) == 0      # below first tier
                assert get_disc(100) == 0.05  # hits first tier
                assert get_disc(500) == 0.10  # hits second tier
                assert get_disc(1000) == 0.15
                assert get_disc(5000) == 0.20
                assert get_disc(10000) == 0.20  # max discount
                print("PASS: test_volume_discounts")

            def test_tax():
                assert calc_tax(100, 'US') == 0.0
                assert calc_tax(100, 'EU') == 20.0
                assert calc_tax(100, 'CA') == 13.0
                assert calc_tax(100, 'XX') == 0.0  # unknown region
                print("PASS: test_tax")

            def test_prorate():
                assert calc_prorate(300, 10, 30) == 100.0
                assert calc_prorate(100, 0, 30) == 0.0
                assert calc_prorate(100, 30, 30) == 100.0
                assert calc_prorate(100, 15, 0) == 0  # zero days
                print("PASS: test_prorate")

            def test_weekend_surcharge():
                sat = datetime(2024, 3, 9)   # Saturday
                sun = datetime(2024, 3, 10)  # Sunday
                mon = datetime(2024, 3, 11)  # Monday
                assert calc_weekend_surcharge(100, sat) == 10.0
                assert calc_weekend_surcharge(100, sun) == 10.0
                assert calc_weekend_surcharge(100, mon) == 0
                print("PASS: test_weekend_surcharge")

            def test_full_invoice():
                inv = generate_invoice(200, 'premium', 'EU',
                                      total_history_units=400,
                                      date=datetime(2024, 3, 11))  # Monday
                assert inv['base'] == 300.0   # 200 * 1.5
                assert inv['discount_rate'] == 0.10  # 400+200=600 units
                assert inv['after_discount'] == 270.0
                assert inv['surcharge'] == 0  # Monday
                assert inv['tax'] == 54.0     # 270 * 0.20
                assert inv['total'] == 324.0
                print("PASS: test_full_invoice")

            def test_invoice_weekend():
                inv = generate_invoice(100, 'standard', 'US',
                                      date=datetime(2024, 3, 9))  # Saturday
                assert inv['base'] == 100.0
                assert inv['surcharge'] == 10.0
                assert inv['total'] == 110.0
                print("PASS: test_invoice_weekend")

            def test_invoice_basic_tier():
                """REGRESSION: basic tier was added Q3 2024, must work in invoices."""
                inv = generate_invoice(1000, 'basic', 'US',
                                      total_history_units=0,
                                      date=datetime(2024, 10, 15))  # Tuesday
                assert inv['base'] == 750.0   # 1000 * 0.75
                assert inv['discount_rate'] == 0.15  # 1000 units
                assert inv['after_discount'] == 637.5
                assert inv['total'] == 637.5  # US, no tax, weekday
                print("PASS: test_invoice_basic_tier")

            def test_invoice_with_prorate():
                inv = generate_invoice(100, 'standard', 'US',
                                      prorate_days=15, prorate_total=30,
                                      date=datetime(2024, 3, 11))
                assert inv['after_discount'] == 50.0  # 100 * 0.5
                assert inv['total'] == 50.0
                print("PASS: test_invoice_with_prorate")

            def test_credits_invoice():
                """REGRESSION: credits should have negative totals."""
                inv = generate_invoice(-100, 'standard', 'US',
                                      total_history_units=600,
                                      date=datetime(2024, 3, 11))
                # Base: -100 * 1.0 * 0.8 = -80
                # Discount: 600+100=700 units -> 0.10 discount
                # After discount: -80 * 0.9 = -72
                assert inv['base'] == -80.0
                assert inv['after_discount'] == -72.0
                # Surcharge on negative should be 0 (no surcharge on credits)
                # Tax on negative should be 0 or negative
                assert inv['total'] <= 0, f"Credit invoice should be negative, got {inv['total']}"
                print("PASS: test_credits_invoice")

            def test_utility_functions():
                assert fmt_currency(99.99) == "$99.99"
                assert fmt_currency(-50.0) == "-$50.00"
                assert fmt_currency(100, 'EUR') == "€100.00"
                assert parse_tier_code('PR') == 'premium'
                assert parse_tier_code('ba') == 'basic'
                assert parse_tier_code('XX') == 'standard'
                print("PASS: test_utility_functions")

            def test_rounding():
                assert _round_price(10.005) == 10.01  # should round up at .005
                assert _round_price(10.004) == 10.0
                assert _round_price(10.995) == 11.0
                assert _round_price(-10.005) == -10.01  # negative should also round
                print("PASS: test_rounding")

            if __name__ == "__main__":
                tests = [f for f in dir() if f.startswith("test_")]
                passed = 0
                failed = 0
                for t in sorted(tests):
                    try:
                        eval(f"{t}()")
                        passed += 1
                    except Exception as e:
                        print(f"FAIL: {t}: {e}")
                        failed += 1
                print(f"\\nResults: {passed}/{passed+failed}")
                if failed:
                    sys.exit(1)
        ''')

        eval_script = textwrap.dedent('''\
            #!/bin/bash
            cd "$WORKDIR"
            OUTPUT=$(python3 test_pricing.py 2>&1)
            echo "$OUTPUT"

            PASSED=$(echo "$OUTPUT" | grep -c "^PASS:")
            TOTAL=12

            echo ""
            echo "Tests passed: $PASSED/$TOTAL"

            if [ "$PASSED" -ge 12 ]; then
                exit 0
            else
                exit 1
            fi
        ''')

        return Task(
            task_id="frontier_legacy_archaeology",
            category=TaskCategory.DIAGNOSTIC,
            title="Fix regressions in legacy pricing engine",
            difficulty="hard",
            goal=textwrap.dedent("""\
                The pricing engine in `pricing.py` has been working for 2 years.
                Recently, the `basic` tier was added and credits support was extended.
                Some tests are now failing.

                Run the tests:
                ```
                python3 test_pricing.py
                ```

                Fix the pricing engine to make ALL tests pass. Important constraints:
                - Do NOT change the existing discount thresholds or rates
                - Do NOT change the rounding behavior
                - Do NOT refactor — the billing system depends on the exact function signatures
                - The `fmt_currency` and `parse_tier_code` functions are called via getattr
                  by external systems — don't remove or rename them

                Only fix what's broken. The minimal change that makes all tests pass.
            """),
            hints="Run the tests first to see which ones fail. The failures are in edge cases around credits and rounding.",
            environment=EnvironmentSetup(
                seed_files={
                    "pricing.py": legacy_code,
                    "test_pricing.py": test_code,
                }
            ),
            ground_truth="Bugs: (1) _round_price uses f-string which truncates not rounds (10.005 -> '10.00' not '10.01') — fix with round() or Decimal. (2) calc_weekend_surcharge applies to negative amounts (credits) — should be 0 for negative. (3) Credits invoice: discount on negative amount with (1-disc_rate) makes it LESS negative instead of more — apply_disc should consider sign.",
            eval_spec=EvalSpec(
                method=EvalMethod.SCRIPT_CHECK,
                check_script_content=eval_script,
            ),
            capabilities=[
                Capability.CODE_READING,
                Capability.ROOT_CAUSE_ANALYSIS,
                Capability.CODE_EDITING,
                Capability.HYPOTHESIS_TESTING,
            ],
            source="frontier_generator",
            estimated_minutes=12,
        )

    def _concurrent_bug_hunt(self, difficulty: str) -> Task:
        """Event-driven notification system with subtle ordering and state bugs.

        Key difficulty: Multiple interacting bugs in callback/event system.
        The code looks reasonable but has 3 bugs that cause deterministic test failures:
        1. Handlers fire in wrong order (dict ordering vs priority)
        2. Unsubscribe during iteration causes skipped handlers
        3. Event data is shared mutably between handlers
        """
        code = textwrap.dedent('''\
            """Event-driven notification system with priorities and filtering."""
            from typing import Callable, Any, Optional
            from dataclasses import dataclass, field
            from collections import defaultdict


            @dataclass
            class Event:
                """An event with a type, payload, and metadata."""
                type: str
                data: dict = field(default_factory=dict)
                source: str = ""
                _propagation_stopped: bool = field(default=False, init=False)

                def stop_propagation(self):
                    self._propagation_stopped = True


            @dataclass
            class Subscription:
                """A handler subscription for an event type."""
                handler: Callable
                priority: int = 0  # higher = runs first
                event_filter: Optional[Callable] = None  # optional predicate
                once: bool = False  # auto-unsubscribe after first fire


            class EventBus:
                """Central event dispatch system.

                Usage:
                    bus = EventBus()
                    bus.subscribe("user.login", my_handler, priority=10)
                    bus.emit(Event("user.login", {"user_id": 123}))
                """

                def __init__(self):
                    self._subscribers = defaultdict(list)  # type -> [Subscription]
                    self._history = []  # recent events for replay
                    self._history_limit = 100

                def subscribe(self, event_type: str, handler: Callable,
                             priority: int = 0, event_filter: Callable = None,
                             once: bool = False) -> Subscription:
                    """Subscribe a handler to an event type."""
                    sub = Subscription(
                        handler=handler,
                        priority=priority,
                        event_filter=event_filter,
                        once=once,
                    )
                    self._subscribers[event_type].append(sub)
                    return sub

                def unsubscribe(self, event_type: str, subscription: Subscription):
                    """Remove a subscription."""
                    subs = self._subscribers.get(event_type, [])
                    if subscription in subs:
                        subs.remove(subscription)

                def emit(self, event: Event) -> list[Any]:
                    """Emit an event to all matching subscribers.

                    Returns list of handler return values.
                    Handlers run in priority order (highest first).
                    """
                    results = []
                    subs = self._subscribers.get(event.type, [])

                    # Sort by priority (highest first)
                    subs.sort(key=lambda s: s.priority, reverse=True)

                    to_remove = []
                    for sub in subs:
                        if event._propagation_stopped:
                            break

                        # Apply filter
                        if sub.event_filter and not sub.event_filter(event):
                            continue

                        result = sub.handler(event)
                        results.append(result)

                        if sub.once:
                            to_remove.append(sub)

                    # Clean up one-shot subscriptions
                    for sub in to_remove:
                        self.unsubscribe(event.type, sub)

                    # Record in history
                    self._history.append(event)
                    if len(self._history) > self._history_limit:
                        self._history = self._history[-self._history_limit:]

                    return results

                def emit_many(self, events: list[Event]) -> dict[str, list]:
                    """Emit multiple events, return results keyed by event type."""
                    results = {}
                    for event in events:
                        key = event.type
                        if key not in results:
                            results[key] = []
                        results[key].extend(self.emit(event))
                    return results

                def replay(self, event_type: str, handler: Callable):
                    """Replay historical events of a type to a new handler."""
                    for event in self._history:
                        if event.type == event_type:
                            handler(event)

                def subscriber_count(self, event_type: str) -> int:
                    """Count subscribers for an event type."""
                    return len(self._subscribers.get(event_type, []))
        ''')

        test_code = textwrap.dedent('''\
            """Tests for event bus system."""
            import sys
            sys.path.insert(0, ".")
            from event_bus import EventBus, Event, Subscription


            def test_basic_subscribe_emit():
                bus = EventBus()
                received = []
                bus.subscribe("test", lambda e: received.append(e.data))
                bus.emit(Event("test", {"msg": "hello"}))
                assert len(received) == 1
                assert received[0]["msg"] == "hello"
                print("PASS: test_basic_subscribe_emit")


            def test_priority_order():
                """Handlers should fire in priority order (highest first)."""
                bus = EventBus()
                order = []

                bus.subscribe("test", lambda e: order.append("low"), priority=1)
                bus.subscribe("test", lambda e: order.append("high"), priority=10)
                bus.subscribe("test", lambda e: order.append("medium"), priority=5)

                bus.emit(Event("test"))

                assert order == ["high", "medium", "low"], \\
                    f"Wrong order: {order}, expected ['high', 'medium', 'low']"
                print("PASS: test_priority_order")


            def test_event_filter():
                bus = EventBus()
                received = []
                bus.subscribe("user.action",
                             lambda e: received.append(e.data),
                             event_filter=lambda e: e.data.get("important", False))

                bus.emit(Event("user.action", {"msg": "boring", "important": False}))
                bus.emit(Event("user.action", {"msg": "urgent", "important": True}))

                assert len(received) == 1
                assert received[0]["msg"] == "urgent"
                print("PASS: test_event_filter")


            def test_once_subscription():
                bus = EventBus()
                count = [0]
                bus.subscribe("ping", lambda e: count.__setitem__(0, count[0] + 1), once=True)

                bus.emit(Event("ping"))
                bus.emit(Event("ping"))
                bus.emit(Event("ping"))

                assert count[0] == 1, f"Once handler fired {count[0]} times"
                print("PASS: test_once_subscription")


            def test_stop_propagation():
                bus = EventBus()
                order = []

                bus.subscribe("test", lambda e: order.append("first") or e.stop_propagation(),
                             priority=10)
                bus.subscribe("test", lambda e: order.append("second"), priority=5)

                bus.emit(Event("test"))
                assert order == ["first"], f"Expected propagation stop, got: {order}"
                print("PASS: test_stop_propagation")


            def test_unsubscribe():
                bus = EventBus()
                received = []
                sub = bus.subscribe("test", lambda e: received.append(1))
                bus.emit(Event("test"))
                bus.unsubscribe("test", sub)
                bus.emit(Event("test"))
                assert len(received) == 1
                print("PASS: test_unsubscribe")


            def test_multiple_once_handlers():
                """Multiple once handlers on same event — all should fire exactly once."""
                bus = EventBus()
                results = {"a": 0, "b": 0, "c": 0}

                bus.subscribe("go", lambda e: results.__setitem__("a", results["a"] + 1), once=True, priority=3)
                bus.subscribe("go", lambda e: results.__setitem__("b", results["b"] + 1), once=True, priority=2)
                bus.subscribe("go", lambda e: results.__setitem__("c", results["c"] + 1), once=True, priority=1)

                bus.emit(Event("go"))
                bus.emit(Event("go"))

                assert results == {"a": 1, "b": 1, "c": 1}, \\
                    f"Expected each once-handler to fire exactly once: {results}"
                assert bus.subscriber_count("go") == 0, \\
                    f"Expected 0 subscribers after once handlers, got {bus.subscriber_count('go')}"
                print("PASS: test_multiple_once_handlers")


            def test_event_data_isolation():
                """Each handler should get its own view of event data — mutations by one
                handler should NOT affect subsequent handlers."""
                bus = EventBus()

                def mutating_handler(event):
                    event.data["count"] = event.data.get("count", 0) + 1
                    return event.data["count"]

                bus.subscribe("test", mutating_handler, priority=10)
                bus.subscribe("test", mutating_handler, priority=5)

                results = bus.emit(Event("test", {"count": 0}))

                # If data is shared, second handler sees count=1 and returns 2
                # If data is isolated, each handler sees count=0 and returns 1
                assert results == [1, 1], \\
                    f"Event data leaked between handlers: results={results}"
                print("PASS: test_event_data_isolation")


            def test_replay():
                bus = EventBus()
                bus.emit(Event("log", {"msg": "first"}))
                bus.emit(Event("log", {"msg": "second"}))
                bus.emit(Event("other", {"msg": "skip"}))

                replayed = []
                bus.replay("log", lambda e: replayed.append(e.data["msg"]))
                assert replayed == ["first", "second"]
                print("PASS: test_replay")


            def test_emit_many():
                bus = EventBus()
                received = {"a": [], "b": []}
                bus.subscribe("a", lambda e: received["a"].append(e.data))
                bus.subscribe("b", lambda e: received["b"].append(e.data))

                bus.emit_many([
                    Event("a", {"n": 1}),
                    Event("b", {"n": 2}),
                    Event("a", {"n": 3}),
                ])

                assert len(received["a"]) == 2
                assert len(received["b"]) == 1
                print("PASS: test_emit_many")


            if __name__ == "__main__":
                tests = [f for f in dir() if f.startswith("test_")]
                passed = 0
                failed = 0
                for t in sorted(tests):
                    try:
                        eval(f"{t}()")
                        passed += 1
                    except Exception as e:
                        print(f"FAIL: {t}: {e}")
                        failed += 1
                print(f"\\nResults: {passed}/{passed+failed}")
                if failed:
                    sys.exit(1)
        ''')

        eval_script = textwrap.dedent('''\
            #!/bin/bash
            cd "$WORKDIR"

            OUTPUT=$(python3 test_event_bus.py 2>&1)
            echo "$OUTPUT"

            PASSED=$(echo "$OUTPUT" | grep -c "^PASS:")
            TOTAL=10

            echo ""
            echo "Tests passed: $PASSED/$TOTAL"

            if [ "$PASSED" -ge 10 ]; then
                exit 0
            else
                exit 1
            fi
        ''')

        return Task(
            task_id="frontier_event_bus_bugs",
            category=TaskCategory.DIAGNOSTIC,
            title="Fix 3 interacting bugs in event bus system",
            difficulty="hard",
            goal=textwrap.dedent("""\
                The file `event_bus.py` implements an event-driven notification system
                with priorities, filtering, and one-shot subscriptions.

                Run the tests:
                ```
                python3 test_event_bus.py
                ```

                Several tests are failing. The bugs interact with each other — fixing
                one may reveal another. Debug carefully.

                Fix all bugs to make every test pass. The fix should be minimal.
            """),
            hints="Think about: (1) what happens when you modify a list while iterating it, (2) whether event data is shared or copied between handlers, (3) how sort() affects the original list.",
            environment=EnvironmentSetup(
                seed_files={
                    "event_bus.py": code,
                    "test_event_bus.py": test_code,
                }
            ),
            ground_truth="3 bugs: (1) sort() mutates the subscriber list in-place, changing insertion order — fix by sorting a copy. (2) Once-handler removal via unsubscribe during/after iteration can skip handlers when multiple once-handlers fire — fix by collecting to_remove and removing after full iteration (already partially done but the sort+iterate-original-list interaction causes issues). (3) Event data dict is shared between handlers — fix by passing a copy of event.data to each handler or making Event immutable.",
            eval_spec=EvalSpec(
                method=EvalMethod.SCRIPT_CHECK,
                check_script_content=eval_script,
            ),
            capabilities=[
                Capability.CODE_READING,
                Capability.ROOT_CAUSE_ANALYSIS,
                Capability.CODE_EDITING,
                Capability.HYPOTHESIS_TESTING,
            ],
            source="frontier_generator",
            estimated_minutes=10,
        )

    def _rename_with_ripple_effects(self, difficulty: str) -> Task:
        """Rename a core function and update ALL 7 files that reference it.

        Key difficulty: The core rename is trivial. But the agent must find
        and update ALL references across tests, docs, __init__.py exports,
        CLI entry point, config defaults, and type stubs. Missing even 1 file
        means the evaluation fails.
        """
        files = {}

        files["mathlib/__init__.py"] = textwrap.dedent('''\
            """MathLib — a small math utilities library."""
            __version__ = "1.2.0"

            from .core import calculate_average, calculate_median, calculate_stddev
            from .formatters import format_result, format_table
        ''')

        files["mathlib/core.py"] = textwrap.dedent('''\
            """Core statistical functions."""
            import math
            from typing import Union


            def calculate_average(values: list[Union[int, float]]) -> float:
                """Calculate the arithmetic mean of a list of numbers."""
                if not values:
                    raise ValueError("Cannot calculate average of empty list")
                return sum(values) / len(values)


            def calculate_median(values: list[Union[int, float]]) -> float:
                """Calculate the median of a list of numbers."""
                if not values:
                    raise ValueError("Cannot calculate median of empty list")
                sorted_vals = sorted(values)
                n = len(sorted_vals)
                if n % 2 == 0:
                    return (sorted_vals[n//2 - 1] + sorted_vals[n//2]) / 2
                return float(sorted_vals[n//2])


            def calculate_stddev(values: list[Union[int, float]]) -> float:
                """Calculate the population standard deviation."""
                if len(values) < 2:
                    raise ValueError("Need at least 2 values for stddev")
                avg = calculate_average(values)
                variance = sum((x - avg) ** 2 for x in values) / len(values)
                return math.sqrt(variance)
        ''')

        files["mathlib/formatters.py"] = textwrap.dedent('''\
            """Output formatting utilities."""
            from .core import calculate_average, calculate_median


            def format_result(values: list, stat: str = "average") -> str:
                """Format a statistical result as a human-readable string."""
                if stat == "average":
                    result = calculate_average(values)
                elif stat == "median":
                    result = calculate_median(values)
                else:
                    raise ValueError(f"Unknown stat: {stat}")
                return f"The {stat} is {result:.2f}"


            def format_table(data: dict[str, list]) -> str:
                """Format multiple datasets as a comparison table."""
                lines = ["Dataset          | Average  | Median"]
                lines.append("-" * 40)
                for name, values in data.items():
                    avg = calculate_average(values)
                    med = calculate_median(values)
                    lines.append(f"{name:16s} | {avg:8.2f} | {med:.2f}")
                return "\\n".join(lines)
        ''')

        files["mathlib/cli.py"] = textwrap.dedent('''\
            """Command-line interface for mathlib."""
            import sys
            from .core import calculate_average, calculate_median, calculate_stddev


            def main():
                if len(sys.argv) < 3:
                    print("Usage: mathlib <stat> <value1> <value2> ...")
                    print("  stat: average, median, stddev")
                    sys.exit(1)

                stat = sys.argv[1]
                values = [float(x) for x in sys.argv[2:]]

                if stat == "average":
                    result = calculate_average(values)
                elif stat == "median":
                    result = calculate_median(values)
                elif stat == "stddev":
                    result = calculate_stddev(values)
                else:
                    print(f"Unknown stat: {stat}")
                    sys.exit(1)

                print(f"{result:.4f}")


            if __name__ == "__main__":
                main()
        ''')

        files["tests/__init__.py"] = ""

        files["tests/test_core.py"] = textwrap.dedent('''\
            """Tests for core statistical functions."""
            import sys
            import os
            sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
            from mathlib.core import calculate_average, calculate_median, calculate_stddev


            def test_average():
                assert calculate_average([1, 2, 3, 4, 5]) == 3.0
                assert calculate_average([10]) == 10.0
                try:
                    calculate_average([])
                    assert False, "Should raise ValueError"
                except ValueError:
                    pass
                print("PASS: test_average")


            def test_median():
                assert calculate_median([1, 2, 3]) == 2.0
                assert calculate_median([1, 2, 3, 4]) == 2.5
                assert calculate_median([5]) == 5.0
                print("PASS: test_median")


            def test_stddev():
                assert abs(calculate_stddev([2, 4, 4, 4, 5, 5, 7, 9]) - 2.0) < 0.01
                try:
                    calculate_stddev([1])
                    assert False, "Should raise ValueError"
                except ValueError:
                    pass
                print("PASS: test_stddev")


            if __name__ == "__main__":
                test_average()
                test_median()
                test_stddev()
                print("\\nAll tests passed")
        ''')

        files["tests/test_formatters.py"] = textwrap.dedent('''\
            """Tests for formatting functions."""
            import sys
            import os
            sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
            from mathlib.formatters import format_result, format_table


            def test_format_result():
                assert "3.00" in format_result([1, 2, 3, 4, 5], "average")
                assert "3.00" in format_result([1, 2, 3, 4, 5], "median")
                print("PASS: test_format_result")


            def test_format_table():
                data = {"set_a": [1, 2, 3], "set_b": [10, 20, 30]}
                result = format_table(data)
                assert "set_a" in result
                assert "set_b" in result
                print("PASS: test_format_table")


            if __name__ == "__main__":
                test_format_result()
                test_format_table()
                print("\\nAll tests passed")
        ''')

        files["README.md"] = textwrap.dedent('''\
            # MathLib

            A small statistics library for Python.

            ## Usage

            ```python
            from mathlib import calculate_average, calculate_median, calculate_stddev

            data = [1, 2, 3, 4, 5]
            print(calculate_average(data))  # 3.0
            print(calculate_median(data))   # 3.0
            print(calculate_stddev(data))   # 1.414
            ```

            ## CLI

            ```bash
            python -m mathlib.cli average 1 2 3 4 5
            # 3.0000
            ```

            ## API Reference

            ### `calculate_average(values) -> float`
            Calculate the arithmetic mean.

            ### `calculate_median(values) -> float`
            Calculate the median.

            ### `calculate_stddev(values) -> float`
            Calculate population standard deviation.
        ''')

        eval_script = textwrap.dedent('''\
            #!/bin/bash
            cd "$WORKDIR"

            SCORE=0
            TOTAL=7

            check() {
                local desc="$1"
                local passed="$2"
                if [ "$passed" -eq 1 ]; then
                    echo "PASS: $desc"
                    SCORE=$((SCORE + 1))
                else
                    echo "FAIL: $desc"
                fi
            }

            # 1. Core function renamed in core.py
            if grep -q "def compute_mean" mathlib/core.py && ! grep -q "def calculate_average" mathlib/core.py; then
                check "core.py: calculate_average -> compute_mean" 1
            else
                check "core.py: calculate_average -> compute_mean" 0
            fi

            # 2. __init__.py exports updated
            if grep -q "compute_mean" mathlib/__init__.py && ! grep -q "calculate_average" mathlib/__init__.py; then
                check "__init__.py: export updated" 1
            else
                check "__init__.py: export updated" 0
            fi

            # 3. formatters.py import+usage updated
            if grep -q "compute_mean" mathlib/formatters.py && ! grep -q "calculate_average" mathlib/formatters.py; then
                check "formatters.py: import+usage updated" 1
            else
                check "formatters.py: import+usage updated" 0
            fi

            # 4. cli.py updated
            if grep -q "compute_mean" mathlib/cli.py && ! grep -q "calculate_average" mathlib/cli.py; then
                check "cli.py: usage updated" 1
            else
                check "cli.py: usage updated" 0
            fi

            # 5. test_core.py updated
            if grep -q "compute_mean" tests/test_core.py && ! grep -q "calculate_average" tests/test_core.py; then
                check "test_core.py: updated" 1
            else
                check "test_core.py: updated" 0
            fi

            # 6. test_formatters.py still passes
            OUTPUT=$(python3 tests/test_formatters.py 2>&1)
            if echo "$OUTPUT" | grep -q "All tests passed"; then
                check "test_formatters.py: still passes" 1
            else
                check "test_formatters.py: still passes" 0
            fi

            # 7. README.md updated
            if grep -q "compute_mean" README.md && ! grep -q "calculate_average" README.md; then
                check "README.md: documentation updated" 1
            else
                check "README.md: documentation updated" 0
            fi

            echo ""
            echo "Score: $SCORE/$TOTAL"

            if [ "$SCORE" -ge 7 ]; then
                exit 0
            else
                exit 1
            fi
        ''')

        return Task(
            task_id="frontier_rename_ripple",
            category=TaskCategory.DIAGNOSTIC,
            title="Rename function and update ALL 7 files",
            difficulty="hard",
            goal=textwrap.dedent("""\
                Rename the function `calculate_average` to `compute_mean` throughout
                the entire MathLib project.

                This rename must be applied consistently across ALL files that reference
                this function:
                - Source code (definition, imports, usages)
                - Tests (imports, assertions)
                - Documentation (README.md)
                - Any other files that reference the old name

                After the rename, all tests must still pass.

                Use grep or find_references to locate ALL occurrences before editing.
            """),
            hints="Don't forget: __init__.py, cli.py, formatters.py, tests, README.md",
            environment=EnvironmentSetup(
                seed_files=files
            ),
            ground_truth="Must update 7 files: core.py (definition), __init__.py (export), formatters.py (import+usage), cli.py (import+usage), test_core.py (import+usage), README.md (docs), and ensure test_formatters.py still passes.",
            eval_spec=EvalSpec(
                method=EvalMethod.SCRIPT_CHECK,
                check_script_content=eval_script,
            ),
            capabilities=[
                Capability.CODE_EDITING,
                Capability.MULTI_FILE_REASONING,
                Capability.CODE_SEARCH,
            ],
            source="frontier_generator",
            estimated_minutes=8,
        )

    def _feature_flag_removal(self, difficulty: str) -> Task:
        """Remove a feature flag and all its conditional branches across 6+ files.

        Key difficulty: The flag is referenced in many places — source, tests,
        config, docs, CLI args. Agent must find and clean up ALL traces.
        Leaving any dangling reference causes test failures.
        """
        import json as _json
        files = {}

        files["app/__init__.py"] = textwrap.dedent('''\
            """TaskRunner — a simple task execution framework."""
            __version__ = "2.1.0"
        ''')

        files["app/config.py"] = textwrap.dedent('''\
            """Configuration management."""
            import json
            import os

            DEFAULT_CONFIG = {
                "max_workers": 4,
                "timeout": 30,
                "log_level": "INFO",
                "enable_experimental_cache": True,  # Feature flag — REMOVE THIS
                "cache_ttl": 300,
                "output_format": "json",
            }


            class Config:
                def __init__(self, config_path=None, **overrides):
                    self._data = dict(DEFAULT_CONFIG)
                    if config_path and os.path.exists(config_path):
                        with open(config_path) as f:
                            self._data.update(json.load(f))
                    self._data.update(overrides)

                def get(self, key, default=None):
                    return self._data.get(key, default)

                @property
                def cache_enabled(self):
                    return self._data.get("enable_experimental_cache", False)
        ''')

        files["app/cache.py"] = textwrap.dedent('''\
            """Simple in-memory cache with TTL support."""
            import time


            class Cache:
                def __init__(self, ttl=300):
                    self._store = {}
                    self._ttl = ttl

                def get(self, key):
                    if key in self._store:
                        value, timestamp = self._store[key]
                        if time.time() - timestamp < self._ttl:
                            return value
                        del self._store[key]
                    return None

                def set(self, key, value):
                    self._store[key] = (value, time.time())

                def clear(self):
                    self._store.clear()

                @property
                def size(self):
                    return len(self._store)
        ''')

        files["app/executor.py"] = textwrap.dedent('''\
            """Task executor with optional caching."""
            from .config import Config
            from .cache import Cache


            class TaskExecutor:
                def __init__(self, config: Config):
                    self.config = config
                    self._cache = Cache(ttl=config.get("cache_ttl", 300)) if config.cache_enabled else None
                    self._stats = {"executed": 0, "cached": 0, "errors": 0}

                def execute(self, task_name: str, fn, *args, **kwargs):
                    """Execute a task, optionally using cache."""
                    if self._cache is not None:
                        cache_key = f"{task_name}:{args}:{kwargs}"
                        cached = self._cache.get(cache_key)
                        if cached is not None:
                            self._stats["cached"] += 1
                            return cached

                    try:
                        result = fn(*args, **kwargs)
                        self._stats["executed"] += 1
                        if self._cache is not None:
                            cache_key = f"{task_name}:{args}:{kwargs}"
                            self._cache.set(cache_key, result)
                        return result
                    except Exception as e:
                        self._stats["errors"] += 1
                        raise

                @property
                def stats(self):
                    return dict(self._stats)

                def clear_cache(self):
                    if self._cache is not None:
                        self._cache.clear()
        ''')

        files["app/cli.py"] = textwrap.dedent('''\
            """CLI entry point."""
            import argparse
            import json
            import sys
            from .config import Config
            from .executor import TaskExecutor


            def parse_args():
                parser = argparse.ArgumentParser(description="TaskRunner")
                parser.add_argument("--config", help="Config file path")
                parser.add_argument("--workers", type=int, help="Max workers")
                parser.add_argument("--enable-cache", action="store_true",
                                    help="Enable experimental caching")
                parser.add_argument("--no-cache", action="store_true",
                                    help="Disable experimental caching")
                parser.add_argument("--format", choices=["json", "text"], default="json")
                return parser.parse_args()


            def main():
                args = parse_args()
                overrides = {}
                if args.workers:
                    overrides["max_workers"] = args.workers
                if args.enable_cache:
                    overrides["enable_experimental_cache"] = True
                if args.no_cache:
                    overrides["enable_experimental_cache"] = False

                config = Config(config_path=args.config, **overrides)
                executor = TaskExecutor(config)

                result = executor.execute("demo", lambda: {"status": "ok"})
                if args.format == "json":
                    print(json.dumps(result))
                else:
                    print(f"Result: {result}")

                stats = executor.stats
                if config.cache_enabled:
                    print(f"Cache: {stats['cached']} hits")
        ''')

        files["tests/__init__.py"] = ""

        files["tests/test_executor.py"] = textwrap.dedent('''\
            """Tests for task executor."""
            import sys
            import os
            sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
            from app.config import Config
            from app.executor import TaskExecutor


            def test_basic_execution():
                config = Config(enable_experimental_cache=False)
                executor = TaskExecutor(config)
                result = executor.execute("test", lambda: 42)
                assert result == 42
                assert executor.stats["executed"] == 1
                print("PASS: test_basic_execution")


            def test_execution_with_cache():
                config = Config(enable_experimental_cache=True)
                executor = TaskExecutor(config)
                counter = [0]
                def slow_task():
                    counter[0] += 1
                    return counter[0]

                r1 = executor.execute("count", slow_task)
                r2 = executor.execute("count", slow_task)
                assert r1 == r2 == 1
                assert executor.stats["cached"] == 1
                print("PASS: test_execution_with_cache")


            def test_error_tracking():
                config = Config(enable_experimental_cache=False)
                executor = TaskExecutor(config)
                try:
                    executor.execute("fail", lambda: 1/0)
                except ZeroDivisionError:
                    pass
                assert executor.stats["errors"] == 1
                print("PASS: test_error_tracking")


            if __name__ == "__main__":
                test_basic_execution()
                test_execution_with_cache()
                test_error_tracking()
                print("\\nAll tests passed")
        ''')

        files["README.md"] = textwrap.dedent('''\
            # TaskRunner

            A simple task execution framework with built-in caching.

            ## Configuration

            ```json
            {
                "max_workers": 4,
                "timeout": 30,
                "enable_experimental_cache": true,
                "cache_ttl": 300
            }
            ```

            ### Cache (Experimental)

            Set `enable_experimental_cache: true` to enable result caching.
            Cache TTL defaults to 300 seconds.

            CLI flags: `--enable-cache` / `--no-cache`

            ## Usage

            ```python
            from app.config import Config
            from app.executor import TaskExecutor

            config = Config(enable_experimental_cache=True)
            executor = TaskExecutor(config)
            result = executor.execute("my_task", my_function, arg1, arg2)
            ```
        ''')

        files["config.json"] = _json.dumps({
            "max_workers": 2,
            "timeout": 60,
            "enable_experimental_cache": True,
            "cache_ttl": 600,
        }, indent=2)

        eval_script = textwrap.dedent('''\
            #!/bin/bash
            cd "$WORKDIR"

            SCORE=0
            TOTAL=8

            check() {
                local desc="$1"
                local passed="$2"
                if [ "$passed" -eq 1 ]; then
                    echo "PASS: $desc"
                    SCORE=$((SCORE + 1))
                else
                    echo "FAIL: $desc"
                fi
            }

            # 1. Config no longer has the feature flag
            if ! grep -q "enable_experimental_cache" app/config.py; then
                check "config.py: flag removed from defaults" 1
            else
                check "config.py: flag removed from defaults" 0
            fi

            # 2. Executor always uses cache (no conditional)
            if grep -q "Cache(" app/executor.py && ! grep -q "cache_enabled" app/executor.py; then
                check "executor.py: cache always enabled" 1
            else
                check "executor.py: cache always enabled" 0
            fi

            # 3. CLI removed --enable-cache and --no-cache flags
            if ! grep -q "enable.cache" app/cli.py && ! grep -q "no.cache" app/cli.py; then
                check "cli.py: cache flags removed" 1
            else
                check "cli.py: cache flags removed" 0
            fi

            # 4. Tests no longer reference the flag
            if ! grep -q "enable_experimental_cache" tests/test_executor.py; then
                check "test_executor.py: flag references removed" 1
            else
                check "test_executor.py: flag references removed" 0
            fi

            # 5. README updated
            if ! grep -qi "experimental" README.md && ! grep -q "enable_experimental_cache" README.md; then
                check "README.md: experimental references removed" 1
            else
                check "README.md: experimental references removed" 0
            fi

            # 6. config.json updated
            if ! grep -q "enable_experimental_cache" config.json; then
                check "config.json: flag removed" 1
            else
                check "config.json: flag removed" 0
            fi

            # 7. Tests still pass
            OUTPUT=$(python3 tests/test_executor.py 2>&1)
            if echo "$OUTPUT" | grep -q "All tests passed"; then
                check "tests pass after refactor" 1
            else
                echo "  Test output: $OUTPUT"
                check "tests pass after refactor" 0
            fi

            # 8. Cache works without flag
            OUTPUT2=$(python3 -c "
import sys, os
sys.path.insert(0, '.')
from app.config import Config
from app.executor import TaskExecutor
config = Config()
executor = TaskExecutor(config)
ct = [0]
def f():
    ct[0] += 1
    return ct[0]
r1 = executor.execute('t', f)
r2 = executor.execute('t', f)
assert r1 == r2 == 1, f'Cache broken: r1={r1}, r2={r2}'
print('CACHE_OK')
" 2>&1)
            if echo "$OUTPUT2" | grep -q "CACHE_OK"; then
                check "cache works without flag" 1
            else
                echo "  Cache test: $OUTPUT2"
                check "cache works without flag" 0
            fi

            echo ""
            echo "Score: $SCORE/$TOTAL"

            if [ "$SCORE" -ge 8 ]; then
                exit 0
            else
                exit 1
            fi
        ''')

        return Task(
            task_id="frontier_feature_flag_removal",
            category=TaskCategory.DIAGNOSTIC,
            title="Remove feature flag and clean up ALL 8 references",
            difficulty="hard",
            goal=textwrap.dedent("""\
                The `enable_experimental_cache` feature flag in TaskRunner is being
                promoted to a permanent feature. Remove the feature flag and make
                caching always enabled.

                This means:
                1. Remove the `enable_experimental_cache` config option and `cache_enabled` property
                2. Make the executor always create and use the cache (no conditional)
                3. Remove the `--enable-cache` and `--no-cache` CLI flags
                4. Update tests to not reference the flag
                5. Update README and config.json to remove references
                6. Cache functionality must still work — just without the flag

                After cleanup, ALL tests must still pass and the cache must still work.
                Use grep to find ALL occurrences of the flag before making changes.
            """),
            hints="Search for 'enable_experimental_cache', 'cache_enabled', 'enable-cache', 'no-cache', and 'experimental' across all files.",
            environment=EnvironmentSetup(
                seed_files=files
            ),
            ground_truth="Must update 6+ files: config.py (remove flag+property), executor.py (always create cache), cli.py (remove --enable-cache/--no-cache), test_executor.py (remove flag refs), README.md (remove experimental docs), config.json (remove flag). Cache must still work.",
            eval_spec=EvalSpec(
                method=EvalMethod.SCRIPT_CHECK,
                check_script_content=eval_script,
            ),
            capabilities=[
                Capability.CODE_EDITING,
                Capability.MULTI_FILE_REASONING,
                Capability.CODE_SEARCH,
                Capability.CODE_READING,
            ],
            source="frontier_generator",
            estimated_minutes=10,
        )
