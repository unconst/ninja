"""
Web search / information synthesis task generator.

Since agents in eval don't have real web access, these tasks simulate
web-search-like scenarios: given a set of "downloaded" reference docs,
blog posts, or API specs, the agent must search through them, synthesize
information, and produce a working solution or report.

Tests: web_fetch-like reading, doc_reading, summary_generation, explanation.
"""

import textwrap
from ..schema import (
    Task, TaskCategory, Capability, EvalMethod,
    EnvironmentSetup, EvalSpec
)
from .base import TaskGenerator


class WebSearchGenerator(TaskGenerator):
    """Generates tasks requiring information synthesis from reference materials."""

    @property
    def category(self) -> TaskCategory:
        return TaskCategory.WEB_SEARCH

    def generate(self, count: int = 5, difficulty: str = "medium") -> list[Task]:
        generators = [
            self._api_migration_guide,
            self._dependency_vulnerability,
            self._config_from_docs,
            self._changelog_impact_analysis,
            self._error_from_docs,
            self._build_system_setup,
        ]

        tasks = []
        for i in range(count):
            gen = generators[i % len(generators)]
            task = gen(difficulty)
            tasks.append(task)
        return tasks

    def _api_migration_guide(self, difficulty: str) -> Task:
        """Task: migrate code using API migration guide docs."""
        return Task(
            category=TaskCategory.WEB_SEARCH,
            title="Migrate API client using migration guide",
            difficulty=difficulty,
            goal=textwrap.dedent("""\
                The `client.py` uses API v1, which is deprecated. A migration guide
                is available in `docs/migration_v1_to_v2.md`. Update the client
                to use the v2 API.

                After migration, run `python3 test_client.py` — it should print
                "All migration tests passed."
            """),
            environment=EnvironmentSetup(
                env_type="directory",
                seed_files={
                    "docs/migration_v1_to_v2.md": textwrap.dedent("""\
                        # API Migration Guide: v1 → v2

                        ## Breaking Changes

                        ### Authentication
                        - v1: `client.auth(api_key)` → v2: `client.authenticate(api_key, version="v2")`
                        - The `auth()` method is removed in v2

                        ### Endpoint Changes
                        - v1: `client.get(endpoint)` → v2: `client.request("GET", endpoint)`
                        - v1: `client.post(endpoint, data)` → v2: `client.request("POST", endpoint, body=data)`
                        - The `get()` and `post()` methods are removed in v2

                        ### Response Format
                        - v1: Returns raw data dict → v2: Returns `Response` object with `.data`, `.status`, `.headers`
                        - v1: `resp["users"]` → v2: `resp.data["users"]`
                        - v1: Errors raise `APIError` → v2: Errors raise `APIError` with `.code` and `.message` attrs

                        ### Configuration
                        - v1: `Client(base_url=...)` → v2: `Client(base_url=..., timeout=30)` (timeout now required)
                        - v1: No retry → v2: `Client(..., retries=3)` optional, defaults to 0

                        ### Pagination
                        - v1: `client.get("/users?page=1")` → v2: `client.paginate("/users", page_size=10)` returns iterator
                        - Or use `client.request("GET", "/users", params={"page": 1, "size": 10})`
                    """),
                    "api_sdk.py": textwrap.dedent("""\
                        # v2 API SDK (simplified)

                        class Response:
                            def __init__(self, data, status=200, headers=None):
                                self.data = data
                                self.status = status
                                self.headers = headers or {}

                        class APIError(Exception):
                            def __init__(self, code, message):
                                self.code = code
                                self.message = message
                                super().__init__(f"API Error {code}: {message}")

                        class Client:
                            def __init__(self, base_url, timeout=30, retries=0):
                                self.base_url = base_url
                                self.timeout = timeout
                                self.retries = retries
                                self._authenticated = False
                                self._data_store = {
                                    "/users": [{"id": 1, "name": "Alice"}, {"id": 2, "name": "Bob"}],
                                    "/items": [{"id": 1, "title": "Widget"}],
                                }

                            def authenticate(self, api_key, version="v2"):
                                if version != "v2":
                                    raise APIError(400, "Only v2 auth supported")
                                self._authenticated = True

                            def request(self, method, endpoint, body=None, params=None):
                                if not self._authenticated:
                                    raise APIError(401, "Not authenticated")
                                if method == "GET":
                                    data = self._data_store.get(endpoint, [])
                                    return Response(data, 200)
                                elif method == "POST":
                                    if body:
                                        return Response(body, 201)
                                    raise APIError(400, "No body")
                                raise APIError(405, f"Method {method} not allowed")

                            def paginate(self, endpoint, page_size=10):
                                data = self._data_store.get(endpoint, [])
                                for i in range(0, len(data), page_size):
                                    yield Response(data[i:i+page_size], 200)
                    """),
                    "client.py": textwrap.dedent("""\
                        # v1 API client — needs migration to v2
                        from api_sdk import Client

                        def get_all_users(api_key):
                            client = Client(base_url="http://api.example.com")
                            client.auth(api_key)  # v1 method
                            resp = client.get("/users")  # v1 method
                            return resp["users"] if "users" in resp else resp  # v1 format

                        def create_item(api_key, title):
                            client = Client(base_url="http://api.example.com")
                            client.auth(api_key)
                            resp = client.post("/items", {"title": title})  # v1 method
                            return resp

                        def run():
                            users = get_all_users("test-key")
                            print(f"Found {len(users)} users")
                            item = create_item("test-key", "New Widget")
                            print(f"Created item: {item}")
                    """),
                    "test_client.py": textwrap.dedent("""\
                        from client import get_all_users, create_item
                        from api_sdk import Response

                        def test_get_users():
                            users = get_all_users("test-key")
                            assert isinstance(users, list), f"Expected list, got {type(users)}"
                            assert len(users) == 2
                            assert users[0]["name"] == "Alice"

                        def test_create_item():
                            result = create_item("test-key", "New Widget")
                            # v2 returns Response object
                            assert isinstance(result, Response), f"Expected Response, got {type(result)}"
                            assert result.data["title"] == "New Widget"
                            assert result.status == 201

                        if __name__ == '__main__':
                            test_get_users()
                            test_create_item()
                            print("All migration tests passed.")
                    """),
                },
            ),
            ground_truth="Migrate client.py: 1) Client needs timeout param, 2) auth->authenticate with version='v2', 3) get->request('GET',...), 4) post->request('POST',...,body=), 5) responses are Response objects (.data)",
            eval_spec=EvalSpec(
                method=EvalMethod.COMMAND_OUTPUT,
                check_command="python3 test_client.py 2>&1",
                output_contains=["All migration tests passed"],
                output_not_contains=["Traceback", "Error", "AssertionError"],
            ),
            capabilities=[
                Capability.DOC_READING,
                Capability.CODE_READING,
                Capability.CODE_EDITING,
                Capability.MULTI_FILE_REASONING,
                Capability.SUMMARY_GENERATION,
            ],
            source="web_search_generator:api_migration_guide",
            estimated_minutes=8,
        )

    def _dependency_vulnerability(self, difficulty: str) -> Task:
        """Task: analyze security advisory and apply fix."""
        return Task(
            category=TaskCategory.WEB_SEARCH,
            title="Fix vulnerability based on security advisory",
            difficulty=difficulty,
            goal=textwrap.dedent("""\
                A security advisory (`docs/SECURITY_ADVISORY.md`) describes a vulnerability
                in the `sanitize` function. Read the advisory and apply the recommended fix.

                Run `python3 test_security.py` to verify the fix. It should print
                "All security tests passed."
            """),
            environment=EnvironmentSetup(
                env_type="directory",
                seed_files={
                    "docs/SECURITY_ADVISORY.md": textwrap.dedent("""\
                        # Security Advisory: XSS in sanitize_html()

                        ## Severity: HIGH

                        ## Affected Versions: < 2.0

                        ## Description
                        The `sanitize_html()` function in `sanitizer.py` fails to handle:
                        1. **Event handler attributes** (e.g., `onerror`, `onload`, `onclick`)
                        2. **javascript: URIs** in href/src attributes
                        3. **Case-insensitive bypasses** (e.g., `<SCRIPT>`, `<Script>`)

                        ## Proof of Concept
                        ```
                        sanitize_html('<img src=x onerror="alert(1)">')  # Not stripped
                        sanitize_html('<a href="javascript:alert(1)">click</a>')  # Not stripped
                        sanitize_html('<SCRIPT>alert(1)</SCRIPT>')  # Not caught
                        ```

                        ## Recommended Fix
                        1. Make tag matching case-insensitive
                        2. Strip ALL attributes matching `on\\w+` pattern (event handlers)
                        3. Remove `href` and `src` attributes containing `javascript:`
                        4. Allowlist approach: only keep `href` (non-JS), `src` (non-JS), `class`, `id`

                        ## Fixed in: 2.0 (apply patch below)
                    """),
                    "sanitizer.py": textwrap.dedent("""\
                        import re

                        ALLOWED_TAGS = {"b", "i", "em", "strong", "a", "p", "br", "ul", "li", "img"}

                        def sanitize_html(html):
                            \"\"\"Remove dangerous HTML tags and attributes.\"\"\"
                            # Remove script tags
                            html = re.sub(r'<script[^>]*>.*?</script>', '', html)

                            # Remove dangerous tags
                            html = re.sub(r'<(?!/?(?:' + '|'.join(ALLOWED_TAGS) + r')\\b)[^>]+>', '', html)

                            return html
                    """),
                    "test_security.py": textwrap.dedent("""\
                        from sanitizer import sanitize_html

                        def test_basic_tags_preserved():
                            assert "<b>" in sanitize_html("<b>bold</b>")
                            assert "<em>" in sanitize_html("<em>emphasis</em>")
                            assert "<a" in sanitize_html('<a href="/page">link</a>')

                        def test_script_removed():
                            result = sanitize_html('<script>alert(1)</script>')
                            assert "script" not in result.lower()

                        def test_case_insensitive_script():
                            result = sanitize_html('<SCRIPT>alert(1)</SCRIPT>')
                            assert "script" not in result.lower()
                            assert "alert" not in result

                        def test_event_handlers_stripped():
                            result = sanitize_html('<img src="photo.jpg" onerror="alert(1)">')
                            assert "onerror" not in result
                            assert "alert" not in result
                            # img tag itself should still be allowed
                            assert "<img" in result.lower() or "img" not in result.lower()

                        def test_javascript_uri_stripped():
                            result = sanitize_html('<a href="javascript:alert(1)">click</a>')
                            assert "javascript:" not in result.lower()

                        def test_mixed_case_event():
                            result = sanitize_html('<img src="x" OnError="alert(1)">')
                            assert "onerror" not in result.lower()
                            assert "alert" not in result

                        def test_safe_content_preserved():
                            safe = '<p>Hello <b>world</b>. Visit <a href="/home">home</a>.</p>'
                            result = sanitize_html(safe)
                            assert "Hello" in result
                            assert "<b>" in result
                            assert "home" in result

                        if __name__ == '__main__':
                            test_basic_tags_preserved()
                            test_script_removed()
                            test_case_insensitive_script()
                            test_event_handlers_stripped()
                            test_javascript_uri_stripped()
                            test_mixed_case_event()
                            test_safe_content_preserved()
                            print("All security tests passed.")
                    """),
                },
            ),
            ground_truth="Fix sanitizer.py: 1) re.IGNORECASE on script removal, 2) strip on\\w+=\"...\" attributes, 3) strip javascript: in href/src, 4) match SCRIPT/Script variants",
            eval_spec=EvalSpec(
                method=EvalMethod.COMMAND_OUTPUT,
                check_command="python3 test_security.py 2>&1",
                output_contains=["All security tests passed"],
                output_not_contains=["Traceback", "AssertionError"],
            ),
            capabilities=[
                Capability.DOC_READING,
                Capability.CODE_READING,
                Capability.CODE_EDITING,
                Capability.ROOT_CAUSE_ANALYSIS,
                Capability.HYPOTHESIS_TESTING,
            ],
            source="web_search_generator:dependency_vulnerability",
            estimated_minutes=8,
        )

    def _config_from_docs(self, difficulty: str) -> Task:
        """Task: configure a system using only documentation."""
        return Task(
            category=TaskCategory.WEB_SEARCH,
            title="Configure system from documentation",
            difficulty=difficulty,
            goal=textwrap.dedent("""\
                Set up the logging system by reading the documentation in `docs/logging.md`.
                Create the `logging_config.yaml` file and the `log_setup.py` module.

                Run `python3 test_logging.py` to verify. It should print
                "Logging configuration tests passed."
            """),
            environment=EnvironmentSetup(
                env_type="directory",
                seed_files={
                    "docs/logging.md": textwrap.dedent("""\
                        # Logging Configuration Guide

                        ## Config File Format (YAML)
                        The logging system reads `logging_config.yaml` from the project root.

                        ### Required Structure:
                        ```yaml
                        version: 1
                        formatters:
                          standard:
                            format: "%(asctime)s [%(levelname)s] %(name)s: %(message)s"
                          json:
                            format: "json"
                            fields: ["timestamp", "level", "logger", "message"]
                        handlers:
                          console:
                            type: stream
                            formatter: standard
                            level: INFO
                          file:
                            type: file
                            formatter: json
                            level: DEBUG
                            path: logs/app.log
                        loggers:
                          root:
                            level: DEBUG
                            handlers: [console, file]
                          app:
                            level: INFO
                            handlers: [console]
                          app.database:
                            level: WARNING
                            handlers: [console, file]
                        ```

                        ## Setup Module
                        Create `log_setup.py` with a `setup_logging()` function that:
                        1. Reads `logging_config.yaml`
                        2. Returns a dict with keys: `formatters`, `handlers`, `loggers`
                        3. Each logger should have `level` and `handlers` keys
                        4. The function should validate the config has `version: 1`
                    """),
                    "test_logging.py": textwrap.dedent("""\
                        import yaml
                        import os

                        def test_config_exists():
                            assert os.path.exists("logging_config.yaml"), "Config file not found"

                        def test_config_structure():
                            with open("logging_config.yaml") as f:
                                config = yaml.safe_load(f)
                            assert config["version"] == 1
                            assert "formatters" in config
                            assert "standard" in config["formatters"]
                            assert "json" in config["formatters"]
                            assert "handlers" in config
                            assert "console" in config["handlers"]
                            assert "file" in config["handlers"]
                            assert "loggers" in config
                            assert "root" in config["loggers"]

                        def test_handler_details():
                            with open("logging_config.yaml") as f:
                                config = yaml.safe_load(f)
                            console = config["handlers"]["console"]
                            assert console["type"] == "stream"
                            assert console["level"] == "INFO"
                            file_h = config["handlers"]["file"]
                            assert file_h["type"] == "file"
                            assert file_h["level"] == "DEBUG"
                            assert "path" in file_h

                        def test_logger_details():
                            with open("logging_config.yaml") as f:
                                config = yaml.safe_load(f)
                            root = config["loggers"]["root"]
                            assert root["level"] == "DEBUG"
                            assert "console" in root["handlers"]
                            assert "file" in root["handlers"]
                            db = config["loggers"]["app.database"]
                            assert db["level"] == "WARNING"

                        def test_setup_module():
                            from log_setup import setup_logging
                            result = setup_logging()
                            assert isinstance(result, dict)
                            assert "formatters" in result
                            assert "handlers" in result
                            assert "loggers" in result

                        if __name__ == '__main__':
                            test_config_exists()
                            test_config_structure()
                            test_handler_details()
                            test_logger_details()
                            test_setup_module()
                            print("Logging configuration tests passed.")
                    """),
                },
                setup_commands=["pip install pyyaml 2>/dev/null || true"],
            ),
            ground_truth="Create logging_config.yaml matching the doc format, and log_setup.py with setup_logging() that reads and validates the YAML config.",
            eval_spec=EvalSpec(
                method=EvalMethod.COMMAND_OUTPUT,
                check_command="python3 test_logging.py 2>&1",
                output_contains=["Logging configuration tests passed"],
                output_not_contains=["Traceback", "AssertionError"],
            ),
            capabilities=[
                Capability.DOC_READING,
                Capability.CODE_WRITING,
                Capability.FILE_CREATION,
                Capability.CONFIG_EDITING,
                Capability.DECOMPOSITION,
            ],
            source="web_search_generator:config_from_docs",
            estimated_minutes=8,
        )

    def _changelog_impact_analysis(self, difficulty: str) -> Task:
        """Task: read changelog and update code for breaking changes."""
        return Task(
            category=TaskCategory.WEB_SEARCH,
            title="Update code based on changelog breaking changes",
            difficulty=difficulty,
            goal=textwrap.dedent("""\
                The library we depend on released a new version. Read the changelog
                at `docs/CHANGELOG.md` and update `app.py` to work with the new version.

                Run `python3 test_app.py` to verify. It should print "All tests passed."
            """),
            environment=EnvironmentSetup(
                env_type="directory",
                seed_files={
                    "docs/CHANGELOG.md": textwrap.dedent("""\
                        # DataStore Changelog

                        ## v3.0.0 (Breaking Changes)

                        ### Removed
                        - `DataStore.find()` removed — use `DataStore.query()` instead
                        - `DataStore.save()` removed — use `DataStore.upsert()` instead
                        - `DataStore(path)` constructor removed — use `DataStore.open(path)` factory

                        ### Changed
                        - `query()` returns `ResultSet` object instead of list
                          - Use `.items()` to get list of records
                          - Use `.count()` for count (was `len()` on list)
                          - Use `.first()` for first result
                        - `upsert()` requires explicit `key` parameter: `upsert(key, data)`
                        - All methods are now prefixed with the record type:
                          `store.upsert("users", key, data)` instead of `store.upsert(key, data)`

                        ### Added
                        - `DataStore.open(path, mode="rw")` — factory method, mode can be "r" or "rw"
                        - `ResultSet.filter(fn)` — filter results with predicate
                        - `DataStore.transaction()` context manager for atomic operations
                    """),
                    "datastore.py": textwrap.dedent("""\
                        # v3.0 DataStore implementation

                        class ResultSet:
                            def __init__(self, data):
                                self._data = data

                            def items(self):
                                return list(self._data)

                            def count(self):
                                return len(self._data)

                            def first(self):
                                return self._data[0] if self._data else None

                            def filter(self, fn):
                                return ResultSet([d for d in self._data if fn(d)])

                        class DataStore:
                            def __init__(self):
                                # Private constructor — use open()
                                self._collections = {}
                                self._path = None

                            @classmethod
                            def open(cls, path, mode="rw"):
                                store = cls()
                                store._path = path
                                store._mode = mode
                                return store

                            def query(self, collection, **filters):
                                items = self._collections.get(collection, [])
                                results = []
                                for item in items:
                                    match = all(item.get(k) == v for k, v in filters.items())
                                    if match or not filters:
                                        results.append(item)
                                return ResultSet(results)

                            def upsert(self, collection, key, data):
                                if collection not in self._collections:
                                    self._collections[collection] = []
                                # Update existing or insert
                                for i, item in enumerate(self._collections[collection]):
                                    if item.get("id") == key:
                                        self._collections[collection][i] = {**data, "id": key}
                                        return
                                self._collections[collection].append({**data, "id": key})

                            def transaction(self):
                                return _Transaction(self)

                        class _Transaction:
                            def __init__(self, store):
                                self._store = store
                            def __enter__(self):
                                return self._store
                            def __exit__(self, *args):
                                pass
                    """),
                    "app.py": textwrap.dedent("""\
                        # Uses v2 API — needs migration to v3
                        from datastore import DataStore

                        def setup_store():
                            store = DataStore("data/app.db")  # v2 constructor
                            return store

                        def add_user(store, user_id, name, email):
                            store.save(user_id, {"name": name, "email": email})  # v2 method

                        def find_users(store, **criteria):
                            results = store.find(**criteria)  # v2 method, returns list
                            return results

                        def get_user_count(store):
                            users = store.find()  # v2 method
                            return len(users)  # v2: direct len on list

                        def get_first_user(store):
                            users = store.find()
                            return users[0] if users else None  # v2: direct index
                    """),
                    "test_app.py": textwrap.dedent("""\
                        from app import setup_store, add_user, find_users, get_user_count, get_first_user
                        from datastore import ResultSet

                        def test_setup():
                            store = setup_store()
                            assert store._path == "data/app.db"

                        def test_add_and_find():
                            store = setup_store()
                            add_user(store, "u1", "Alice", "alice@test.com")
                            add_user(store, "u2", "Bob", "bob@test.com")
                            results = find_users(store)
                            # v3: find_users should return ResultSet
                            assert isinstance(results, ResultSet), f"Expected ResultSet, got {type(results)}"
                            assert results.count() == 2

                        def test_count():
                            store = setup_store()
                            add_user(store, "u1", "Alice", "alice@test.com")
                            assert get_user_count(store) == 1

                        def test_first():
                            store = setup_store()
                            add_user(store, "u1", "Alice", "alice@test.com")
                            user = get_first_user(store)
                            assert user["name"] == "Alice"

                        if __name__ == '__main__':
                            test_setup()
                            test_add_and_find()
                            test_count()
                            test_first()
                            print("All tests passed.")
                    """),
                },
            ),
            ground_truth="Migrate app.py: DataStore('path') -> DataStore.open('path'), store.save(k,d) -> store.upsert('users',k,d), store.find() -> store.query('users'), len(results) -> results.count(), results[0] -> results.first()",
            eval_spec=EvalSpec(
                method=EvalMethod.COMMAND_OUTPUT,
                check_command="python3 test_app.py 2>&1",
                output_contains=["All tests passed"],
                output_not_contains=["Traceback", "Error", "AssertionError"],
            ),
            capabilities=[
                Capability.DOC_READING,
                Capability.CODE_READING,
                Capability.CODE_EDITING,
                Capability.MULTI_FILE_REASONING,
                Capability.SUMMARY_GENERATION,
            ],
            source="web_search_generator:changelog_impact_analysis",
            estimated_minutes=8,
        )

    def _error_from_docs(self, difficulty: str) -> Task:
        """Task: look up error in FAQ docs to find the fix."""
        return Task(
            category=TaskCategory.WEB_SEARCH,
            title="Fix error using FAQ documentation",
            difficulty=difficulty,
            goal=textwrap.dedent("""\
                The application fails with an error. Check the FAQ at `docs/FAQ.md`
                for known issues and solutions, then apply the fix.

                Run `python3 app.py` after fixing. It should print "App ready."
            """),
            environment=EnvironmentSetup(
                env_type="directory",
                seed_files={
                    "docs/FAQ.md": textwrap.dedent("""\
                        # Frequently Asked Questions

                        ## Common Errors

                        ### "ConnectionPoolExhausted" error
                        **Cause**: Default pool size is 5. If `MAX_WORKERS` > pool size, connections queue up.
                        **Fix**: Set `pool_size` in config to match `max_workers`, or set `pool_overflow=10`.

                        ### "SerializerNotFound" for custom types
                        **Cause**: The default JSON serializer doesn't handle custom types.
                        **Fix**: Register custom types in the config:
                        ```python
                        config = Config(
                            serializers={"datetime": str, "Decimal": float},
                        )
                        ```

                        ### "InvalidSchemaVersion" on startup
                        **Cause**: Config file `schema_version` doesn't match expected version.
                        **Fix**: Current expected version is `3`. Update config to `schema_version: 3`.
                        Also ensure `migrations_enabled: true` is set.

                        ### "HandshakeTimeout" connecting to service
                        **Cause**: Default timeout is 5s, some services need more.
                        **Fix**: Set `connect_timeout: 30` in config. Also set `retry_on_timeout: true`.

                        ## Configuration Reference
                        Required fields for v3 schema:
                        - schema_version: 3
                        - pool_size: int (must be >= max_workers)
                        - max_workers: int
                        - connect_timeout: int (seconds)
                        - retry_on_timeout: bool
                        - migrations_enabled: bool
                    """),
                    "app.py": textwrap.dedent("""\
                        import json
                        import sys

                        def load_config():
                            with open("config.json") as f:
                                config = json.load(f)

                            errors = []
                            if config.get("schema_version") != 3:
                                errors.append("InvalidSchemaVersion")
                            if not config.get("migrations_enabled"):
                                errors.append("InvalidSchemaVersion: migrations_enabled required")
                            if config.get("pool_size", 5) < config.get("max_workers", 1):
                                errors.append("ConnectionPoolExhausted: pool_size < max_workers")
                            if config.get("connect_timeout", 5) < 10:
                                errors.append("HandshakeTimeout: connect_timeout too low")
                            if not config.get("retry_on_timeout"):
                                errors.append("HandshakeTimeout: retry_on_timeout not set")

                            if errors:
                                for e in errors:
                                    print(f"ERROR: {e}", file=sys.stderr)
                                sys.exit(1)
                            return config

                        if __name__ == '__main__':
                            config = load_config()
                            print(f"Schema v{config['schema_version']}, pool={config['pool_size']}, workers={config['max_workers']}")
                            print("App ready.")
                    """),
                    "config.json": textwrap.dedent("""\
                        {
                            "schema_version": 2,
                            "pool_size": 5,
                            "max_workers": 10,
                            "connect_timeout": 5
                        }
                    """).strip(),
                },
            ),
            ground_truth="Update config.json: schema_version->3, pool_size>=max_workers (10), connect_timeout>=10 (30), add retry_on_timeout:true, add migrations_enabled:true",
            eval_spec=EvalSpec(
                method=EvalMethod.COMMAND_OUTPUT,
                check_command="python3 app.py 2>&1",
                output_contains=["App ready"],
                output_not_contains=["ERROR", "Traceback"],
            ),
            capabilities=[
                Capability.DOC_READING,
                Capability.CONFIG_READING,
                Capability.CONFIG_EDITING,
                Capability.ROOT_CAUSE_ANALYSIS,
                Capability.EXPLANATION,
            ],
            source="web_search_generator:error_from_docs",
            estimated_minutes=5,
        )

    def _build_system_setup(self, difficulty: str) -> Task:
        """Task: set up build system from documentation."""
        return Task(
            category=TaskCategory.WEB_SEARCH,
            title="Set up build system from documentation",
            difficulty=difficulty,
            goal=textwrap.dedent("""\
                Read `docs/BUILD.md` and set up the project's build system.
                Create the Makefile and verify the build works.

                Run `make test` to verify. It should print "Build system OK."
            """),
            environment=EnvironmentSetup(
                env_type="directory",
                seed_files={
                    "docs/BUILD.md": textwrap.dedent("""\
                        # Build System Setup

                        ## Overview
                        This project uses Make for building. Create a `Makefile` in the project root.

                        ## Required Targets

                        ### `build`
                        - Compile all Python files to bytecode: `python3 -m py_compile <file>`
                        - Compile: `src/main.py`, `src/utils.py`, `src/config.py`
                        - Create `build/` directory if it doesn't exist

                        ### `clean`
                        - Remove `build/` directory
                        - Remove all `__pycache__` directories
                        - Remove all `.pyc` files

                        ### `test`
                        - Run: `python3 -m pytest tests/ -p no:xdist -p no:randomly -p no:cacheprovider -v`
                        - Must depend on `build` (build first, then test)

                        ### `lint`
                        - Run: `python3 -m py_compile src/main.py src/utils.py src/config.py`
                        - Exit with error if any file has syntax errors

                        ### `all` (default)
                        - Run `clean`, then `build`, then `test`

                        ## Variables
                        - `SRC_DIR = src`
                        - `BUILD_DIR = build`
                        - `PYTHON = python3`
                    """),
                    "src/__init__.py": "",
                    "src/main.py": textwrap.dedent("""\
                        from src.utils import helper
                        from src.config import load_config

                        def main():
                            config = load_config()
                            result = helper(config["value"])
                            print(f"Result: {result}")

                        if __name__ == '__main__':
                            main()
                    """),
                    "src/utils.py": textwrap.dedent("""\
                        def helper(x):
                            return x * 2
                    """),
                    "src/config.py": textwrap.dedent("""\
                        def load_config():
                            return {"value": 21}
                    """),
                    "tests/__init__.py": "",
                    "tests/test_main.py": textwrap.dedent("""\
                        from src.utils import helper
                        from src.config import load_config

                        def test_helper():
                            assert helper(21) == 42

                        def test_config():
                            config = load_config()
                            assert "value" in config

                        def test_build_system():
                            import os
                            # Check Makefile exists
                            assert os.path.exists("Makefile"), "Makefile not found"
                            print("Build system OK.")
                    """),
                },
            ),
            ground_truth="Create Makefile with targets: all (clean build test), build (py_compile), clean (rm -rf), test (pytest), lint (py_compile). Must use tabs for indentation.",
            eval_spec=EvalSpec(
                method=EvalMethod.COMPOSITE,
                sub_evals=[
                    {"method": "file_exists",
                     "expected_files": ["Makefile"]},
                    {"method": "command_output",
                     "check_command": "make test 2>&1",
                     "output_contains": ["passed"],
                     "output_not_contains": ["FAILED"]},
                ]
            ),
            capabilities=[
                Capability.DOC_READING,
                Capability.FILE_CREATION,
                Capability.BUILD_SYSTEMS,
                Capability.SCRIPT_WRITING,
                Capability.DECOMPOSITION,
            ],
            source="web_search_generator:build_system_setup",
            estimated_minutes=8,
        )
