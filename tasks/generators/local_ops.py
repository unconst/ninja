"""
Local operations task generator.

Generates tasks involving file manipulation, shell scripting, dependency
management, and local system operations — things an agent should handle
in everyday developer workflows.
"""

import random
import textwrap
from ..schema import (
    Task, TaskCategory, Capability, EvalMethod,
    EnvironmentSetup, EvalSpec
)
from .base import TaskGenerator


class LocalOpsGenerator(TaskGenerator):
    """Generates local file/shell/script operation tasks."""

    @property
    def category(self) -> TaskCategory:
        return TaskCategory.LOCAL_OPS

    def generate(self, count: int = 5, difficulty: str = "medium") -> list[Task]:
        """Generate local ops tasks from templates with randomization."""
        generators = [
            self._file_reorganization,
            self._broken_script_fix,
            self._config_migration,
            self._log_extraction,
            self._dependency_cleanup,
            self._data_transformation,
            self._permission_fix,
            self._build_script_creation,
            self._env_setup,
            self._batch_rename,
        ]

        tasks = []
        for i in range(count):
            gen = generators[i % len(generators)]
            task = gen(difficulty)
            issues = self.validate_task(task)
            if issues:
                print(f"  Warning: {task.task_id} has issues: {issues}")
            tasks.append(task)
        return tasks

    def _file_reorganization(self, difficulty: str) -> Task:
        """Task: reorganize a messy project directory into standard structure."""
        # Seed files representing a flat, unorganized project
        seed = {
            "app.py": textwrap.dedent("""\
                from flask import Flask
                app = Flask(__name__)
                @app.route('/')
                def index():
                    return 'Hello World'
                if __name__ == '__main__':
                    app.run()
            """),
            "test_app.py": textwrap.dedent("""\
                import pytest
                from app import app
                def test_index():
                    client = app.test_client()
                    resp = client.get('/')
                    assert resp.status_code == 200
            """),
            "utils.py": textwrap.dedent("""\
                import os
                def get_config():
                    return {'debug': os.environ.get('DEBUG', 'false')}
            """),
            "config.yaml": "debug: true\nport: 5000\ndb_url: sqlite:///app.db\n",
            "requirements.txt": "flask==3.0.0\npytest==8.0.0\npyyaml==6.0\n",
            "setup_db.sql": "CREATE TABLE users (id INTEGER PRIMARY KEY, name TEXT);\n",
            "notes.txt": "TODO: add authentication\nTODO: add logging\n",
            "deploy.sh": "#!/bin/bash\npip install -r requirements.txt\npython app.py\n",
        }

        return Task(
            category=TaskCategory.LOCAL_OPS,
            title="Reorganize flat project into standard structure",
            difficulty=difficulty,
            goal=textwrap.dedent("""\
                This project has all files dumped in the root directory with no organization.
                Reorganize it into a proper Python project structure:

                - Move source code into a `src/` directory
                - Move tests into a `tests/` directory
                - Move config files into a `config/` directory
                - Move SQL files into a `migrations/` directory
                - Keep requirements.txt and deploy.sh at root
                - Update any imports that break due to the reorganization
                - Make sure the test can still find the app module
            """),
            environment=EnvironmentSetup(
                env_type="directory",
                seed_files=seed,
                setup_commands=["pip install flask pytest pyyaml 2>/dev/null || true"],
            ),
            ground_truth="Files moved to src/, tests/, config/, migrations/ with imports updated",
            eval_spec=EvalSpec(
                method=EvalMethod.COMPOSITE,
                sub_evals=[
                    {"method": "file_exists", "expected_files": [
                        "src/app.py", "src/utils.py", "tests/test_app.py",
                        "config/config.yaml", "migrations/setup_db.sql",
                        "requirements.txt", "deploy.sh"
                    ]},
                    {"method": "command_output",
                     "check_command": "test ! -f app.py && test ! -f utils.py && echo 'cleaned'",
                     "output_contains": ["cleaned"]},
                ]
            ),
            capabilities=[
                Capability.DIRECTORY_NAVIGATION,
                Capability.FILE_CREATION,
                Capability.CODE_EDITING,
                Capability.SHELL_COMMANDS,
                Capability.DECOMPOSITION,
            ],
            source="local_ops_generator:file_reorganization",
            estimated_minutes=5,
        )

    def _broken_script_fix(self, difficulty: str) -> Task:
        """Task: fix a broken shell script with common errors."""
        broken_script = textwrap.dedent("""\
            #!/bin/bash
            # Deploy script for the application

            set -e

            DEPLOY_DIR="/tmp/myapp_deploy_$$"
            LOG_FILE="$DEPLOY_DIR/deploy.log

            mkdir -p $DEPLOY_DIR

            echo "Starting deployment..." > $LOG_FILE
            echo "Date: $(date)" >> LOG_FILE

            # Check if python exists
            if which python3; then
                PYTHON=python3
            else if which python; then
                PYTHON=python
            fi

            # Create virtual environment
            $PYTHON -m venv $DEPLOY_DIR/venv
            source $DEPLOY_DIR/venv/bin/activate

            # Install requirements
            pip install -r requirements.txt 2>&1 | tee -a $LOG_FILE

            # Run tests
            python -m pytest tests/ 2>&1 | tee -a $LOG_FILE
            RESULT=$?

            if [ $RESULT -neq 0 ]; then
                echo "Tests failed!" >> $LOG_FILE
                exit 1
            fi

            echo "Deployment complete!" >> $LOG_FILE
            echo "Deployed to: $DEPLOY_DIR"
        """)

        requirements = "pytest==8.0.0\n"
        test_file = textwrap.dedent("""\
            def test_placeholder():
                assert True
        """)

        return Task(
            category=TaskCategory.LOCAL_OPS,
            title="Fix broken deployment shell script",
            difficulty=difficulty,
            goal=textwrap.dedent("""\
                The deploy.sh script has several bugs that prevent it from running.
                Fix all the bugs so the script runs successfully to completion.
                There are at least 4 distinct bugs. Fix them all.

                Test your fix by running: bash deploy.sh
            """),
            environment=EnvironmentSetup(
                env_type="directory",
                seed_files={
                    "deploy.sh": broken_script,
                    "requirements.txt": requirements,
                    "tests/test_basic.py": test_file,
                },
            ),
            ground_truth="Bugs: 1) unclosed quote on LOG_FILE line, 2) LOG_FILE missing $ prefix, 3) else if should be elif, 4) -neq should be -ne",
            eval_spec=EvalSpec(
                method=EvalMethod.COMMAND_OUTPUT,
                check_command="bash deploy.sh 2>&1",
                output_contains=["Deployment complete!", "Deployed to:"],
                output_not_contains=["syntax error", "command not found"],
            ),
            capabilities=[
                Capability.CODE_READING,
                Capability.CODE_EDITING,
                Capability.SHELL_COMMANDS,
                Capability.ERROR_INTERPRETATION,
                Capability.ROOT_CAUSE_ANALYSIS,
                Capability.SCRIPT_WRITING,
            ],
            source="local_ops_generator:broken_script_fix",
            estimated_minutes=5,
        )

    def _config_migration(self, difficulty: str) -> Task:
        """Task: convert config from one format to another."""
        ini_config = textwrap.dedent("""\
            [database]
            host = localhost
            port = 5432
            name = myapp_db
            user = admin
            password = secret123
            pool_size = 10

            [redis]
            host = localhost
            port = 6379
            db = 0

            [server]
            host = 0.0.0.0
            port = 8080
            debug = true
            workers = 4

            [logging]
            level = INFO
            file = /var/log/myapp.log
            format = %(asctime)s %(levelname)s %(message)s
        """)

        return Task(
            category=TaskCategory.LOCAL_OPS,
            title="Convert INI config to YAML and TOML",
            difficulty=difficulty,
            goal=textwrap.dedent("""\
                Convert the config.ini file into two equivalent files:
                1. config.yaml (YAML format)
                2. config.toml (TOML format)

                Preserve all sections, keys, and values. Numeric values should be
                numbers (not strings). Boolean values should be booleans.
                Keep the original config.ini file.
            """),
            environment=EnvironmentSetup(
                env_type="directory",
                seed_files={"config.ini": ini_config},
                setup_commands=["pip install pyyaml toml 2>/dev/null || true"],
            ),
            ground_truth="config.yaml and config.toml created with correct types and all values preserved",
            eval_spec=EvalSpec(
                method=EvalMethod.COMPOSITE,
                sub_evals=[
                    {"method": "file_exists", "expected_files": ["config.yaml", "config.toml", "config.ini"]},
                    {"method": "file_content", "expected_content": {
                        "config.yaml": "pool_size: 10",
                        "config.toml": "pool_size = 10",
                    }},
                    {"method": "command_output",
                     "check_command": "python3 -c \"import yaml; d=yaml.safe_load(open('config.yaml')); assert d['database']['port']==5432; assert d['server']['debug']==True; print('yaml_ok')\"",
                     "output_contains": ["yaml_ok"]},
                ]
            ),
            capabilities=[
                Capability.CONFIG_READING,
                Capability.CONFIG_EDITING,
                Capability.FILE_CREATION,
                Capability.CODE_WRITING,
                Capability.SCRIPT_WRITING,
            ],
            source="local_ops_generator:config_migration",
            estimated_minutes=5,
        )

    def _log_extraction(self, difficulty: str) -> Task:
        """Task: extract and summarize information from log files."""
        log_content = "\n".join([
            "2024-01-15 08:00:01 INFO  server started on port 8080",
            "2024-01-15 08:00:05 INFO  database connected: pool_size=10",
            "2024-01-15 08:01:12 WARN  slow query detected: 2.3s SELECT * FROM users",
            "2024-01-15 08:02:30 INFO  request: GET /api/users 200 45ms",
            "2024-01-15 08:02:31 INFO  request: POST /api/login 200 120ms",
            "2024-01-15 08:03:15 ERROR connection pool exhausted, retrying...",
            "2024-01-15 08:03:16 ERROR connection pool exhausted, retrying...",
            "2024-01-15 08:03:17 INFO  connection pool recovered",
            "2024-01-15 08:04:00 INFO  request: GET /api/users 200 50ms",
            "2024-01-15 08:04:01 WARN  deprecated API endpoint called: /api/v1/users",
            "2024-01-15 08:05:30 ERROR unhandled exception: NullPointerError in UserService.getProfile",
            "2024-01-15 08:05:30 ERROR   at UserService.java:142",
            "2024-01-15 08:05:30 ERROR   at RequestHandler.java:89",
            "2024-01-15 08:06:00 INFO  request: GET /health 200 5ms",
            "2024-01-15 08:07:45 WARN  memory usage above 80%: 82.3%",
            "2024-01-15 08:10:00 INFO  request: GET /api/users 200 48ms",
            "2024-01-15 08:15:00 ERROR database connection timeout after 30s",
            "2024-01-15 08:15:01 ERROR database connection timeout after 30s",
            "2024-01-15 08:15:02 WARN  circuit breaker opened for database",
            "2024-01-15 08:16:00 INFO  circuit breaker closed, database reconnected",
        ])

        return Task(
            category=TaskCategory.LOCAL_OPS,
            title="Extract and summarize log issues",
            difficulty=difficulty,
            goal=textwrap.dedent("""\
                Analyze the application log file (app.log) and create a report file called report.txt with:

                1. Total count of each log level (INFO, WARN, ERROR)
                2. List of unique error messages
                3. List of unique warnings
                4. Average response time of HTTP requests (from the request lines)
                5. Time range of the log file (first and last timestamp)

                Use simple text format with clear section headers.
            """),
            environment=EnvironmentSetup(
                env_type="directory",
                seed_files={"app.log": log_content},
            ),
            ground_truth="report.txt with correct counts (INFO:9, WARN:3, ERROR:6), unique errors listed, average response time ~53.6ms",
            eval_spec=EvalSpec(
                method=EvalMethod.COMPOSITE,
                sub_evals=[
                    {"method": "file_exists", "expected_files": ["report.txt"]},
                    {"method": "file_content", "expected_content": {
                        "report.txt": "ERROR",
                    }},
                    {"method": "command_output",
                     "check_command": "grep -c 'INFO' report.txt | head -1 && grep -ci 'error' report.txt | head -1",
                     "output_contains": []},
                ]
            ),
            capabilities=[
                Capability.LOG_ANALYSIS,
                Capability.FILE_CREATION,
                Capability.SHELL_COMMANDS,
                Capability.CODE_WRITING,
                Capability.SUMMARY_GENERATION,
            ],
            source="local_ops_generator:log_extraction",
            estimated_minutes=5,
        )

    def _dependency_cleanup(self, difficulty: str) -> Task:
        """Task: audit and clean up project dependencies."""
        requirements = textwrap.dedent("""\
            flask==2.0.1
            requests==2.28.0
            numpy==1.23.0
            pandas==1.5.0
            scikit-learn==1.2.0
            matplotlib==3.6.0
            SQLAlchemy==1.4.40
            celery==5.2.7
            redis==4.3.4
            boto3==1.26.0
            pytest==7.2.0
            black==22.10.0
            flake8==5.0.4
            mypy==0.990
            sphinx==5.3.0
            coverage==6.5.0
        """)

        app_code = textwrap.dedent("""\
            from flask import Flask, jsonify
            import requests
            from sqlalchemy import create_engine

            app = Flask(__name__)
            engine = create_engine('sqlite:///app.db')

            @app.route('/api/data')
            def get_data():
                resp = requests.get('https://api.example.com/data')
                return jsonify(resp.json())
        """)

        return Task(
            category=TaskCategory.LOCAL_OPS,
            title="Audit and split requirements into prod/dev",
            difficulty=difficulty,
            goal=textwrap.dedent("""\
                The requirements.txt has all dependencies mixed together.

                1. Read the source code in src/ to determine which packages are actually used at runtime
                2. Split requirements.txt into:
                   - requirements.txt (production dependencies only)
                   - requirements-dev.txt (development/testing tools only)
                3. Remove any packages that are not imported anywhere in the codebase
                4. Keep version pins as-is
            """),
            environment=EnvironmentSetup(
                env_type="directory",
                seed_files={
                    "requirements.txt": requirements,
                    "src/app.py": app_code,
                    "tests/test_app.py": "import pytest\nfrom src.app import app\ndef test_health():\n    pass\n",
                },
            ),
            ground_truth="requirements.txt: flask, requests, SQLAlchemy. requirements-dev.txt: pytest, black, flake8, mypy, coverage. Removed: numpy, pandas, scikit-learn, matplotlib, celery, redis, boto3, sphinx",
            eval_spec=EvalSpec(
                method=EvalMethod.COMPOSITE,
                sub_evals=[
                    {"method": "file_exists", "expected_files": ["requirements.txt", "requirements-dev.txt"]},
                    {"method": "file_content", "expected_content": {
                        "requirements.txt": "flask",
                        "requirements-dev.txt": "pytest",
                    }},
                    {"method": "command_output",
                     "check_command": "! grep -q 'numpy' requirements.txt && ! grep -q 'pandas' requirements.txt && echo 'unused_removed'",
                     "output_contains": ["unused_removed"]},
                ]
            ),
            capabilities=[
                Capability.CODE_READING,
                Capability.DEPENDENCY_MGMT,
                Capability.FILE_CREATION,
                Capability.MULTI_FILE_REASONING,
                Capability.DECOMPOSITION,
            ],
            source="local_ops_generator:dependency_cleanup",
            estimated_minutes=5,
        )

    def _data_transformation(self, difficulty: str) -> Task:
        """Task: transform CSV data and generate a summary."""
        csv_data = textwrap.dedent("""\
            name,department,salary,start_date,status
            Alice,Engineering,95000,2020-03-15,active
            Bob,Marketing,72000,2019-07-01,active
            Charlie,Engineering,105000,2018-01-10,active
            Diana,Sales,68000,2021-06-20,inactive
            Eve,Engineering,98000,2020-11-01,active
            Frank,Marketing,75000,2022-02-14,active
            Grace,Sales,71000,2019-09-30,active
            Henry,Engineering,110000,2017-05-22,active
            Iris,Marketing,69000,2023-01-05,active
            Jack,Sales,82000,2020-08-15,inactive
        """)

        return Task(
            category=TaskCategory.LOCAL_OPS,
            title="Transform CSV and generate department summary",
            difficulty=difficulty,
            goal=textwrap.dedent("""\
                Process the employees.csv file and create two output files:

                1. active_employees.json - JSON array of only active employees,
                   sorted by salary descending, with fields: name, department, salary

                2. department_summary.csv - CSV with columns: department, headcount,
                   avg_salary, total_salary (only counting active employees)
                   Sort by department name alphabetically.
            """),
            environment=EnvironmentSetup(
                env_type="directory",
                seed_files={"employees.csv": csv_data},
            ),
            ground_truth="active_employees.json has 8 entries (Henry first at 110000), department_summary.csv has 3 rows with correct aggregations",
            eval_spec=EvalSpec(
                method=EvalMethod.COMPOSITE,
                sub_evals=[
                    {"method": "file_exists", "expected_files": ["active_employees.json", "department_summary.csv"]},
                    {"method": "command_output",
                     "check_command": "python3 -c \"import json; d=json.load(open('active_employees.json')); assert len(d)==8; assert d[0]['name']=='Henry'; assert d[0]['salary']==110000; print('json_ok')\"",
                     "output_contains": ["json_ok"]},
                    {"method": "command_output",
                     "check_command": "grep -c ',' department_summary.csv",
                     "output_contains": []},
                ]
            ),
            capabilities=[
                Capability.CODE_WRITING,
                Capability.SCRIPT_WRITING,
                Capability.SHELL_COMMANDS,
                Capability.FILE_CREATION,
            ],
            source="local_ops_generator:data_transformation",
            estimated_minutes=5,
        )

    def _permission_fix(self, difficulty: str) -> Task:
        """Task: fix file permissions for a deployment setup."""
        return Task(
            category=TaskCategory.LOCAL_OPS,
            title="Fix script permissions and shebang lines",
            difficulty=difficulty,
            goal=textwrap.dedent("""\
                The scripts/ directory contains several scripts that can't be executed.

                1. Add missing shebang lines (#!/bin/bash for .sh, #!/usr/bin/env python3 for .py)
                2. Make all scripts executable (chmod +x)
                3. Create a run_all.sh that executes each script in alphabetical order
                   and reports success/failure for each
            """),
            environment=EnvironmentSetup(
                env_type="directory",
                seed_files={
                    "scripts/setup.sh": "echo 'Setting up...'\nmkdir -p /tmp/test_app_$$\necho 'Done'\n",
                    "scripts/check.py": "import sys\nprint('Checks passed')\nsys.exit(0)\n",
                    "scripts/deploy.sh": "echo 'Deploying...'\necho 'Deployed'\n",
                    "scripts/validate.py": "print('Validation OK')\n",
                },
            ),
            ground_truth="All scripts have shebangs, are executable, run_all.sh created and works",
            eval_spec=EvalSpec(
                method=EvalMethod.COMPOSITE,
                sub_evals=[
                    {"method": "command_output",
                     "check_command": "head -1 scripts/setup.sh",
                     "output_contains": ["#!/"]},
                    {"method": "command_output",
                     "check_command": "head -1 scripts/check.py",
                     "output_contains": ["#!/"]},
                    {"method": "file_exists", "expected_files": ["scripts/run_all.sh"]},
                    {"method": "command_output",
                     "check_command": "bash scripts/run_all.sh 2>&1",
                     "output_not_contains": ["Permission denied"]},
                ]
            ),
            capabilities=[
                Capability.SHELL_COMMANDS,
                Capability.SCRIPT_WRITING,
                Capability.FILE_CREATION,
                Capability.CODE_EDITING,
            ],
            source="local_ops_generator:permission_fix",
            estimated_minutes=3,
        )

    def _build_script_creation(self, difficulty: str) -> Task:
        """Task: create a Makefile for a project."""
        return Task(
            category=TaskCategory.LOCAL_OPS,
            title="Create Makefile for Python project",
            difficulty=difficulty,
            goal=textwrap.dedent("""\
                Create a Makefile for this Python project with the following targets:

                - install: install dependencies from requirements.txt
                - test: run pytest
                - lint: run flake8 on src/
                - format: run black on src/ and tests/
                - clean: remove __pycache__, .pytest_cache, *.pyc
                - all: run install, lint, test (in that order)

                The default target should be 'all'.
                Each target should print what it's doing.
            """),
            environment=EnvironmentSetup(
                env_type="directory",
                seed_files={
                    "src/app.py": "def hello():\n    return 'world'\n",
                    "tests/test_app.py": "from src.app import hello\ndef test_hello():\n    assert hello() == 'world'\n",
                    "requirements.txt": "pytest\nflake8\nblack\n",
                },
                setup_commands=["pip install pytest flake8 black 2>/dev/null || true"],
            ),
            ground_truth="Makefile with all targets working correctly",
            eval_spec=EvalSpec(
                method=EvalMethod.COMPOSITE,
                sub_evals=[
                    {"method": "file_exists", "expected_files": ["Makefile"]},
                    {"method": "file_content", "expected_content": {
                        "Makefile": "test:",
                    }},
                    {"method": "command_output",
                     "check_command": "make clean 2>&1",
                     "output_not_contains": ["Error", "No rule"]},
                ]
            ),
            capabilities=[
                Capability.BUILD_SYSTEMS,
                Capability.FILE_CREATION,
                Capability.SCRIPT_WRITING,
                Capability.SHELL_COMMANDS,
            ],
            source="local_ops_generator:build_script_creation",
            estimated_minutes=5,
        )

    def _env_setup(self, difficulty: str) -> Task:
        """Task: create a proper .env setup with validation."""
        return Task(
            category=TaskCategory.LOCAL_OPS,
            title="Create .env template and validation script",
            difficulty=difficulty,
            goal=textwrap.dedent("""\
                The app.py reads environment variables but has no .env file or documentation.

                1. Read app.py to find all environment variables it uses
                2. Create a .env.example file with all variables and sensible defaults
                3. Create a validate_env.py script that:
                   - Reads .env.example to find required variables
                   - Checks if each is set in the current environment or in a .env file
                   - Reports which are missing
                   - Exits 0 if all present, 1 if any missing
                4. Create the actual .env file with working values
            """),
            environment=EnvironmentSetup(
                env_type="directory",
                seed_files={
                    "app.py": textwrap.dedent("""\
                        import os
                        DB_HOST = os.environ['DB_HOST']
                        DB_PORT = int(os.environ.get('DB_PORT', '5432'))
                        DB_NAME = os.environ['DB_NAME']
                        SECRET_KEY = os.environ['SECRET_KEY']
                        DEBUG = os.environ.get('DEBUG', 'false').lower() == 'true'
                        API_KEY = os.environ.get('API_KEY', '')
                        LOG_LEVEL = os.environ.get('LOG_LEVEL', 'INFO')
                    """),
                },
            ),
            ground_truth=".env.example lists all 7 vars, .env has working values, validate_env.py correctly validates",
            eval_spec=EvalSpec(
                method=EvalMethod.COMPOSITE,
                sub_evals=[
                    {"method": "file_exists", "expected_files": [".env.example", ".env", "validate_env.py"]},
                    {"method": "file_content", "expected_content": {
                        ".env.example": "DB_HOST",
                        ".env.example": "SECRET_KEY",
                        ".env": "DB_HOST",
                    }},
                    {"method": "command_output",
                     "check_command": "set -a && . ./.env && set +a && python3 validate_env.py 2>&1; echo exit_$?",
                     "output_contains": ["exit_0"]},
                ]
            ),
            capabilities=[
                Capability.CODE_READING,
                Capability.CONFIG_EDITING,
                Capability.FILE_CREATION,
                Capability.SCRIPT_WRITING,
                Capability.CODE_WRITING,
            ],
            source="local_ops_generator:env_setup",
            estimated_minutes=5,
        )

    def _batch_rename(self, difficulty: str) -> Task:
        """Task: rename files following a naming convention."""
        seed_files = {}
        names = [
            "MyComponent.js", "userProfile.js", "API_handler.js",
            "data-utils.js", "CONSTANTS.js", "helperFunctions.js",
            "MainPage.test.js", "userProfile.test.js",
        ]
        for name in names:
            seed_files[f"src/{name}"] = f"// {name}\nmodule.exports = {{}};\n"

        return Task(
            category=TaskCategory.LOCAL_OPS,
            title="Batch rename files to kebab-case convention",
            difficulty=difficulty,
            goal=textwrap.dedent("""\
                The src/ directory has JavaScript files with inconsistent naming.
                Rename ALL .js files (but not .test.js files) to kebab-case:
                - MyComponent.js -> my-component.js
                - userProfile.js -> user-profile.js
                - API_handler.js -> api-handler.js
                - CONSTANTS.js -> constants.js
                - helperFunctions.js -> helper-functions.js
                - data-utils.js stays the same (already kebab-case)

                For .test.js files, rename the base part to match:
                - MainPage.test.js -> main-page.test.js
                - userProfile.test.js -> user-profile.test.js

                Update any requires/imports within files if they reference renamed files.
            """),
            environment=EnvironmentSetup(
                env_type="directory",
                seed_files=seed_files,
            ),
            ground_truth="All files renamed to kebab-case, references updated",
            eval_spec=EvalSpec(
                method=EvalMethod.COMPOSITE,
                sub_evals=[
                    {"method": "file_exists", "expected_files": [
                        "src/my-component.js", "src/user-profile.js",
                        "src/api-handler.js", "src/constants.js",
                        "src/helper-functions.js", "src/data-utils.js",
                        "src/main-page.test.js", "src/user-profile.test.js",
                    ]},
                    {"method": "command_output",
                     "check_command": "test ! -f src/MyComponent.js && test ! -f src/CONSTANTS.js && echo 'old_removed'",
                     "output_contains": ["old_removed"]},
                ]
            ),
            capabilities=[
                Capability.SHELL_COMMANDS,
                Capability.FILE_SEARCH,
                Capability.CODE_EDITING,
                Capability.SCRIPT_WRITING,
            ],
            source="local_ops_generator:batch_rename",
            estimated_minutes=5,
        )
