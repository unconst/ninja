"""
Documentation reconciliation task generator.

Generates tasks involving reading documentation, comparing it with code,
finding discrepancies, and updating either docs or code to match.
Tests doc_reading, code_search, symbol_lookup, and explanation capabilities.
"""

import textwrap
from ..schema import (
    Task, TaskCategory, Capability, EvalMethod,
    EnvironmentSetup, EvalSpec
)
from .base import TaskGenerator


class DocsReconciliationGenerator(TaskGenerator):
    """Generates documentation vs code reconciliation tasks."""

    @property
    def category(self) -> TaskCategory:
        return TaskCategory.DOCS_RECONCILIATION

    def generate(self, count: int = 5, difficulty: str = "medium") -> list[Task]:
        generators = [
            self._outdated_readme,
            self._wrong_api_docs,
            self._missing_docstrings,
            self._changelog_from_diff,
            self._config_docs_mismatch,
            self._generate_api_reference,
        ]
        tasks = []
        for i in range(count):
            gen = generators[i % len(generators)]
            tasks.append(gen(difficulty))
        return tasks

    def _outdated_readme(self, difficulty: str) -> Task:
        """Task: fix a README that no longer matches the code."""
        return Task(
            category=TaskCategory.DOCS_RECONCILIATION,
            title="Fix outdated README to match current code",
            difficulty=difficulty,
            goal=textwrap.dedent("""\
                The README.md describes the project but is outdated. Read the actual
                source code and update the README to accurately reflect:

                1. The actual CLI arguments (check main.py's argparse setup)
                2. The actual function names and signatures
                3. The correct installation steps
                4. Remove references to features that don't exist in the code
                5. Add documentation for features in the code but not in the README

                Keep the README's style and tone. Only fix inaccuracies.
            """),
            environment=EnvironmentSetup(
                env_type="directory",
                seed_files={
                    "README.md": textwrap.dedent("""\
                        # DataProcessor

                        A tool for processing CSV files.

                        ## Installation
                        ```
                        pip install dataprocessor
                        pip install -r requirements.txt
                        ```

                        ## Usage
                        ```
                        python main.py --input data.csv --output result.csv
                        python main.py --input data.csv --format json
                        python main.py --validate data.csv
                        ```

                        ## Features
                        - CSV to JSON conversion
                        - Data validation
                        - Column filtering with --columns flag
                        - Row sampling with --sample flag
                        - Export to Excel format

                        ## API
                        ```python
                        from processor import DataProcessor
                        dp = DataProcessor()
                        dp.load("data.csv")
                        dp.filter(columns=["name", "age"])
                        dp.export("output.json")
                        ```
                    """),
                    "main.py": textwrap.dedent("""\
                        import argparse
                        from processor import load_csv, transform, save_output

                        def main():
                            parser = argparse.ArgumentParser(description='Process CSV data')
                            parser.add_argument('input', help='Input CSV file')
                            parser.add_argument('-o', '--output', help='Output file path')
                            parser.add_argument('-f', '--format', choices=['csv', 'json'], default='csv',
                                              help='Output format (default: csv)')
                            parser.add_argument('--sort', help='Sort by column name')
                            parser.add_argument('--filter', help='Filter expression (col=value)')
                            parser.add_argument('--stats', action='store_true', help='Show column statistics')
                            args = parser.parse_args()

                            data = load_csv(args.input)

                            if args.filter:
                                col, val = args.filter.split('=')
                                data = [r for r in data if r.get(col) == val]

                            if args.sort:
                                data = sorted(data, key=lambda r: r.get(args.sort, ''))

                            if args.stats:
                                from processor import print_stats
                                print_stats(data)
                                return

                            output = transform(data, args.format)
                            if args.output:
                                save_output(output, args.output)
                            else:
                                print(output)

                        if __name__ == '__main__':
                            main()
                    """),
                    "processor.py": textwrap.dedent("""\
                        import csv
                        import json
                        import io

                        def load_csv(filepath):
                            with open(filepath) as f:
                                return list(csv.DictReader(f))

                        def transform(data, format='csv'):
                            if format == 'json':
                                return json.dumps(data, indent=2)
                            output = io.StringIO()
                            if data:
                                writer = csv.DictWriter(output, fieldnames=data[0].keys())
                                writer.writeheader()
                                writer.writerows(data)
                            return output.getvalue()

                        def save_output(content, filepath):
                            with open(filepath, 'w') as f:
                                f.write(content)

                        def print_stats(data):
                            if not data:
                                print("No data")
                                return
                            for col in data[0].keys():
                                values = [r[col] for r in data]
                                print(f"{col}: {len(values)} values, {len(set(values))} unique")
                    """),
                    "requirements.txt": "# no external dependencies needed\n",
                },
            ),
            ground_truth="README updated: positional input arg (not --input), no --validate flag, no --columns/--sample flags, no Excel export, has --sort/--filter/--stats. API is functions not class. Installation is just 'pip install -r requirements.txt'.",
            eval_spec=EvalSpec(
                method=EvalMethod.COMPOSITE,
                sub_evals=[
                    {"method": "file_content", "expected_content": {
                        "README.md": "--sort",  # must mention sort
                    }},
                    {"method": "command_output",
                     "check_command": "! grep -q '\\-\\-validate' README.md && ! grep -q 'Excel' README.md && echo 'removed_ok'",
                     "output_contains": ["removed_ok"]},
                    {"method": "command_output",
                     "check_command": "grep -q '\\-\\-filter' README.md && grep -q '\\-\\-stats' README.md && echo 'added_ok'",
                     "output_contains": ["added_ok"]},
                ]
            ),
            capabilities=[
                Capability.DOC_READING,
                Capability.CODE_READING,
                Capability.CODE_EDITING,
                Capability.SYMBOL_LOOKUP,
                Capability.MULTI_FILE_REASONING,
                Capability.EXPLANATION,
            ],
            source="docs_reconciliation_generator:outdated_readme",
            estimated_minutes=8,
        )

    def _wrong_api_docs(self, difficulty: str) -> Task:
        """Task: fix incorrect API documentation."""
        return Task(
            category=TaskCategory.DOCS_RECONCILIATION,
            title="Fix incorrect API documentation comments",
            difficulty=difficulty,
            goal=textwrap.dedent("""\
                The api.py module has docstrings that don't match the actual behavior.
                Read each function, understand what it ACTUALLY does, and fix the
                docstrings to accurately describe:
                - What the function does
                - Parameter names and types
                - Return values
                - Any exceptions raised

                Do NOT change the code behavior, only fix the documentation.
                Run the verify_docs.py script when done to check your fixes.
            """),
            environment=EnvironmentSetup(
                env_type="directory",
                seed_files={
                    "api.py": textwrap.dedent('''\
                        def calculate_discount(price, percentage, max_discount=None):
                            """Calculate tax on a given price.

                            Args:
                                price: The base price (string)
                                rate: Tax rate as decimal (e.g., 0.08 for 8%)

                            Returns:
                                The price with tax added

                            Raises:
                                Nothing
                            """
                            discount = price * (percentage / 100)
                            if max_discount is not None and discount > max_discount:
                                discount = max_discount
                            return price - discount

                        def merge_configs(*configs):
                            """Combine two configuration dictionaries.

                            The first config takes precedence over the second.

                            Args:
                                config_a: Primary configuration dict
                                config_b: Secondary configuration dict

                            Returns:
                                Merged configuration as a list
                            """
                            result = {}
                            for config in configs:
                                result.update(config)
                            return result

                        def parse_range(range_str):
                            """Parse a single number from a string.

                            Args:
                                range_str: A numeric string

                            Returns:
                                An integer

                            Example:
                                parse_range("42") -> 42
                            """
                            if '-' in range_str:
                                start, end = range_str.split('-')
                                return list(range(int(start), int(end) + 1))
                            return [int(range_str)]
                    '''),
                    "verify_docs.py": textwrap.dedent("""\
                        import ast
                        import sys

                        with open('api.py') as f:
                            tree = ast.parse(f.read())

                        issues = []
                        for node in ast.walk(tree):
                            if isinstance(node, ast.FunctionDef):
                                ds = ast.get_docstring(node)
                                if not ds:
                                    issues.append(f"{node.name}: missing docstring")
                                    continue
                                # Check param names match
                                actual_params = [a.arg for a in node.args.args]
                                for param in actual_params:
                                    if param not in ds:
                                        issues.append(f"{node.name}: param '{param}' not in docstring")

                        if issues:
                            for i in issues:
                                print(f"ISSUE: {i}")
                            sys.exit(1)
                        else:
                            print("All docstrings verified!")
                            sys.exit(0)
                    """),
                },
            ),
            ground_truth="calculate_discount docs: calculates discount not tax, params are price/percentage/max_discount, returns discounted price, raises nothing. merge_configs: accepts *configs (any number), later configs override earlier ones, returns dict. parse_range: parses range string '1-5' to list, not single number.",
            eval_spec=EvalSpec(
                method=EvalMethod.COMPOSITE,
                sub_evals=[
                    {"method": "command_output",
                     "check_command": "python3 verify_docs.py 2>&1",
                     "output_contains": ["verified"]},
                    {"method": "command_output",
                     "check_command": "grep -c 'discount' api.py",
                     "output_contains": []},  # just ensure it runs
                    {"method": "command_output",
                     # Ensure the function code wasn't changed
                     "check_command": "python3 -c \"from api import calculate_discount; assert calculate_discount(100, 20) == 80; print('code_intact')\"",
                     "output_contains": ["code_intact"]},
                ]
            ),
            capabilities=[
                Capability.DOC_READING,
                Capability.CODE_READING,
                Capability.CODE_EDITING,
                Capability.SYMBOL_LOOKUP,
                Capability.EXPLANATION,
            ],
            source="docs_reconciliation_generator:wrong_api_docs",
            estimated_minutes=8,
        )

    def _missing_docstrings(self, difficulty: str) -> Task:
        """Task: add missing documentation to undocumented code."""
        return Task(
            category=TaskCategory.DOCS_RECONCILIATION,
            title="Add comprehensive docstrings to undocumented code",
            difficulty=difficulty,
            goal=textwrap.dedent("""\
                The utils.py module has no docstrings at all. Read the code carefully
                and add accurate docstrings to:

                1. The module itself (module-level docstring)
                2. Every class
                3. Every public method/function
                4. Include: description, Args, Returns, Raises, Examples

                Follow Google-style docstring format. Do NOT change any code logic.
                Verify by running: python3 -c "import utils; help(utils)"
            """),
            environment=EnvironmentSetup(
                env_type="directory",
                seed_files={
                    "utils.py": textwrap.dedent('''\
                        import re
                        from collections import defaultdict

                        class TextAnalyzer:
                            def __init__(self, text):
                                self.text = text
                                self._words = None

                            @property
                            def words(self):
                                if self._words is None:
                                    self._words = re.findall(r\'\\b\\w+\\b\', self.text.lower())
                                return self._words

                            def word_frequency(self):
                                freq = defaultdict(int)
                                for word in self.words:
                                    freq[word] += 1
                                return dict(sorted(freq.items(), key=lambda x: -x[1]))

                            def sentences(self):
                                return [s.strip() for s in re.split(r\'[.!?]+\', self.text) if s.strip()]

                            def search(self, pattern):
                                return re.findall(pattern, self.text)

                            def summary(self, max_sentences=3):
                                sents = self.sentences()
                                return \'. \'.join(sents[:max_sentences]) + \'.\' if sents else \'\'


                        def slugify(text):
                            text = text.lower().strip()
                            text = re.sub(r\'[^\\w\\s-]\', \'\', text)
                            text = re.sub(r\'[\\s_-]+\', \'-\', text)
                            return text.strip(\'-\')

                        def extract_emails(text):
                            return re.findall(r\'[\\w.+-]+@[\\w-]+\\.[\\w.-]+\', text)

                        def mask_sensitive(text, patterns=None):
                            if patterns is None:
                                patterns = [r\'\\b\\d{3}-\\d{2}-\\d{4}\\b\', r\'\\b\\d{16}\\b\']
                            for pattern in patterns:
                                text = re.sub(pattern, \'***REDACTED***\', text)
                            return text
                    '''),
                },
            ),
            ground_truth="All functions and class have Google-style docstrings with accurate descriptions, Args, Returns, and Examples sections",
            eval_spec=EvalSpec(
                method=EvalMethod.COMPOSITE,
                sub_evals=[
                    {"method": "command_output",
                     "check_command": "python3 -c \"import utils; assert utils.TextAnalyzer.__doc__; assert utils.slugify.__doc__; assert utils.extract_emails.__doc__; print('docs_present')\"",
                     "output_contains": ["docs_present"]},
                    {"method": "command_output",
                     "check_command": "python3 -c \"from utils import TextAnalyzer; t=TextAnalyzer('Hello world. Test.'); assert t.word_frequency()['hello']==1; assert t.sentences()==['Hello world', 'Test']; print('code_intact')\"",
                     "output_contains": ["code_intact"]},
                    {"method": "command_output",
                     "check_command": "python3 -c \"from utils import slugify; assert slugify('Hello World!')==('hello-world'); print('slugify_ok')\"",
                     "output_contains": ["slugify_ok"]},
                ]
            ),
            capabilities=[
                Capability.CODE_READING,
                Capability.CODE_EDITING,
                Capability.SYMBOL_LOOKUP,
                Capability.EXPLANATION,
                Capability.DOC_READING,
            ],
            source="docs_reconciliation_generator:missing_docstrings",
            estimated_minutes=8,
        )

    def _changelog_from_diff(self, difficulty: str) -> Task:
        """Task: generate a changelog from git-style diffs."""
        return Task(
            category=TaskCategory.DOCS_RECONCILIATION,
            title="Generate changelog from code diffs",
            difficulty=difficulty,
            goal=textwrap.dedent("""\
                The changes/ directory contains diff files showing recent changes to the project.
                Read each diff carefully and produce a CHANGELOG.md that:

                1. Groups changes by type: Added, Changed, Fixed, Removed
                2. Describes each change in user-friendly language (not technical jargon)
                3. References the affected component/module
                4. Uses Keep a Changelog format (https://keepachangelog.com)

                Read the diffs, understand the code changes, and write clear descriptions.
            """),
            environment=EnvironmentSetup(
                env_type="directory",
                seed_files={
                    "changes/001_add_search.diff": textwrap.dedent("""\
                        --- a/app/routes.py
                        +++ b/app/routes.py
                        @@ -15,6 +15,18 @@ def list_users():
                             return jsonify(users)

                        +@app.route('/api/search')
                        +def search():
                        +    query = request.args.get('q', '')
                        +    results = db.search(query)
                        +    return jsonify(results)
                        +
                        +@app.route('/api/search/advanced')
                        +def advanced_search():
                        +    filters = request.json
                        +    results = db.advanced_search(filters)
                        +    return jsonify(results)
                    """),
                    "changes/002_fix_auth.diff": textwrap.dedent("""\
                        --- a/app/auth.py
                        +++ b/app/auth.py
                        @@ -22,7 +22,8 @@ def verify_token(token):
                        -    if token.expiry < time.time():
                        +    if token.expiry <= time.time():
                        +        logger.warning(f"Expired token attempt: {token.user_id}")
                             return None

                        @@ -45,6 +46,9 @@ def login(username, password):
                        +    if not rate_limiter.check(username):
                        +        raise TooManyAttemptsError("Too many login attempts")
                        +
                             user = db.get_user(username)
                    """),
                    "changes/003_remove_legacy.diff": textwrap.dedent("""\
                        --- a/app/compat.py
                        +++ /dev/null
                        @@ -1,35 +0,0 @@
                        -# Legacy compatibility layer
                        -# Deprecated since v2.0
                        -
                        -def old_api_handler(request):
                        -    '''Handle requests in v1 format.'''
                        -    return convert_to_v2(request)
                        -
                        -def convert_to_v2(request):
                        -    return request
                    """),
                    "changes/004_update_config.diff": textwrap.dedent("""\
                        --- a/config.py
                        +++ b/config.py
                        @@ -5,8 +5,10 @@ class Config:
                        -    TIMEOUT = 30
                        +    TIMEOUT = 60
                        -    MAX_RETRIES = 3
                        +    MAX_RETRIES = 5
                        +    CACHE_TTL = 300
                        +    ENABLE_METRICS = True
                    """),
                },
            ),
            ground_truth="CHANGELOG.md with: Added (search endpoints, rate limiting, cache TTL, metrics), Changed (timeout 30->60, retries 3->5), Fixed (token expiry off-by-one, added expired token logging), Removed (legacy compatibility layer)",
            eval_spec=EvalSpec(
                method=EvalMethod.COMPOSITE,
                sub_evals=[
                    {"method": "file_exists", "expected_files": ["CHANGELOG.md"]},
                    {"method": "file_content", "expected_content": {
                        "CHANGELOG.md": "Added",
                    }},
                    {"method": "command_output",
                     "check_command": "grep -c -iE '(added|changed|fixed|removed)' CHANGELOG.md",
                     "output_contains": []},
                    {"method": "command_output",
                     "check_command": "grep -qi 'search' CHANGELOG.md && grep -qi 'legacy\\|compat' CHANGELOG.md && echo 'content_ok'",
                     "output_contains": ["content_ok"]},
                ]
            ),
            capabilities=[
                Capability.DOC_READING,
                Capability.CODE_READING,
                Capability.FILE_CREATION,
                Capability.EXPLANATION,
                Capability.SUMMARY_GENERATION,
                Capability.CODE_SEARCH,
            ],
            source="docs_reconciliation_generator:changelog_from_diff",
            estimated_minutes=8,
        )

    def _config_docs_mismatch(self, difficulty: str) -> Task:
        """Task: find discrepancies between config docs and actual config usage."""
        return Task(
            category=TaskCategory.DOCS_RECONCILIATION,
            title="Find and fix config documentation mismatches",
            difficulty=difficulty,
            goal=textwrap.dedent("""\
                The CONFIG.md documents all configuration options, but the code has evolved
                and the docs are now out of sync.

                1. Read CONFIG.md carefully
                2. Search the code to find all actual config variable usage
                3. Create a discrepancies.json file listing:
                   - "documented_not_used": config vars in docs but not in code
                   - "used_not_documented": config vars in code but not in docs
                   - "wrong_defaults": vars where documented default differs from code default
                4. Update CONFIG.md to be correct

                Do NOT change the code, only fix the documentation.
            """),
            environment=EnvironmentSetup(
                env_type="directory",
                seed_files={
                    "CONFIG.md": textwrap.dedent("""\
                        # Configuration Guide

                        ## Database
                        | Variable | Default | Description |
                        |----------|---------|-------------|
                        | DB_HOST | localhost | Database host |
                        | DB_PORT | 5432 | Database port |
                        | DB_NAME | myapp | Database name |
                        | DB_POOL_SIZE | 5 | Connection pool size |
                        | DB_TIMEOUT | 10 | Query timeout in seconds |

                        ## Server
                        | Variable | Default | Description |
                        |----------|---------|-------------|
                        | SERVER_HOST | 0.0.0.0 | Server bind address |
                        | SERVER_PORT | 8080 | Server port |
                        | WORKERS | 4 | Number of worker processes |
                        | DEBUG_MODE | false | Enable debug mode |

                        ## Cache
                        | Variable | Default | Description |
                        |----------|---------|-------------|
                        | CACHE_BACKEND | memory | Cache backend (memory/redis) |
                        | CACHE_TTL | 300 | Cache TTL in seconds |
                    """),
                    "app/config.py": textwrap.dedent("""\
                        import os

                        DB_HOST = os.environ.get('DB_HOST', 'localhost')
                        DB_PORT = int(os.environ.get('DB_PORT', '5432'))
                        DB_NAME = os.environ.get('DB_NAME', 'myapp')
                        DB_POOL_SIZE = int(os.environ.get('DB_POOL_SIZE', '10'))  # docs say 5
                        # DB_TIMEOUT was removed in v3

                        SERVER_HOST = os.environ.get('SERVER_HOST', '0.0.0.0')
                        SERVER_PORT = int(os.environ.get('SERVER_PORT', '3000'))  # docs say 8080
                        DEBUG_MODE = os.environ.get('DEBUG_MODE', 'false').lower() == 'true'
                        # WORKERS was replaced by MAX_THREADS
                        MAX_THREADS = int(os.environ.get('MAX_THREADS', '8'))

                        CACHE_BACKEND = os.environ.get('CACHE_BACKEND', 'redis')  # docs say memory
                        CACHE_TTL = int(os.environ.get('CACHE_TTL', '300'))

                        # New in v3
                        LOG_LEVEL = os.environ.get('LOG_LEVEL', 'INFO')
                        RATE_LIMIT = int(os.environ.get('RATE_LIMIT', '100'))
                    """),
                },
            ),
            ground_truth="documented_not_used: DB_TIMEOUT, WORKERS. used_not_documented: MAX_THREADS, LOG_LEVEL, RATE_LIMIT. wrong_defaults: DB_POOL_SIZE (5->10), SERVER_PORT (8080->3000), CACHE_BACKEND (memory->redis).",
            eval_spec=EvalSpec(
                method=EvalMethod.COMPOSITE,
                sub_evals=[
                    {"method": "file_exists", "expected_files": ["discrepancies.json"]},
                    {"method": "command_output",
                     "check_command": "python3 -c \"import json; d=json.load(open('discrepancies.json')); assert len(d.get('documented_not_used',[]))>=2; assert len(d.get('used_not_documented',[]))>=2; print('discrepancies_found')\"",
                     "output_contains": ["discrepancies_found"]},
                    {"method": "command_output",
                     "check_command": "grep -q 'MAX_THREADS' CONFIG.md && grep -q 'LOG_LEVEL' CONFIG.md && echo 'docs_updated'",
                     "output_contains": ["docs_updated"]},
                    {"method": "command_output",
                     "check_command": "grep -q '3000' CONFIG.md && echo 'port_fixed'",
                     "output_contains": ["port_fixed"]},
                ]
            ),
            capabilities=[
                Capability.DOC_READING,
                Capability.CODE_READING,
                Capability.CODE_SEARCH,
                Capability.CODE_EDITING,
                Capability.FILE_CREATION,
                Capability.MULTI_FILE_REASONING,
                Capability.SYMBOL_LOOKUP,
            ],
            source="docs_reconciliation_generator:config_docs_mismatch",
            estimated_minutes=10,
        )

    def _generate_api_reference(self, difficulty: str) -> Task:
        """Task: generate API reference docs from code."""
        return Task(
            category=TaskCategory.DOCS_RECONCILIATION,
            title="Generate API reference from source code",
            difficulty=difficulty,
            goal=textwrap.dedent("""\
                The library/ directory contains a Python package with some docstrings.
                Generate a comprehensive API_REFERENCE.md that documents:

                1. All public classes and their methods
                2. All public functions
                3. Constructor arguments and types
                4. Method signatures with argument descriptions
                5. Return types
                6. Usage examples for key functions

                Read ALL source files to ensure complete coverage.
                Use markdown with proper code blocks for examples.
            """),
            environment=EnvironmentSetup(
                env_type="directory",
                seed_files={
                    "library/__init__.py": "from .core import EventEmitter\nfrom .utils import retry, cached\n",
                    "library/core.py": textwrap.dedent("""\
                        class EventEmitter:
                            \"\"\"Simple event emitter supporting subscribe/emit pattern.\"\"\"

                            def __init__(self):
                                self._handlers = {}

                            def on(self, event, handler):
                                \"\"\"Register a handler for an event.\"\"\"
                                if event not in self._handlers:
                                    self._handlers[event] = []
                                self._handlers[event].append(handler)
                                return self

                            def off(self, event, handler=None):
                                \"\"\"Remove handler(s) for an event.\"\"\"
                                if handler is None:
                                    self._handlers.pop(event, None)
                                elif event in self._handlers:
                                    self._handlers[event] = [h for h in self._handlers[event] if h != handler]

                            def emit(self, event, *args, **kwargs):
                                \"\"\"Emit an event, calling all registered handlers.\"\"\"
                                for handler in self._handlers.get(event, []):
                                    handler(*args, **kwargs)
                    """),
                    "library/utils.py": textwrap.dedent("""\
                        import time
                        import functools

                        def retry(max_attempts=3, delay=1.0, exceptions=(Exception,)):
                            \"\"\"Decorator that retries a function on failure.\"\"\"
                            def decorator(func):
                                @functools.wraps(func)
                                def wrapper(*args, **kwargs):
                                    for attempt in range(max_attempts):
                                        try:
                                            return func(*args, **kwargs)
                                        except exceptions:
                                            if attempt == max_attempts - 1:
                                                raise
                                            time.sleep(delay)
                                return wrapper
                            return decorator

                        def cached(ttl=60):
                            \"\"\"Decorator that caches function results with TTL.\"\"\"
                            def decorator(func):
                                cache = {}
                                @functools.wraps(func)
                                def wrapper(*args):
                                    key = args
                                    now = time.time()
                                    if key in cache and now - cache[key][1] < ttl:
                                        return cache[key][0]
                                    result = func(*args)
                                    cache[key] = (result, now)
                                    return result
                                wrapper.cache_clear = lambda: cache.clear()
                                return wrapper
                            return decorator
                    """),
                },
            ),
            ground_truth="API_REFERENCE.md documents EventEmitter (on/off/emit), retry decorator, cached decorator with all params and examples",
            eval_spec=EvalSpec(
                method=EvalMethod.COMPOSITE,
                sub_evals=[
                    {"method": "file_exists", "expected_files": ["API_REFERENCE.md"]},
                    {"method": "command_output",
                     "check_command": "grep -q 'EventEmitter' API_REFERENCE.md && grep -q 'retry' API_REFERENCE.md && grep -q 'cached' API_REFERENCE.md && echo 'all_documented'",
                     "output_contains": ["all_documented"]},
                    {"method": "command_output",
                     "check_command": "grep -c '```' API_REFERENCE.md",
                     "output_contains": []},  # ensure code blocks exist
                ]
            ),
            capabilities=[
                Capability.CODE_READING,
                Capability.DOC_READING,
                Capability.FILE_CREATION,
                Capability.SYMBOL_LOOKUP,
                Capability.EXPLANATION,
                Capability.SUMMARY_GENERATION,
                Capability.CODE_SEARCH,
            ],
            source="docs_reconciliation_generator:generate_api_reference",
            estimated_minutes=10,
        )
