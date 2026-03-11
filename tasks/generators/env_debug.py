"""
Environment debugging task generator.

Generates tasks involving broken environments, misconfigured systems,
log analysis, dependency conflicts, and runtime errors that require
investigation and fixing.
"""

import textwrap
from ..schema import (
    Task, TaskCategory, Capability, EvalMethod,
    EnvironmentSetup, EvalSpec
)
from .base import TaskGenerator


class EnvDebugGenerator(TaskGenerator):
    """Generates environment debugging and troubleshooting tasks."""

    @property
    def category(self) -> TaskCategory:
        return TaskCategory.ENV_DEBUG

    def generate(self, count: int = 5, difficulty: str = "medium") -> list[Task]:
        generators = [
            self._broken_python_imports,
            self._port_conflict,
            self._missing_config,
            self._corrupt_json,
            self._path_issue,
            self._circular_dependency,
            self._encoding_issue,
            self._version_conflict,
        ]

        tasks = []
        for i in range(count):
            gen = generators[i % len(generators)]
            task = gen(difficulty)
            tasks.append(task)
        return tasks

    def _broken_python_imports(self, difficulty: str) -> Task:
        """Task: diagnose and fix broken Python imports."""
        return Task(
            category=TaskCategory.ENV_DEBUG,
            title="Fix broken Python import chain",
            difficulty=difficulty,
            goal=textwrap.dedent("""\
                Running `python3 main.py` produces an ImportError.
                Diagnose the import chain and fix all issues so the program runs
                and prints "Application started successfully".

                Do NOT restructure the project. Fix the minimum necessary to make imports work.
            """),
            environment=EnvironmentSetup(
                env_type="directory",
                seed_files={
                    "main.py": textwrap.dedent("""\
                        from app.server import create_app

                        if __name__ == '__main__':
                            app = create_app()
                            print("Application started successfully")
                    """),
                    "app/__init__.py": "",
                    "app/server.py": textwrap.dedent("""\
                        from app.config import Settings
                        from app.database import get_connection

                        def create_app():
                            settings = Settings()
                            db = get_connection(settings.db_url)
                            return {'settings': settings, 'db': db}
                    """),
                    "app/config.py": textwrap.dedent("""\
                        from app.utils.validators import validate_url

                        class Settings:
                            def __init__(self):
                                self.db_url = "sqlite:///app.db"
                                validate_url(self.db_url)
                    """),
                    # Missing __init__.py in utils/
                    "app/utils/validators.py": textwrap.dedent("""\
                        def validate_url(url):
                            if not url:
                                raise ValueError("Empty URL")
                            return True
                    """),
                    "app/database.py": textwrap.dedent("""\
                        from app.modls import Base

                        def get_connection(url):
                            return {'url': url, 'connected': True}
                    """),
                    # Typo: modls instead of models
                    "app/models.py": textwrap.dedent("""\
                        class Base:
                            pass
                    """),
                },
            ),
            ground_truth="Two fixes: 1) create app/utils/__init__.py, 2) fix typo in database.py: 'modls' -> 'models'",
            eval_spec=EvalSpec(
                method=EvalMethod.COMMAND_OUTPUT,
                check_command="python3 main.py 2>&1",
                output_contains=["Application started successfully"],
                output_not_contains=["Error", "Traceback"],
            ),
            capabilities=[
                Capability.ERROR_INTERPRETATION,
                Capability.ROOT_CAUSE_ANALYSIS,
                Capability.CODE_READING,
                Capability.CODE_EDITING,
                Capability.FILE_CREATION,
                Capability.MULTI_FILE_REASONING,
                Capability.HYPOTHESIS_TESTING,
            ],
            source="env_debug_generator:broken_python_imports",
            estimated_minutes=5,
        )

    def _port_conflict(self, difficulty: str) -> Task:
        """Task: diagnose why a server can't start."""
        return Task(
            category=TaskCategory.ENV_DEBUG,
            title="Diagnose and fix server startup failure",
            difficulty=difficulty,
            goal=textwrap.dedent("""\
                The server.py script is failing to start. When you run `python3 server.py`
                it should print "Server started on port XXXX" but instead it errors out.

                Diagnose the issue and fix it. The fix should be in the code, not by
                killing other processes. The server should be able to start successfully.
            """),
            environment=EnvironmentSetup(
                env_type="directory",
                seed_files={
                    "server.py": textwrap.dedent("""\
                        import socket
                        import json
                        import os

                        def load_config():
                            with open('server_config.json') as f:
                                return json.load(f)

                        def start_server():
                            config = load_config()
                            host = config['host']
                            port = config['port']

                            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                            sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
                            try:
                                sock.bind((host, port))
                                sock.listen(1)
                                print(f"Server started on port {port}")
                            except OSError as e:
                                print(f"Failed to start: {e}")
                                raise
                            finally:
                                sock.close()

                        if __name__ == '__main__':
                            start_server()
                    """),
                    "server_config.json": '{"host": "0.0.0.0", "port": "8080"}',
                    # Bug: port is a string, not an int
                },
            ),
            ground_truth="The port value in server_config.json is a string '8080' but socket.bind needs an int. Fix: either change JSON to use integer 8080, or add int() conversion in code.",
            eval_spec=EvalSpec(
                method=EvalMethod.COMMAND_OUTPUT,
                check_command="python3 server.py 2>&1",
                output_contains=["Server started on port"],
                output_not_contains=["Failed to start", "Error", "Traceback"],
            ),
            capabilities=[
                Capability.ERROR_INTERPRETATION,
                Capability.ROOT_CAUSE_ANALYSIS,
                Capability.CODE_READING,
                Capability.CONFIG_READING,
                Capability.CODE_EDITING,
            ],
            source="env_debug_generator:port_conflict",
            estimated_minutes=3,
        )

    def _missing_config(self, difficulty: str) -> Task:
        """Task: diagnose missing/partial configuration."""
        return Task(
            category=TaskCategory.ENV_DEBUG,
            title="Fix application failing due to missing config",
            difficulty=difficulty,
            goal=textwrap.dedent("""\
                The application crashes on startup with a cryptic error.
                Run `python3 app.py` to see the error. Diagnose why it fails
                and fix the configuration so the app starts and prints
                "App initialized: all checks passed".
            """),
            environment=EnvironmentSetup(
                env_type="directory",
                seed_files={
                    "app.py": textwrap.dedent("""\
                        import yaml
                        import sys

                        def load_config():
                            with open('config/app.yaml') as f:
                                config = yaml.safe_load(f)
                            required = ['database.host', 'database.port', 'database.name',
                                       'cache.backend', 'cache.ttl',
                                       'auth.secret_key', 'auth.algorithm']
                            missing = []
                            for key in required:
                                parts = key.split('.')
                                val = config
                                for part in parts:
                                    if isinstance(val, dict):
                                        val = val.get(part)
                                    else:
                                        val = None
                                if val is None:
                                    missing.append(key)
                            if missing:
                                print(f"Missing config keys: {', '.join(missing)}", file=sys.stderr)
                                sys.exit(1)
                            return config

                        if __name__ == '__main__':
                            config = load_config()
                            print("App initialized: all checks passed")
                    """),
                    "config/app.yaml": textwrap.dedent("""\
                        database:
                          host: localhost
                          port: 5432

                        cache:
                          backend: redis
                    """),
                    # Missing: database.name, cache.ttl, auth section entirely
                },
                setup_commands=["pip install pyyaml 2>/dev/null || true"],
            ),
            ground_truth="Add missing keys to config/app.yaml: database.name, cache.ttl, auth.secret_key, auth.algorithm",
            eval_spec=EvalSpec(
                method=EvalMethod.COMMAND_OUTPUT,
                check_command="python3 app.py 2>&1",
                output_contains=["App initialized: all checks passed"],
                output_not_contains=["Missing config keys"],
            ),
            capabilities=[
                Capability.ERROR_INTERPRETATION,
                Capability.CODE_READING,
                Capability.CONFIG_READING,
                Capability.CONFIG_EDITING,
                Capability.ROOT_CAUSE_ANALYSIS,
            ],
            source="env_debug_generator:missing_config",
            estimated_minutes=5,
        )

    def _corrupt_json(self, difficulty: str) -> Task:
        """Task: fix corrupt data files."""
        return Task(
            category=TaskCategory.ENV_DEBUG,
            title="Fix and recover corrupt JSON data files",
            difficulty=difficulty,
            goal=textwrap.dedent("""\
                The data/ directory contains JSON files that a data pipeline reads.
                Running `python3 pipeline.py` fails because some JSON files are corrupt.

                1. Find which files are corrupt
                2. Fix the JSON syntax errors (preserving all data)
                3. Run pipeline.py to verify it completes successfully
                   and prints "Pipeline complete: processed N records"
            """),
            environment=EnvironmentSetup(
                env_type="directory",
                seed_files={
                    "pipeline.py": textwrap.dedent("""\
                        import json
                        import os
                        import sys

                        def process_data():
                            data_dir = 'data'
                            total = 0
                            for fname in sorted(os.listdir(data_dir)):
                                if not fname.endswith('.json'):
                                    continue
                                path = os.path.join(data_dir, fname)
                                with open(path) as f:
                                    records = json.load(f)
                                if not isinstance(records, list):
                                    print(f"Error: {fname} is not a list", file=sys.stderr)
                                    sys.exit(1)
                                total += len(records)
                            print(f"Pipeline complete: processed {total} records")

                        if __name__ == '__main__':
                            process_data()
                    """),
                    "data/batch_001.json": '[{"id": 1, "value": "alpha"}, {"id": 2, "value": "beta"}]',
                    "data/batch_002.json": '[{"id": 3, "value": "gamma"}, {"id": 4, "value": "delta",}]',
                    # Bug: trailing comma
                    "data/batch_003.json": '[{"id": 5, "value": "epsilon"}, {"id": 6, "value": "zeta"}]',
                    "data/batch_004.json": '[{"id": 7, "value": "eta"} {"id": 8, "value": "theta"}]',
                    # Bug: missing comma between objects
                    "data/batch_005.json": '[{"id": 9, "value": "iota"}, {"id": 10, "value": "kappa"}]',
                },
            ),
            ground_truth="Fix batch_002.json (trailing comma) and batch_004.json (missing comma). Total: 10 records.",
            eval_spec=EvalSpec(
                method=EvalMethod.COMMAND_OUTPUT,
                check_command="python3 pipeline.py 2>&1",
                output_contains=["Pipeline complete: processed 10 records"],
                output_not_contains=["Error", "Traceback"],
            ),
            capabilities=[
                Capability.ERROR_INTERPRETATION,
                Capability.ROOT_CAUSE_ANALYSIS,
                Capability.CODE_READING,
                Capability.CODE_EDITING,
                Capability.FILE_SEARCH,
                Capability.HYPOTHESIS_TESTING,
            ],
            source="env_debug_generator:corrupt_json",
            estimated_minutes=5,
        )

    def _path_issue(self, difficulty: str) -> Task:
        """Task: fix path-related issues in a project."""
        return Task(
            category=TaskCategory.ENV_DEBUG,
            title="Fix path resolution issues in multi-module project",
            difficulty=difficulty,
            goal=textwrap.dedent("""\
                Running `python3 run.py` fails with a FileNotFoundError.
                The project uses relative paths that break depending on the working directory.
                Fix the path handling so that run.py works regardless of where it's
                invoked from. It should print "All templates loaded successfully".

                Test from both the project root AND from a parent directory:
                  python3 run.py
                  cd /tmp && python3 /path/to/run.py
            """),
            environment=EnvironmentSetup(
                env_type="directory",
                seed_files={
                    "run.py": textwrap.dedent("""\
                        from app.loader import load_templates

                        if __name__ == '__main__':
                            templates = load_templates()
                            print(f"All templates loaded successfully")
                    """),
                    "app/__init__.py": "",
                    "app/loader.py": textwrap.dedent("""\
                        import os

                        def load_templates():
                            template_dir = "templates"  # Bug: relative to CWD, not to project
                            templates = {}
                            for fname in os.listdir(template_dir):
                                if fname.endswith('.txt'):
                                    with open(os.path.join(template_dir, fname)) as f:
                                        templates[fname] = f.read()
                            return templates
                    """),
                    "templates/welcome.txt": "Welcome, {name}!",
                    "templates/error.txt": "Error: {message}",
                    "templates/footer.txt": "Copyright 2024",
                },
            ),
            ground_truth="Fix loader.py to use __file__-relative paths: os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'templates')",
            eval_spec=EvalSpec(
                method=EvalMethod.COMPOSITE,
                sub_evals=[
                    {"method": "command_output",
                     "check_command": "python3 run.py 2>&1",
                     "output_contains": ["All templates loaded successfully"]},
                    {"method": "command_output",
                     "check_command": "cd /tmp && python3 $OLDPWD/run.py 2>&1",
                     "output_contains": ["All templates loaded successfully"]},
                ]
            ),
            capabilities=[
                Capability.ERROR_INTERPRETATION,
                Capability.ROOT_CAUSE_ANALYSIS,
                Capability.CODE_READING,
                Capability.CODE_EDITING,
                Capability.MULTI_FILE_REASONING,
            ],
            source="env_debug_generator:path_issue",
            estimated_minutes=5,
        )

    def _circular_dependency(self, difficulty: str) -> Task:
        """Task: break a circular import."""
        return Task(
            category=TaskCategory.ENV_DEBUG,
            title="Break circular import dependency",
            difficulty=difficulty,
            goal=textwrap.dedent("""\
                Running `python3 main.py` produces an ImportError due to circular
                imports. The modules depend on each other in a cycle.

                Break the circular dependency WITHOUT removing any functionality.
                All existing functions must still work. The program should print
                "Result: 42" when running main.py.
            """),
            environment=EnvironmentSetup(
                env_type="directory",
                seed_files={
                    "main.py": textwrap.dedent("""\
                        from services.processor import process

                        if __name__ == '__main__':
                            result = process(42)
                            print(f"Result: {result}")
                    """),
                    "services/__init__.py": "",
                    "services/processor.py": textwrap.dedent("""\
                        from services.validator import validate
                        from services.formatter import format_output

                        def process(data):
                            validate(data)
                            return format_output(data)
                    """),
                    "services/validator.py": textwrap.dedent("""\
                        from services.formatter import format_error

                        def validate(data):
                            if data is None:
                                raise ValueError(format_error("data is None"))
                            return True
                    """),
                    "services/formatter.py": textwrap.dedent("""\
                        from services.validator import validate

                        def format_output(data):
                            validate(data)
                            return data

                        def format_error(msg):
                            return f"[ERROR] {msg}"
                    """),
                },
            ),
            ground_truth="Break the cycle between validator.py and formatter.py. Options: lazy import, move format_error to a shared module, or inline the dependency.",
            eval_spec=EvalSpec(
                method=EvalMethod.COMMAND_OUTPUT,
                check_command="python3 main.py 2>&1",
                output_contains=["Result: 42"],
                output_not_contains=["ImportError", "Traceback"],
            ),
            capabilities=[
                Capability.ERROR_INTERPRETATION,
                Capability.ROOT_CAUSE_ANALYSIS,
                Capability.CODE_READING,
                Capability.CODE_EDITING,
                Capability.MULTI_FILE_REASONING,
                Capability.DECOMPOSITION,
            ],
            source="env_debug_generator:circular_dependency",
            estimated_minutes=5,
        )

    def _encoding_issue(self, difficulty: str) -> Task:
        """Task: fix file encoding issues."""
        return Task(
            category=TaskCategory.ENV_DEBUG,
            title="Fix file encoding errors in text processor",
            difficulty=difficulty,
            goal=textwrap.dedent("""\
                The process.py script reads text files from the input/ directory
                but crashes on some files due to encoding issues.

                Fix process.py so it handles all files correctly regardless of encoding.
                It should print "Processed N files, M total characters" when done.
                Do not modify the input files themselves.
            """),
            environment=EnvironmentSetup(
                env_type="directory",
                seed_files={
                    "process.py": textwrap.dedent("""\
                        import os

                        def process_files():
                            input_dir = 'input'
                            file_count = 0
                            total_chars = 0
                            for fname in sorted(os.listdir(input_dir)):
                                path = os.path.join(input_dir, fname)
                                with open(path, 'r') as f:  # Bug: no encoding handling
                                    content = f.read()
                                total_chars += len(content)
                                file_count += 1
                            print(f"Processed {file_count} files, {total_chars} total characters")

                        if __name__ == '__main__':
                            process_files()
                    """),
                    "input/english.txt": "Hello, World! This is a test file.\n",
                    "input/numbers.txt": "12345 67890\nabcdef\n",
                },
                setup_commands=[
                    # Create a file with non-UTF8 encoding
                    "python3 -c \"open('input/latin1.txt', 'wb').write(b'Caf\\xe9 na\\xefve r\\xe9sum\\xe9\\n')\"",
                    "python3 -c \"open('input/mixed.txt', 'wb').write(b'Normal text\\nM\\xf6re text\\nEnd\\n')\"",
                ],
            ),
            ground_truth="Fix process.py to handle encoding: use errors='replace' or try utf-8 then latin-1 fallback",
            eval_spec=EvalSpec(
                method=EvalMethod.COMMAND_OUTPUT,
                check_command="python3 process.py 2>&1",
                output_contains=["Processed 4 files"],
                output_not_contains=["Error", "Traceback", "UnicodeDecodeError"],
            ),
            capabilities=[
                Capability.ERROR_INTERPRETATION,
                Capability.ROOT_CAUSE_ANALYSIS,
                Capability.CODE_READING,
                Capability.CODE_EDITING,
            ],
            source="env_debug_generator:encoding_issue",
            estimated_minutes=5,
        )

    def _version_conflict(self, difficulty: str) -> Task:
        """Task: diagnose and fix API version compatibility issue."""
        return Task(
            category=TaskCategory.ENV_DEBUG,
            title="Fix API version compatibility in client code",
            difficulty=difficulty,
            goal=textwrap.dedent("""\
                The client.py script calls a local API (api.py) but gets errors
                because it uses the old API format. The API was recently updated
                (v2) but the client was not.

                1. Start the API: `python3 api.py &`
                2. Run the client: `python3 client.py`
                3. The client should print "All API calls successful"

                Fix the client to work with the v2 API. Do NOT modify api.py.
            """),
            environment=EnvironmentSetup(
                env_type="directory",
                seed_files={
                    "api.py": textwrap.dedent("""\
                        import http.server
                        import json

                        class APIHandler(http.server.BaseHTTPRequestHandler):
                            def do_GET(self):
                                self.send_response(200)
                                self.send_header('Content-type', 'application/json')
                                self.end_headers()
                                # v2 API wraps data in {"data": ..., "version": 2}
                                response = {"data": {"users": [{"id": 1, "name": "Alice"}]}, "version": 2}
                                self.wfile.write(json.dumps(response).encode())

                            def do_POST(self):
                                length = int(self.headers.get('content-length', 0))
                                body = json.loads(self.rfile.read(length)) if length else {}
                                # v2 expects {"payload": {...}} not raw data
                                if 'payload' not in body:
                                    self.send_response(400)
                                    self.send_header('Content-type', 'application/json')
                                    self.end_headers()
                                    self.wfile.write(json.dumps({"error": "Missing 'payload' wrapper"}).encode())
                                    return
                                self.send_response(201)
                                self.send_header('Content-type', 'application/json')
                                self.end_headers()
                                self.wfile.write(json.dumps({"data": body['payload'], "version": 2}).encode())

                            def log_message(self, fmt, *args):
                                pass  # suppress logs

                        if __name__ == '__main__':
                            server = http.server.HTTPServer(('localhost', 9876), APIHandler)
                            print("API running on port 9876")
                            server.serve_forever()
                    """),
                    "client.py": textwrap.dedent("""\
                        import urllib.request
                        import json

                        BASE = 'http://localhost:9876'

                        def get_users():
                            resp = urllib.request.urlopen(f'{BASE}/users')
                            data = json.loads(resp.read())
                            # v1 client expects flat response: {"users": [...]}
                            return data['users']

                        def create_user(name):
                            # v1 client sends raw data
                            body = json.dumps({"name": name}).encode()
                            req = urllib.request.Request(f'{BASE}/users', data=body,
                                                        headers={'Content-Type': 'application/json'})
                            resp = urllib.request.urlopen(req)
                            return json.loads(resp.read())

                        if __name__ == '__main__':
                            users = get_users()
                            assert len(users) > 0, "No users returned"
                            result = create_user("Bob")
                            assert 'name' in str(result), "Create failed"
                            print("All API calls successful")
                    """),
                },
            ),
            ground_truth="Fix client.py: 1) get_users should unwrap data['data']['users'], 2) create_user should wrap body in {'payload': {...}}",
            eval_spec=EvalSpec(
                method=EvalMethod.SCRIPT_CHECK,
                check_script_content=textwrap.dedent("""\
                    #!/bin/bash
                    # Start API in background
                    python3 api.py &
                    API_PID=$!
                    sleep 1

                    # Run client
                    OUTPUT=$(python3 client.py 2>&1)
                    RESULT=$?

                    # Cleanup
                    kill $API_PID 2>/dev/null
                    wait $API_PID 2>/dev/null

                    echo "$OUTPUT"
                    if echo "$OUTPUT" | grep -q "All API calls successful"; then
                        exit 0
                    else
                        exit 1
                    fi
                """),
            ),
            capabilities=[
                Capability.ERROR_INTERPRETATION,
                Capability.ROOT_CAUSE_ANALYSIS,
                Capability.CODE_READING,
                Capability.CODE_EDITING,
                Capability.API_INTERACTION,
                Capability.HYPOTHESIS_TESTING,
                Capability.MULTI_FILE_REASONING,
            ],
            source="env_debug_generator:version_conflict",
            estimated_minutes=8,
        )
