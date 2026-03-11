"""
Multi-step planning task generator.

Generates tasks requiring long-horizon planning, multiple sequential operations,
and careful coordination of steps. Tests decomposition, prioritization, and
end-to-end execution across multiple tools and files.
"""

import textwrap
from ..schema import (
    Task, TaskCategory, Capability, EvalMethod,
    EnvironmentSetup, EvalSpec
)
from .base import TaskGenerator


class MultiStepGenerator(TaskGenerator):
    """Generates multi-step planning and execution tasks."""

    @property
    def category(self) -> TaskCategory:
        return TaskCategory.MULTI_STEP

    def generate(self, count: int = 5, difficulty: str = "medium") -> list[Task]:
        generators = [
            self._project_bootstrap,
            self._migration_pipeline,
            self._test_infrastructure,
            self._api_with_tests,
            self._refactor_and_verify,
            self._build_and_deploy_setup,
        ]
        tasks = []
        for i in range(count):
            gen = generators[i % len(generators)]
            tasks.append(gen(difficulty))
        return tasks

    def _project_bootstrap(self, difficulty: str) -> Task:
        """Task: bootstrap a complete project from a spec document."""
        return Task(
            category=TaskCategory.MULTI_STEP,
            title="Bootstrap Python CLI tool from specification",
            difficulty=difficulty,
            goal=textwrap.dedent("""\
                Read the spec.md file. It describes a CLI tool called "taskr" for managing
                a JSON-based todo list. Implement it completely:

                1. Read and understand the full spec
                2. Create the project structure
                3. Implement the CLI with all commands
                4. Write the data persistence layer
                5. Add input validation
                6. Verify each command works

                The tool must pass all the test scenarios described in the spec.
            """),
            environment=EnvironmentSetup(
                env_type="directory",
                seed_files={
                    "spec.md": textwrap.dedent("""\
                        # taskr - CLI Todo Manager

                        ## Overview
                        A command-line todo list manager that stores tasks in a JSON file.

                        ## Usage
                        ```
                        python taskr.py add "Buy groceries"
                        python taskr.py add "Read book" --priority high
                        python taskr.py list
                        python taskr.py list --status pending
                        python taskr.py done 1
                        python taskr.py delete 1
                        python taskr.py stats
                        ```

                        ## Commands

                        ### add <title> [--priority low|medium|high]
                        Add a new task. Default priority is "medium".
                        Prints: "Added task #<id>: <title>"

                        ### list [--status pending|done|all] [--priority low|medium|high]
                        List tasks with optional filters. Default shows all.
                        Format: "#<id> [<status>] [<priority>] <title>"

                        ### done <id>
                        Mark task as done. Prints: "Completed task #<id>: <title>"

                        ### delete <id>
                        Delete a task. Prints: "Deleted task #<id>: <title>"

                        ### stats
                        Print statistics:
                        - Total tasks
                        - Pending tasks
                        - Completed tasks
                        - Tasks by priority

                        ## Data Storage
                        Tasks stored in `tasks.json` in the current directory.
                        Each task: {id, title, priority, status, created_at}
                        IDs auto-increment starting from 1.

                        ## Test Scenarios
                        1. Add 3 tasks with different priorities
                        2. List all tasks
                        3. Mark one as done
                        4. List only pending tasks (should show 2)
                        5. Show stats
                        6. Delete a task
                        7. Show stats again
                    """),
                },
            ),
            ground_truth="taskr.py implements all 5 commands correctly, data persists in tasks.json, all test scenarios pass",
            eval_spec=EvalSpec(
                method=EvalMethod.SCRIPT_CHECK,
                check_script_content=textwrap.dedent("""\
                    #!/bin/bash
                    set -e
                    rm -f tasks.json

                    # Test add
                    OUT1=$(python3 taskr.py add "Buy groceries" --priority high 2>&1)
                    echo "$OUT1" | grep -qi "added.*#1"

                    OUT2=$(python3 taskr.py add "Read book" 2>&1)
                    echo "$OUT2" | grep -qi "added.*#2"

                    OUT3=$(python3 taskr.py add "Exercise" --priority low 2>&1)
                    echo "$OUT3" | grep -qi "added.*#3"

                    # Test list
                    LIST=$(python3 taskr.py list 2>&1)
                    echo "$LIST" | grep -q "Buy groceries"
                    echo "$LIST" | grep -q "Read book"

                    # Test done
                    DONE=$(python3 taskr.py done 1 2>&1)
                    echo "$DONE" | grep -qi "completed.*#1"

                    # Test list pending
                    PENDING=$(python3 taskr.py list --status pending 2>&1)
                    echo "$PENDING" | grep -q "Read book"
                    # Buy groceries should NOT appear in pending
                    if echo "$PENDING" | grep -q "Buy groceries"; then
                        echo "FAIL: completed task in pending list"
                        exit 1
                    fi

                    # Test stats
                    STATS=$(python3 taskr.py stats 2>&1)
                    echo "$STATS" | grep -qi "total"

                    # Test delete
                    DEL=$(python3 taskr.py delete 2 2>&1)
                    echo "$DEL" | grep -qi "deleted.*#2"

                    echo "All tests passed!"
                """),
            ),
            capabilities=[
                Capability.DOC_READING,
                Capability.CODE_WRITING,
                Capability.FILE_CREATION,
                Capability.SHELL_COMMANDS,
                Capability.DECOMPOSITION,
                Capability.PRIORITIZATION,
                Capability.TEST_RUNNING,
            ],
            source="multi_step_generator:project_bootstrap",
            estimated_minutes=12,
        )

    def _migration_pipeline(self, difficulty: str) -> Task:
        """Task: migrate data between formats with validation."""
        sqlite_setup = textwrap.dedent("""\
            import sqlite3
            import os

            db_path = 'legacy.db'
            if os.path.exists(db_path):
                os.remove(db_path)

            conn = sqlite3.connect(db_path)
            c = conn.cursor()

            c.execute('''CREATE TABLE users (
                id INTEGER PRIMARY KEY,
                fullname TEXT,
                email TEXT,
                dept_code TEXT,
                hire_date TEXT,
                salary REAL,
                is_active INTEGER
            )''')

            c.execute('''CREATE TABLE departments (
                code TEXT PRIMARY KEY,
                name TEXT,
                budget REAL,
                manager_id INTEGER
            )''')

            users = [
                (1, 'Alice Smith', 'alice@corp.com', 'ENG', '2020-03-15', 95000, 1),
                (2, 'Bob Jones', 'bob@corp.com', 'MKT', '2019-07-01', 72000, 1),
                (3, 'Charlie Brown', 'charlie@corp.com', 'ENG', '2018-01-10', 105000, 1),
                (4, 'Diana Prince', 'diana@corp.com', 'SAL', '2021-06-20', 68000, 0),
                (5, 'Eve Wilson', 'eve@corp.com', 'ENG', '2020-11-01', 98000, 1),
                (6, 'Frank Castle', 'frank@corp.com', 'MKT', '2022-02-14', 75000, 1),
            ]
            c.executemany('INSERT INTO users VALUES (?,?,?,?,?,?,?)', users)

            depts = [
                ('ENG', 'Engineering', 500000, 3),
                ('MKT', 'Marketing', 200000, 2),
                ('SAL', 'Sales', 150000, 4),
            ]
            c.executemany('INSERT INTO departments VALUES (?,?,?,?)', depts)

            conn.commit()
            conn.close()
            print('Database created successfully')
        """)

        return Task(
            category=TaskCategory.MULTI_STEP,
            title="Migrate SQLite database to JSON API format",
            difficulty=difficulty,
            goal=textwrap.dedent("""\
                Migrate data from a SQLite database to a JSON-based API format.
                Steps:

                1. Run `python3 create_db.py` to create the legacy SQLite database
                2. Read the database schema and understand the relationships
                3. Export to a new format:
                   - users.json: array of user objects with department NAME (not code)
                     and is_active as boolean (not integer)
                   - departments.json: array with department objects including a
                     "employees" array of employee names and a "manager_name" field
                4. Create a verify.py script that:
                   - Reads both JSON files
                   - Checks data integrity (all users accounted for, valid references)
                   - Prints "Migration verified: X users, Y departments"
                5. Run verify.py to confirm
            """),
            environment=EnvironmentSetup(
                env_type="directory",
                seed_files={"create_db.py": sqlite_setup},
                setup_commands=["python3 create_db.py"],
            ),
            ground_truth="users.json has 6 users with department names, departments.json has 3 depts with employee lists and manager names",
            eval_spec=EvalSpec(
                method=EvalMethod.COMPOSITE,
                sub_evals=[
                    {"method": "file_exists", "expected_files": [
                        "users.json", "departments.json", "verify.py"
                    ]},
                    {"method": "command_output",
                     "check_command": "python3 -c \"import json; u=json.load(open('users.json')); assert len(u)==6; assert all('department' in x or 'dept' in str(x).lower() for x in u); print('users_ok')\"",
                     "output_contains": ["users_ok"]},
                    {"method": "command_output",
                     "check_command": "python3 -c \"import json; d=json.load(open('departments.json')); assert len(d)==3; print('depts_ok')\"",
                     "output_contains": ["depts_ok"]},
                    {"method": "command_output",
                     "check_command": "python3 verify.py 2>&1",
                     "output_contains": ["Migration verified"]},
                ]
            ),
            capabilities=[
                Capability.CODE_WRITING,
                Capability.CODE_READING,
                Capability.FILE_CREATION,
                Capability.SHELL_COMMANDS,
                Capability.DECOMPOSITION,
                Capability.MULTI_FILE_REASONING,
                Capability.SCRIPT_WRITING,
            ],
            source="multi_step_generator:migration_pipeline",
            estimated_minutes=12,
        )

    def _test_infrastructure(self, difficulty: str) -> Task:
        """Task: add test infrastructure to an untested project."""
        return Task(
            category=TaskCategory.MULTI_STEP,
            title="Add test suite to untested project",
            difficulty=difficulty,
            goal=textwrap.dedent("""\
                This project has no tests. Add a comprehensive test suite:

                1. Read all source files to understand the codebase
                2. Create a tests/ directory with test files
                3. Write tests for each module in src/
                4. Ensure tests cover:
                   - Calculator: all operations, edge cases (division by zero)
                   - StringUtils: all methods with various inputs
                   - DataStore: add, get, delete, list, persistence
                5. Run the tests and make sure they all pass
                6. Report coverage: which functions are tested
            """),
            environment=EnvironmentSetup(
                env_type="directory",
                seed_files={
                    "src/__init__.py": "",
                    "src/calculator.py": textwrap.dedent("""\
                        class Calculator:
                            def __init__(self):
                                self.history = []

                            def add(self, a, b):
                                result = a + b
                                self.history.append(f"{a} + {b} = {result}")
                                return result

                            def subtract(self, a, b):
                                result = a - b
                                self.history.append(f"{a} - {b} = {result}")
                                return result

                            def multiply(self, a, b):
                                result = a * b
                                self.history.append(f"{a} * {b} = {result}")
                                return result

                            def divide(self, a, b):
                                if b == 0:
                                    raise ValueError("Cannot divide by zero")
                                result = a / b
                                self.history.append(f"{a} / {b} = {result}")
                                return result

                            def get_history(self):
                                return list(self.history)

                            def clear_history(self):
                                self.history = []
                    """),
                    "src/string_utils.py": textwrap.dedent("""\
                        def reverse_string(s):
                            return s[::-1]

                        def is_palindrome(s):
                            cleaned = ''.join(c.lower() for c in s if c.isalnum())
                            return cleaned == cleaned[::-1]

                        def word_count(s):
                            if not s or not s.strip():
                                return 0
                            return len(s.split())

                        def truncate(s, max_length, suffix='...'):
                            if len(s) <= max_length:
                                return s
                            return s[:max_length - len(suffix)] + suffix

                        def to_title_case(s):
                            return ' '.join(w.capitalize() for w in s.split())
                    """),
                    "src/data_store.py": textwrap.dedent("""\
                        import json
                        import os

                        class DataStore:
                            def __init__(self, filepath='store.json'):
                                self.filepath = filepath
                                self.data = {}
                                if os.path.exists(filepath):
                                    with open(filepath) as f:
                                        self.data = json.load(f)

                            def set(self, key, value):
                                self.data[key] = value
                                self._save()

                            def get(self, key, default=None):
                                return self.data.get(key, default)

                            def delete(self, key):
                                if key in self.data:
                                    del self.data[key]
                                    self._save()
                                    return True
                                return False

                            def keys(self):
                                return list(self.data.keys())

                            def clear(self):
                                self.data = {}
                                self._save()

                            def _save(self):
                                with open(self.filepath, 'w') as f:
                                    json.dump(self.data, f, indent=2)
                    """),
                },
                setup_commands=["pip install pytest 2>/dev/null || true"],
            ),
            ground_truth="Test files for all 3 modules, all tests pass, coverage includes edge cases",
            eval_spec=EvalSpec(
                method=EvalMethod.COMPOSITE,
                sub_evals=[
                    {"method": "file_exists", "expected_files": ["tests/"]},
                    {"method": "command_output",
                     "check_command": "python3 -m pytest tests/ -v 2>&1 | tail -5",
                     "output_contains": ["passed"]},
                    {"method": "command_output",
                     "check_command": "python3 -m pytest tests/ 2>&1 | grep -E '\\d+ passed' | head -1",
                     "output_contains": ["passed"]},
                ]
            ),
            capabilities=[
                Capability.CODE_READING,
                Capability.CODE_WRITING,
                Capability.FILE_CREATION,
                Capability.TEST_RUNNING,
                Capability.DECOMPOSITION,
                Capability.MULTI_FILE_REASONING,
            ],
            source="multi_step_generator:test_infrastructure",
            estimated_minutes=12,
        )

    def _api_with_tests(self, difficulty: str) -> Task:
        """Task: build a REST API from a data model."""
        return Task(
            category=TaskCategory.MULTI_STEP,
            title="Build REST API server from data model",
            difficulty=difficulty,
            goal=textwrap.dedent("""\
                Build a simple REST API using Python's built-in http.server (no frameworks).

                The API should manage a "books" collection with these endpoints:
                - GET /books — list all books
                - GET /books/<id> — get one book
                - POST /books — create a book (JSON body: title, author, year)
                - DELETE /books/<id> — delete a book

                Requirements:
                1. Create server.py implementing the API
                2. Store data in books.json (persist between requests)
                3. Return proper status codes (200, 201, 404)
                4. Return JSON responses with Content-Type header
                5. Create test_api.py that starts the server, runs all CRUD tests,
                   and shuts down the server
                6. Run the tests to verify everything works
            """),
            environment=EnvironmentSetup(
                env_type="directory",
                seed_files={},
            ),
            ground_truth="server.py with all 4 endpoints working, test_api.py that validates CRUD operations",
            eval_spec=EvalSpec(
                method=EvalMethod.SCRIPT_CHECK,
                check_script_content=textwrap.dedent("""\
                    #!/bin/bash
                    set -e

                    # Start server
                    python3 server.py &
                    SERVER_PID=$!
                    sleep 2

                    cleanup() { kill $SERVER_PID 2>/dev/null; wait $SERVER_PID 2>/dev/null; }
                    trap cleanup EXIT

                    # Test POST
                    CREATED=$(curl -s -w "\\n%{http_code}" -X POST http://localhost:8000/books \
                        -H "Content-Type: application/json" \
                        -d '{"title":"Test Book","author":"Author","year":2024}')
                    CODE=$(echo "$CREATED" | tail -1)
                    if [ "$CODE" != "201" ]; then echo "POST failed: $CODE"; exit 1; fi

                    # Test GET all
                    LIST=$(curl -s http://localhost:8000/books)
                    if ! echo "$LIST" | python3 -c "import sys,json; d=json.load(sys.stdin); assert len(d)>=1"; then
                        echo "GET /books failed"; exit 1
                    fi

                    # Test DELETE
                    DEL_CODE=$(curl -s -o /dev/null -w "%{http_code}" -X DELETE http://localhost:8000/books/1)

                    echo "All API tests passed!"
                """),
            ),
            capabilities=[
                Capability.CODE_WRITING,
                Capability.FILE_CREATION,
                Capability.SHELL_COMMANDS,
                Capability.TEST_RUNNING,
                Capability.API_INTERACTION,
                Capability.DECOMPOSITION,
                Capability.PRIORITIZATION,
            ],
            source="multi_step_generator:api_with_tests",
            estimated_minutes=15,
        )

    def _refactor_and_verify(self, difficulty: str) -> Task:
        """Task: refactor messy code while maintaining behavior."""
        return Task(
            category=TaskCategory.MULTI_STEP,
            title="Refactor monolithic script into modules",
            difficulty=difficulty,
            goal=textwrap.dedent("""\
                The monolith.py file is a 200+ line single-file script that's hard to maintain.
                Refactor it into a proper multi-module structure:

                1. Read and understand the full script
                2. Identify logical components (data loading, processing, reporting)
                3. Split into separate modules under a package directory
                4. Create a new main.py entry point
                5. Ensure `python3 main.py` produces EXACTLY the same output as
                   `python3 monolith.py` (save original output first!)
                6. Keep monolith.py unchanged for comparison
            """),
            environment=EnvironmentSetup(
                env_type="directory",
                seed_files={
                    "monolith.py": textwrap.dedent("""\
                        import json
                        import os
                        import sys
                        from datetime import datetime

                        # Data loading
                        def load_data(filename):
                            if not os.path.exists(filename):
                                return []
                            with open(filename) as f:
                                return json.load(f)

                        def save_data(filename, data):
                            with open(filename, 'w') as f:
                                json.dump(data, f, indent=2)

                        # Processing
                        def filter_active(records):
                            return [r for r in records if r.get('active', False)]

                        def sort_by_field(records, field, reverse=False):
                            return sorted(records, key=lambda r: r.get(field, ''), reverse=reverse)

                        def aggregate_by(records, field):
                            groups = {}
                            for r in records:
                                key = r.get(field, 'unknown')
                                if key not in groups:
                                    groups[key] = []
                                groups[key].append(r)
                            return groups

                        def calculate_stats(values):
                            if not values:
                                return {'count': 0, 'sum': 0, 'avg': 0, 'min': 0, 'max': 0}
                            return {
                                'count': len(values),
                                'sum': sum(values),
                                'avg': round(sum(values) / len(values), 2),
                                'min': min(values),
                                'max': max(values)
                            }

                        # Reporting
                        def format_header(title):
                            return f"\\n{'='*40}\\n{title}\\n{'='*40}"

                        def format_table(records, fields):
                            if not records:
                                return "(no data)"
                            widths = {f: max(len(f), max(len(str(r.get(f, ''))) for r in records)) for f in fields}
                            header = ' | '.join(f.ljust(widths[f]) for f in fields)
                            sep = '-+-'.join('-' * widths[f] for f in fields)
                            rows = []
                            for r in records:
                                rows.append(' | '.join(str(r.get(f, '')).ljust(widths[f]) for f in fields))
                            return f"{header}\\n{sep}\\n" + '\\n'.join(rows)

                        def generate_report(data):
                            lines = []
                            lines.append(format_header("DATA REPORT"))
                            lines.append(f"Generated: {datetime.now().strftime('%Y-%m-%d')}")
                            lines.append(f"Total records: {len(data)}")

                            active = filter_active(data)
                            lines.append(f"Active records: {len(active)}")

                            sorted_data = sort_by_field(active, 'name')
                            lines.append(format_header("ACTIVE RECORDS"))
                            lines.append(format_table(sorted_data, ['name', 'department', 'score']))

                            groups = aggregate_by(active, 'department')
                            lines.append(format_header("BY DEPARTMENT"))
                            for dept, members in sorted(groups.items()):
                                scores = [m.get('score', 0) for m in members]
                                stats = calculate_stats(scores)
                                lines.append(f"  {dept}: {stats['count']} members, avg score: {stats['avg']}")

                            return '\\n'.join(lines)

                        # Main
                        if __name__ == '__main__':
                            sample_data = [
                                {'name': 'Alice', 'department': 'Engineering', 'score': 92, 'active': True},
                                {'name': 'Bob', 'department': 'Marketing', 'score': 78, 'active': True},
                                {'name': 'Charlie', 'department': 'Engineering', 'score': 85, 'active': False},
                                {'name': 'Diana', 'department': 'Sales', 'score': 90, 'active': True},
                                {'name': 'Eve', 'department': 'Engineering', 'score': 95, 'active': True},
                                {'name': 'Frank', 'department': 'Marketing', 'score': 82, 'active': True},
                            ]
                            save_data('data.json', sample_data)
                            data = load_data('data.json')
                            report = generate_report(data)
                            print(report)
                    """),
                },
            ),
            ground_truth="Code split into data_loader.py, processor.py, reporter.py modules. main.py produces identical output to monolith.py.",
            eval_spec=EvalSpec(
                method=EvalMethod.SCRIPT_CHECK,
                check_script_content=textwrap.dedent("""\
                    #!/bin/bash
                    set -e

                    # Get original output
                    ORIGINAL=$(python3 monolith.py 2>&1)

                    # Get refactored output
                    REFACTORED=$(python3 main.py 2>&1)

                    # Compare (ignore whitespace differences)
                    if [ "$(echo "$ORIGINAL" | tr -s ' ')" = "$(echo "$REFACTORED" | tr -s ' ')" ]; then
                        echo "Output matches! Refactoring preserved behavior."

                        # Check that modules exist
                        if [ -f main.py ] && find . -name "*.py" -not -name monolith.py -not -name main.py | grep -q .; then
                            echo "Module structure created."
                            echo "All checks passed!"
                            exit 0
                        else
                            echo "FAIL: No module files found"
                            exit 1
                        fi
                    else
                        echo "FAIL: Output differs!"
                        diff <(echo "$ORIGINAL") <(echo "$REFACTORED") || true
                        exit 1
                    fi
                """),
            ),
            capabilities=[
                Capability.CODE_READING,
                Capability.CODE_WRITING,
                Capability.CODE_EDITING,
                Capability.FILE_CREATION,
                Capability.SHELL_COMMANDS,
                Capability.DECOMPOSITION,
                Capability.MULTI_FILE_REASONING,
                Capability.PRIORITIZATION,
            ],
            source="multi_step_generator:refactor_and_verify",
            estimated_minutes=12,
        )

    def _build_and_deploy_setup(self, difficulty: str) -> Task:
        """Task: set up build, test, and deploy pipeline."""
        return Task(
            category=TaskCategory.MULTI_STEP,
            title="Set up complete CI/CD pipeline config",
            difficulty=difficulty,
            goal=textwrap.dedent("""\
                Set up a complete build and test pipeline for this Python project:

                1. Create a pyproject.toml with project metadata and dependencies
                2. Create a Makefile with targets: install, test, lint, format, clean, all
                3. Create a .github/workflows/ci.yml GitHub Actions workflow that:
                   - Triggers on push and pull request
                   - Runs on ubuntu-latest
                   - Sets up Python 3.11
                   - Installs dependencies
                   - Runs linting (flake8)
                   - Runs tests (pytest)
                4. Create a Dockerfile for the application
                5. Create a docker-compose.yml for local development
                6. Verify: make install && make lint && make test all succeed
            """),
            environment=EnvironmentSetup(
                env_type="directory",
                seed_files={
                    "src/__init__.py": "",
                    "src/app.py": textwrap.dedent("""\
                        def hello(name="World"):
                            return f"Hello, {name}!"

                        def add(a, b):
                            return a + b

                        if __name__ == "__main__":
                            print(hello())
                    """),
                    "tests/__init__.py": "",
                    "tests/test_app.py": textwrap.dedent("""\
                        from src.app import hello, add

                        def test_hello():
                            assert hello() == "Hello, World!"
                            assert hello("Alice") == "Hello, Alice!"

                        def test_add():
                            assert add(1, 2) == 3
                    """),
                },
                setup_commands=["pip install pytest flake8 2>/dev/null || true"],
            ),
            ground_truth="pyproject.toml, Makefile, .github/workflows/ci.yml, Dockerfile, docker-compose.yml all created. make test passes.",
            eval_spec=EvalSpec(
                method=EvalMethod.COMPOSITE,
                sub_evals=[
                    {"method": "file_exists", "expected_files": [
                        "pyproject.toml", "Makefile",
                        ".github/workflows/ci.yml", "Dockerfile",
                        "docker-compose.yml"
                    ]},
                    {"method": "file_content", "expected_content": {
                        ".github/workflows/ci.yml": "pytest",
                        "Dockerfile": "FROM",
                    }},
                    {"method": "command_output",
                     "check_command": "make test 2>&1",
                     "output_contains": ["passed"]},
                ]
            ),
            capabilities=[
                Capability.CODE_READING,
                Capability.FILE_CREATION,
                Capability.BUILD_SYSTEMS,
                Capability.CONFIG_EDITING,
                Capability.SHELL_COMMANDS,
                Capability.DECOMPOSITION,
                Capability.PRIORITIZATION,
                Capability.SCRIPT_WRITING,
            ],
            source="multi_step_generator:build_and_deploy_setup",
            estimated_minutes=15,
        )
