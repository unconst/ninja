"""
Repository debugging task generator.

Generates tasks that simulate real bugs in code repositories — test failures,
regressions, off-by-one errors, missing edge cases, refactoring breakage, etc.
These tasks exercise git_ops, test_running, root_cause_analysis, and multi_file_reasoning.
"""

import textwrap
from ..schema import (
    Task, TaskCategory, Capability, EvalMethod,
    EnvironmentSetup, EvalSpec
)
from .base import TaskGenerator


class RepoDebugGenerator(TaskGenerator):
    """Generates repository debugging and bug-fixing tasks."""

    @property
    def category(self) -> TaskCategory:
        return TaskCategory.REPO_DEBUG

    def generate(self, count: int = 5, difficulty: str = "medium") -> list[Task]:
        generators = [
            self._failing_tests_regression,
            self._off_by_one_pagination,
            self._missing_edge_case,
            self._refactor_breakage,
            self._git_bisect_bug,
            self._test_fixture_corruption,
            self._import_after_rename,
            self._race_condition_in_cache,
        ]

        tasks = []
        for i in range(count):
            gen = generators[i % len(generators)]
            task = gen(difficulty)
            tasks.append(task)
        return tasks

    def _failing_tests_regression(self, difficulty: str) -> Task:
        """Task: fix a regression that broke existing tests."""
        return Task(
            category=TaskCategory.REPO_DEBUG,
            title="Fix test regression after feature addition",
            difficulty=difficulty,
            goal=textwrap.dedent("""\
                A recent change to the `UserService` class broke existing tests.
                Run `python3 -m pytest tests/ -p no:xdist -p no:randomly -p no:cacheprovider -x -v` to see the failures.

                Fix the bug WITHOUT reverting the new feature (the `is_premium` field).
                All tests must pass after your fix.
            """),
            environment=EnvironmentSetup(
                env_type="directory",
                seed_files={
                    "src/__init__.py": "",
                    "src/models.py": textwrap.dedent("""\
                        class User:
                            def __init__(self, name, email, is_premium=False):
                                self.name = name
                                self.email = email
                                self.is_premium = is_premium

                            def display_name(self):
                                prefix = "[P] " if self.is_premium else ""
                                return f"{prefix}{self.name}"

                            def to_dict(self):
                                return {
                                    "name": self.name,
                                    "email": self.email,
                                    "is_premium": self.is_premium,
                                }
                    """),
                    "src/service.py": textwrap.dedent("""\
                        from src.models import User

                        class UserService:
                            def __init__(self):
                                self._users = {}

                            def create_user(self, name, email, is_premium=False):
                                if email in self._users:
                                    raise ValueError(f"User {email} already exists")
                                user = User(name, email, is_premium)
                                self._users[email] = user
                                return user

                            def get_user(self, email):
                                return self._users.get(email)

                            def list_users(self):
                                # Bug: was returning list of User objects, now returns dicts
                                # This broke downstream code that expected User objects
                                return [u.to_dict() for u in self._users.values()]

                            def count_premium(self):
                                return sum(1 for u in self._users.values() if u.is_premium)
                    """),
                    "tests/__init__.py": "",
                    "tests/test_service.py": textwrap.dedent("""\
                        import pytest
                        from src.service import UserService

                        @pytest.fixture
                        def svc():
                            s = UserService()
                            s.create_user("Alice", "alice@test.com")
                            s.create_user("Bob", "bob@test.com", is_premium=True)
                            return s

                        def test_create_user(svc):
                            user = svc.create_user("Charlie", "charlie@test.com")
                            assert user.name == "Charlie"

                        def test_duplicate_user(svc):
                            with pytest.raises(ValueError):
                                svc.create_user("Alice2", "alice@test.com")

                        def test_get_user(svc):
                            user = svc.get_user("alice@test.com")
                            assert user.name == "Alice"
                            assert user.email == "alice@test.com"

                        def test_list_users(svc):
                            users = svc.list_users()
                            assert len(users) == 2
                            names = [u.name for u in users]  # Expects User objects
                            assert "Alice" in names
                            assert "Bob" in names

                        def test_list_users_display(svc):
                            users = svc.list_users()
                            displays = [u.display_name() for u in users]  # Expects .display_name()
                            assert "[P] Bob" in displays

                        def test_count_premium(svc):
                            assert svc.count_premium() == 1
                    """),
                },
            ),
            ground_truth="Fix list_users() to return User objects instead of dicts. Change: return list(self._users.values())",
            eval_spec=EvalSpec(
                method=EvalMethod.COMPOSITE,
                sub_evals=[
                    {"method": "command_output",
                     "check_command": "python3 -m pytest tests/ -p no:xdist -p no:randomly -p no:cacheprovider -v 2>&1",
                     "output_contains": ["passed"],
                     "output_not_contains": ["FAILED", "ERROR"]},
                    {"method": "command_output",
                     "check_command": "python3 -c \"from src.service import UserService; s=UserService(); s.create_user('X','x@t.com',True); print(s.count_premium())\" 2>&1",
                     "output_contains": ["1"]},
                ]
            ),
            capabilities=[
                Capability.TEST_RUNNING,
                Capability.ROOT_CAUSE_ANALYSIS,
                Capability.CODE_READING,
                Capability.CODE_EDITING,
                Capability.MULTI_FILE_REASONING,
                Capability.ERROR_INTERPRETATION,
            ],
            source="repo_debug_generator:failing_tests_regression",
            estimated_minutes=5,
        )

    def _off_by_one_pagination(self, difficulty: str) -> Task:
        """Task: fix off-by-one error in pagination logic."""
        return Task(
            category=TaskCategory.REPO_DEBUG,
            title="Fix off-by-one error in pagination",
            difficulty=difficulty,
            goal=textwrap.dedent("""\
                The pagination module has a bug. Run the tests to see:
                `python3 -m pytest test_pagination.py -p no:xdist -p no:randomly -p no:cacheprovider -v`

                Fix the pagination logic so all tests pass. The paginator should:
                - Return correct items for each page
                - Calculate total_pages correctly
                - Handle edge cases (empty list, last page with fewer items)
            """),
            environment=EnvironmentSetup(
                env_type="directory",
                seed_files={
                    "pagination.py": textwrap.dedent("""\
                        class Paginator:
                            def __init__(self, items, page_size=10):
                                self.items = items
                                self.page_size = page_size

                            @property
                            def total_pages(self):
                                # Bug: integer division truncates, missing partial last page
                                return len(self.items) // self.page_size

                            def get_page(self, page_num):
                                \"\"\"Get items for a page (1-indexed).\"\"\"
                                if page_num < 1 or page_num > self.total_pages:
                                    return []
                                # Bug: off-by-one in start index
                                start = page_num * self.page_size
                                end = start + self.page_size
                                return self.items[start:end]

                            def page_info(self, page_num):
                                items = self.get_page(page_num)
                                return {
                                    "page": page_num,
                                    "items": items,
                                    "total_pages": self.total_pages,
                                    "total_items": len(self.items),
                                    "has_next": page_num < self.total_pages,
                                    "has_prev": page_num > 1,
                                }
                    """),
                    "test_pagination.py": textwrap.dedent("""\
                        import pytest
                        from pagination import Paginator

                        def test_total_pages_exact():
                            p = Paginator(list(range(20)), page_size=10)
                            assert p.total_pages == 2

                        def test_total_pages_partial():
                            p = Paginator(list(range(25)), page_size=10)
                            assert p.total_pages == 3  # 10 + 10 + 5

                        def test_total_pages_empty():
                            p = Paginator([], page_size=10)
                            assert p.total_pages == 0

                        def test_get_first_page():
                            p = Paginator(list(range(25)), page_size=10)
                            assert p.get_page(1) == list(range(10))

                        def test_get_second_page():
                            p = Paginator(list(range(25)), page_size=10)
                            assert p.get_page(2) == list(range(10, 20))

                        def test_get_last_partial_page():
                            p = Paginator(list(range(25)), page_size=10)
                            assert p.get_page(3) == list(range(20, 25))

                        def test_page_out_of_range():
                            p = Paginator(list(range(25)), page_size=10)
                            assert p.get_page(0) == []
                            assert p.get_page(4) == []

                        def test_page_info():
                            p = Paginator(list(range(25)), page_size=10)
                            info = p.page_info(2)
                            assert info["page"] == 2
                            assert info["has_next"] is True
                            assert info["has_prev"] is True
                            assert len(info["items"]) == 10

                        def test_single_page():
                            p = Paginator(list(range(5)), page_size=10)
                            assert p.total_pages == 1
                            assert p.get_page(1) == list(range(5))
                            info = p.page_info(1)
                            assert info["has_next"] is False
                            assert info["has_prev"] is False
                    """),
                },
            ),
            ground_truth="Two bugs: 1) total_pages should use math.ceil or (len+size-1)//size, 2) get_page start index should be (page_num-1)*page_size not page_num*page_size",
            eval_spec=EvalSpec(
                method=EvalMethod.COMMAND_OUTPUT,
                check_command="python3 -m pytest test_pagination.py -p no:xdist -p no:randomly -p no:cacheprovider -v 2>&1",
                output_contains=["passed"],
                output_not_contains=["FAILED", "ERROR"],
            ),
            capabilities=[
                Capability.TEST_RUNNING,
                Capability.ROOT_CAUSE_ANALYSIS,
                Capability.CODE_READING,
                Capability.CODE_EDITING,
                Capability.ERROR_INTERPRETATION,
            ],
            source="repo_debug_generator:off_by_one_pagination",
            estimated_minutes=5,
        )

    def _missing_edge_case(self, difficulty: str) -> Task:
        """Task: fix missing edge case handling in a parser."""
        return Task(
            category=TaskCategory.REPO_DEBUG,
            title="Fix edge case crashes in URL parser",
            difficulty=difficulty,
            goal=textwrap.dedent("""\
                The URL parser utility works for basic cases but crashes on edge cases.
                Run `python3 -m pytest test_parser.py -p no:xdist -p no:randomly -p no:cacheprovider -v` to see failures.

                Fix the parser to handle all edge cases. Do NOT rewrite it from scratch —
                fix the minimum necessary to make all tests pass.
            """),
            environment=EnvironmentSetup(
                env_type="directory",
                seed_files={
                    "parser.py": textwrap.dedent("""\
                        def parse_url(url):
                            \"\"\"Parse a URL into its components.\"\"\"
                            result = {
                                "scheme": "",
                                "host": "",
                                "port": None,
                                "path": "/",
                                "query": {},
                                "fragment": "",
                            }

                            # Split fragment
                            if "#" in url:
                                url, result["fragment"] = url.split("#", 1)

                            # Split query
                            if "?" in url:
                                url, query_str = url.split("?", 1)
                                for param in query_str.split("&"):
                                    key, value = param.split("=")  # Bug: crashes if no "="
                                    result["query"][key] = value

                            # Split scheme
                            scheme_end = url.index("://")  # Bug: crashes if no scheme
                            result["scheme"] = url[:scheme_end]
                            url = url[scheme_end + 3:]

                            # Split path
                            if "/" in url:
                                slash_idx = url.index("/")
                                result["path"] = url[slash_idx:]
                                url = url[:slash_idx]

                            # Split port
                            if ":" in url:
                                host, port_str = url.split(":")
                                result["host"] = host
                                result["port"] = int(port_str)  # Bug: crashes on empty port
                            else:
                                result["host"] = url

                            return result
                    """),
                    "test_parser.py": textwrap.dedent("""\
                        import pytest
                        from parser import parse_url

                        def test_basic_url():
                            r = parse_url("https://example.com/path")
                            assert r["scheme"] == "https"
                            assert r["host"] == "example.com"
                            assert r["path"] == "/path"

                        def test_url_with_port():
                            r = parse_url("http://localhost:8080/api")
                            assert r["host"] == "localhost"
                            assert r["port"] == 8080
                            assert r["path"] == "/api"

                        def test_url_with_query():
                            r = parse_url("https://example.com/search?q=hello&lang=en")
                            assert r["query"]["q"] == "hello"
                            assert r["query"]["lang"] == "en"

                        def test_url_with_fragment():
                            r = parse_url("https://example.com/page#section1")
                            assert r["fragment"] == "section1"

                        def test_url_no_path():
                            r = parse_url("https://example.com")
                            assert r["host"] == "example.com"
                            assert r["path"] == "/"

                        def test_query_param_no_value():
                            r = parse_url("https://example.com/search?q=hello&debug")
                            assert r["query"]["q"] == "hello"
                            assert "debug" in r["query"]

                        def test_no_scheme():
                            r = parse_url("example.com/path")
                            assert r["host"] == "example.com"
                            assert r["path"] == "/path"
                            assert r["scheme"] == ""

                        def test_empty_url():
                            r = parse_url("")
                            assert r["host"] == ""
                            assert r["path"] == "/"
                    """),
                },
            ),
            ground_truth="Three bugs: 1) query param split needs to handle missing '=' (use split('=',1) + default), 2) scheme parsing needs try/except for missing '://', 3) port parsing needs guard for empty port string",
            eval_spec=EvalSpec(
                method=EvalMethod.COMMAND_OUTPUT,
                check_command="python3 -m pytest test_parser.py -p no:xdist -p no:randomly -p no:cacheprovider -v 2>&1",
                output_contains=["passed"],
                output_not_contains=["FAILED", "ERROR"],
            ),
            capabilities=[
                Capability.TEST_RUNNING,
                Capability.ROOT_CAUSE_ANALYSIS,
                Capability.CODE_READING,
                Capability.CODE_EDITING,
                Capability.HYPOTHESIS_TESTING,
            ],
            source="repo_debug_generator:missing_edge_case",
            estimated_minutes=8,
        )

    def _refactor_breakage(self, difficulty: str) -> Task:
        """Task: fix breakage caused by an incomplete refactor."""
        return Task(
            category=TaskCategory.REPO_DEBUG,
            title="Fix broken code after incomplete refactoring",
            difficulty=difficulty,
            goal=textwrap.dedent("""\
                Someone started refactoring the calculator module from functions to a class-based
                design but didn't finish. The code is in a broken state — some parts use the old
                function API, others use the new class API.

                Complete the refactoring so ALL tests pass:
                `python3 -m pytest tests/ -p no:xdist -p no:randomly -p no:cacheprovider -v`

                Keep the Calculator class approach. Update all call sites to use it.
            """),
            environment=EnvironmentSetup(
                env_type="directory",
                seed_files={
                    "calculator/__init__.py": textwrap.dedent("""\
                        # Refactored: only class-based API now
                        from .calc import Calculator
                    """),
                    "calculator/calc.py": textwrap.dedent("""\
                        class Calculator:
                            def __init__(self, precision=2):
                                self.precision = precision
                                self.history = []

                            def add(self, a, b):
                                result = round(a + b, self.precision)
                                self.history.append(('add', a, b, result))
                                return result

                            def subtract(self, a, b):
                                result = round(a - b, self.precision)
                                self.history.append(('subtract', a, b, result))
                                return result

                            def multiply(self, a, b):
                                result = round(a * b, self.precision)
                                self.history.append(('multiply', a, b, result))
                                return result

                            def divide(self, a, b):
                                if b == 0:
                                    raise ZeroDivisionError("Cannot divide by zero")
                                result = round(a / b, self.precision)
                                self.history.append(('divide', a, b, result))
                                return result

                            def last_result(self):
                                if not self.history:
                                    return None
                                return self.history[-1][3]
                    """),
                    "app.py": textwrap.dedent("""\
                        # Main app — partially refactored (functions.py was deleted)
                        from calculator import Calculator
                        from calculator.functions import add, multiply  # Bug: functions.py no longer exists

                        def compute_stats(numbers):
                            total = add(numbers[0], numbers[1])  # Bug: should use Calculator
                            for n in numbers[2:]:
                                total = add(total, n)

                            calc = Calculator()
                            avg = calc.divide(total, len(numbers))
                            product = multiply(numbers[0], numbers[1])  # Bug: old API
                            return {"total": total, "average": avg, "product": product}

                        def run():
                            result = compute_stats([10, 20, 30])
                            print(f"Total: {result['total']}, Avg: {result['average']}, Product: {result['product']}")
                            return result
                    """),
                    "tests/__init__.py": "",
                    "tests/test_calculator.py": textwrap.dedent("""\
                        import pytest
                        from calculator import Calculator

                        @pytest.fixture
                        def calc():
                            return Calculator()

                        def test_add(calc):
                            assert calc.add(2, 3) == 5

                        def test_subtract(calc):
                            assert calc.subtract(10, 4) == 6

                        def test_multiply(calc):
                            assert calc.multiply(3, 7) == 21

                        def test_divide(calc):
                            assert calc.divide(10, 3) == 3.33

                        def test_divide_by_zero(calc):
                            with pytest.raises(ZeroDivisionError):
                                calc.divide(1, 0)

                        def test_history(calc):
                            calc.add(1, 2)
                            calc.multiply(3, 4)
                            assert len(calc.history) == 2
                            assert calc.last_result() == 12

                        def test_precision():
                            calc = Calculator(precision=4)
                            assert calc.divide(1, 3) == 0.3333
                    """),
                    "tests/test_app.py": textwrap.dedent("""\
                        from app import compute_stats, run

                        def test_compute_stats():
                            result = compute_stats([10, 20, 30])
                            assert result["total"] == 60
                            assert result["average"] == 20.0
                            assert result["product"] == 200

                        def test_run(capsys):
                            run()
                            captured = capsys.readouterr()
                            assert "Total: 60" in captured.out
                            assert "Avg: 20" in captured.out
                    """),
                },
            ),
            ground_truth="Refactor app.py to use Calculator class: remove old function imports, create Calculator instance, call calc.add() and calc.multiply() instead of bare functions",
            eval_spec=EvalSpec(
                method=EvalMethod.COMMAND_OUTPUT,
                check_command="python3 -m pytest tests/ -p no:xdist -p no:randomly -p no:cacheprovider -v 2>&1",
                output_contains=["passed"],
                output_not_contains=["FAILED", "ERROR"],
            ),
            capabilities=[
                Capability.TEST_RUNNING,
                Capability.ROOT_CAUSE_ANALYSIS,
                Capability.CODE_READING,
                Capability.CODE_EDITING,
                Capability.MULTI_FILE_REASONING,
                Capability.DECOMPOSITION,
            ],
            source="repo_debug_generator:refactor_breakage",
            estimated_minutes=8,
        )

    def _git_bisect_bug(self, difficulty: str) -> Task:
        """Task: use git history to find when a bug was introduced."""
        return Task(
            category=TaskCategory.REPO_DEBUG,
            title="Find and fix bug using git history",
            difficulty=difficulty,
            goal=textwrap.dedent("""\
                This git repository has a bug that was introduced in a recent commit.
                The `validate_email` function currently rejects valid emails with subdomains
                (like user@mail.example.com).

                1. Use `git log` to examine the recent commits
                2. Find which commit introduced the regression
                3. Fix the bug so ALL tests pass:
                   `python3 -m pytest test_email.py -p no:xdist -p no:randomly -p no:cacheprovider -v`
                4. Write the bad commit hash to a file called `bad_commit.txt`
            """),
            environment=EnvironmentSetup(
                env_type="directory",
                seed_files={
                    "email_validator.py": textwrap.dedent("""\
                        import re

                        def validate_email(email):
                            \"\"\"Validate an email address.\"\"\"
                            if not email or not isinstance(email, str):
                                return False
                            # Must have exactly one @
                            parts = email.split("@")
                            if len(parts) != 2:
                                return False
                            local, domain = parts
                            # Local part checks
                            if not local or len(local) > 64:
                                return False
                            # Domain checks — bug: only allows single-level domains
                            if not re.match(r'^[a-zA-Z0-9]+\\.[a-zA-Z]{2,}$', domain):
                                return False
                            return True
                    """),
                    "test_email.py": textwrap.dedent("""\
                        import pytest
                        from email_validator import validate_email

                        def test_valid_basic():
                            assert validate_email("user@example.com") is True

                        def test_valid_subdomain():
                            assert validate_email("user@mail.example.com") is True

                        def test_valid_long_domain():
                            assert validate_email("user@sub.domain.example.co.uk") is True

                        def test_invalid_no_at():
                            assert validate_email("userexample.com") is False

                        def test_invalid_no_domain():
                            assert validate_email("user@") is False

                        def test_invalid_no_local():
                            assert validate_email("@example.com") is False

                        def test_invalid_double_at():
                            assert validate_email("user@@example.com") is False

                        def test_invalid_empty():
                            assert validate_email("") is False

                        def test_invalid_none():
                            assert validate_email(None) is False

                        def test_valid_numbers_in_domain():
                            assert validate_email("user@123.example.com") is True

                        def test_valid_hyphen_in_domain():
                            assert validate_email("user@my-domain.com") is True
                    """),
                },
                setup_commands=[
                    "git init",
                    "git config user.email 'dev@test.com'",
                    "git config user.name 'Dev'",
                    # Commit 1: initial version (working)
                    "python3 -c \"\nimport textwrap, pathlib\npathlib.Path('email_validator.py').write_text(textwrap.dedent('''\nimport re\n\ndef validate_email(email):\n    if not email or not isinstance(email, str):\n        return False\n    parts = email.split('@')\n    if len(parts) != 2:\n        return False\n    local, domain = parts\n    if not local or len(local) > 64:\n        return False\n    if not re.match(r'^[a-zA-Z0-9.-]+\\\\.[a-zA-Z]{2,}$', domain):\n        return False\n    return True\n'''))\"",
                    "git add -A && git commit -m 'Initial email validator'",
                    # Commit 2: add test file
                    "git add -A && git commit -m 'Add test suite' --allow-empty",
                    # Commit 3: "tighten" domain validation (introduces bug)
                    "python3 -c \"\nimport textwrap, pathlib\npathlib.Path('email_validator.py').write_text(textwrap.dedent('''\nimport re\n\ndef validate_email(email):\n    if not email or not isinstance(email, str):\n        return False\n    parts = email.split('@')\n    if len(parts) != 2:\n        return False\n    local, domain = parts\n    if not local or len(local) > 64:\n        return False\n    if not re.match(r\\'^[a-zA-Z0-9]+\\\\\\\\.[a-zA-Z]{2,}$\\', domain):\n        return False\n    return True\n'''))\"",
                    "git add -A && git commit -m 'Tighten domain validation regex'",
                    # Commit 4: unrelated change
                    "git add -A && git commit -m 'Update test comments' --allow-empty",
                    # Now restore the buggy version as working tree
                ],
            ),
            ground_truth="Fix regex to allow subdomains: r'^[a-zA-Z0-9.-]+\\.[a-zA-Z]{2,}$' (allow dots and hyphens). Bad commit is the 'Tighten domain validation' one.",
            eval_spec=EvalSpec(
                method=EvalMethod.COMPOSITE,
                sub_evals=[
                    {"method": "command_output",
                     "check_command": "python3 -m pytest test_email.py -p no:xdist -p no:randomly -p no:cacheprovider -v 2>&1",
                     "output_contains": ["passed"],
                     "output_not_contains": ["FAILED", "ERROR"]},
                    {"method": "file_exists",
                     "expected_files": ["bad_commit.txt"]},
                ]
            ),
            capabilities=[
                Capability.GIT_OPERATIONS,
                Capability.TEST_RUNNING,
                Capability.ROOT_CAUSE_ANALYSIS,
                Capability.CODE_READING,
                Capability.CODE_EDITING,
                Capability.HYPOTHESIS_TESTING,
            ],
            source="repo_debug_generator:git_bisect_bug",
            estimated_minutes=10,
        )

    def _test_fixture_corruption(self, difficulty: str) -> Task:
        """Task: fix shared test fixture that causes flaky tests."""
        return Task(
            category=TaskCategory.REPO_DEBUG,
            title="Fix shared mutable state causing flaky tests",
            difficulty=difficulty,
            goal=textwrap.dedent("""\
                Tests pass individually but fail when run together:

                Single: `python3 -m pytest test_inventory.py::test_add_item -p no:xdist -p no:randomly -p no:cacheprovider -v`  (PASS)
                All:    `python3 -m pytest test_inventory.py -p no:xdist -p no:randomly -p no:cacheprovider -v`  (FAIL)

                Find and fix the shared mutable state that's causing test interference.
                All tests should pass when run together.
            """),
            environment=EnvironmentSetup(
                env_type="directory",
                seed_files={
                    "inventory.py": textwrap.dedent("""\
                        class Inventory:
                            # Bug: shared mutable default — all instances share same list
                            def __init__(self, items=[]):
                                self.items = items

                            def add_item(self, name, quantity):
                                self.items.append({"name": name, "quantity": quantity})

                            def remove_item(self, name):
                                self.items = [i for i in self.items if i["name"] != name]

                            def get_item(self, name):
                                for item in self.items:
                                    if item["name"] == name:
                                        return item
                                return None

                            def total_items(self):
                                return sum(i["quantity"] for i in self.items)

                            def count(self):
                                return len(self.items)
                    """),
                    "test_inventory.py": textwrap.dedent("""\
                        import pytest
                        from inventory import Inventory

                        def test_add_item():
                            inv = Inventory()
                            inv.add_item("Apple", 5)
                            assert inv.count() == 1
                            assert inv.get_item("Apple")["quantity"] == 5

                        def test_empty_inventory():
                            inv = Inventory()
                            assert inv.count() == 0
                            assert inv.total_items() == 0

                        def test_remove_item():
                            inv = Inventory()
                            inv.add_item("Banana", 3)
                            inv.remove_item("Banana")
                            assert inv.count() == 0

                        def test_multiple_items():
                            inv = Inventory()
                            inv.add_item("X", 1)
                            inv.add_item("Y", 2)
                            assert inv.count() == 2
                            assert inv.total_items() == 3

                        def test_get_nonexistent():
                            inv = Inventory()
                            assert inv.get_item("Ghost") is None
                    """),
                },
            ),
            ground_truth="Classic Python mutable default argument bug. Fix: def __init__(self, items=None): self.items = items if items is not None else []",
            eval_spec=EvalSpec(
                method=EvalMethod.COMMAND_OUTPUT,
                check_command="python3 -m pytest test_inventory.py -p no:xdist -p no:randomly -p no:cacheprovider -v 2>&1",
                output_contains=["5 passed"],
                output_not_contains=["FAILED", "ERROR"],
            ),
            capabilities=[
                Capability.TEST_RUNNING,
                Capability.ROOT_CAUSE_ANALYSIS,
                Capability.CODE_READING,
                Capability.CODE_EDITING,
                Capability.HYPOTHESIS_TESTING,
            ],
            source="repo_debug_generator:test_fixture_corruption",
            estimated_minutes=5,
        )

    def _import_after_rename(self, difficulty: str) -> Task:
        """Task: fix broken imports after a module rename."""
        return Task(
            category=TaskCategory.REPO_DEBUG,
            title="Fix broken imports after module rename",
            difficulty=difficulty,
            goal=textwrap.dedent("""\
                Someone renamed the `utils` package to `helpers` but didn't update all
                the import statements. Running `python3 main.py` crashes with ImportError.

                Find and fix ALL broken imports so the program runs and prints:
                "Report generated: 3 items processed"

                Do NOT rename anything back — keep the `helpers` package name.
            """),
            environment=EnvironmentSetup(
                env_type="directory",
                seed_files={
                    "main.py": textwrap.dedent("""\
                        from reporting.report import generate_report

                        if __name__ == '__main__':
                            data = [
                                {"name": "Widget A", "price": 10.99, "qty": 5},
                                {"name": "Widget B", "price": 24.50, "qty": 2},
                                {"name": "Widget C", "price": 7.25, "qty": 12},
                            ]
                            result = generate_report(data)
                            print(f"Report generated: {result['count']} items processed")
                    """),
                    "helpers/__init__.py": "",
                    "helpers/formatting.py": textwrap.dedent("""\
                        def format_currency(amount):
                            return f"${amount:,.2f}"

                        def format_table_row(name, value, qty):
                            return f"| {name:20s} | {format_currency(value):>10s} | {qty:>5d} |"
                    """),
                    "helpers/math_ops.py": textwrap.dedent("""\
                        def safe_divide(a, b, default=0):
                            return a / b if b != 0 else default

                        def running_total(items, key):
                            total = 0
                            results = []
                            for item in items:
                                total += item[key]
                                results.append(total)
                            return results
                    """),
                    "helpers/validators.py": textwrap.dedent("""\
                        def validate_positive(value, name="value"):
                            if value < 0:
                                raise ValueError(f"{name} must be positive, got {value}")
                            return value
                    """),
                    "reporting/__init__.py": "",
                    "reporting/report.py": textwrap.dedent("""\
                        from utils.formatting import format_currency, format_table_row
                        from utils.math_ops import running_total
                        from utils.validators import validate_positive

                        def generate_report(data):
                            rows = []
                            for item in data:
                                validate_positive(item['price'], 'price')
                                validate_positive(item['qty'], 'qty')
                                rows.append(format_table_row(
                                    item['name'], item['price'], item['qty']
                                ))
                            totals = running_total(data, 'price')
                            return {
                                "rows": rows,
                                "count": len(data),
                                "total": format_currency(totals[-1] if totals else 0),
                            }
                    """),
                },
            ),
            ground_truth="Fix 3 imports in reporting/report.py: change 'utils.formatting' to 'helpers.formatting', 'utils.math_ops' to 'helpers.math_ops', 'utils.validators' to 'helpers.validators'",
            eval_spec=EvalSpec(
                method=EvalMethod.COMMAND_OUTPUT,
                check_command="python3 main.py 2>&1",
                output_contains=["Report generated: 3 items processed"],
                output_not_contains=["ImportError", "ModuleNotFoundError", "Traceback"],
            ),
            capabilities=[
                Capability.ERROR_INTERPRETATION,
                Capability.FILE_SEARCH,
                Capability.CODE_READING,
                Capability.CODE_EDITING,
                Capability.MULTI_FILE_REASONING,
                Capability.CODE_SEARCH,
            ],
            source="repo_debug_generator:import_after_rename",
            estimated_minutes=5,
        )

    def _race_condition_in_cache(self, difficulty: str) -> Task:
        """Task: fix a logic bug in a cache implementation."""
        return Task(
            category=TaskCategory.REPO_DEBUG,
            title="Fix LRU cache eviction bug",
            difficulty=difficulty,
            goal=textwrap.dedent("""\
                The LRU cache implementation has a bug in its eviction logic.
                Run tests: `python3 -m pytest test_cache.py -p no:xdist -p no:randomly -p no:cacheprovider -v`

                The cache should evict the Least Recently Used item when full.
                Fix the bug — do NOT rewrite the cache from scratch.
            """),
            environment=EnvironmentSetup(
                env_type="directory",
                seed_files={
                    "cache.py": textwrap.dedent("""\
                        from collections import OrderedDict

                        class LRUCache:
                            def __init__(self, capacity):
                                self.capacity = capacity
                                self.cache = OrderedDict()

                            def get(self, key):
                                if key not in self.cache:
                                    return None
                                # Move to end (most recently used)
                                self.cache.move_to_end(key)
                                return self.cache[key]

                            def put(self, key, value):
                                if key in self.cache:
                                    self.cache[key] = value
                                    self.cache.move_to_end(key)
                                    return
                                if len(self.cache) >= self.capacity:
                                    # Bug: evicts LAST (most recent) instead of FIRST (least recent)
                                    self.cache.popitem(last=True)
                                self.cache[key] = value

                            def size(self):
                                return len(self.cache)

                            def keys(self):
                                return list(self.cache.keys())
                    """),
                    "test_cache.py": textwrap.dedent("""\
                        import pytest
                        from cache import LRUCache

                        def test_basic_put_get():
                            c = LRUCache(3)
                            c.put("a", 1)
                            c.put("b", 2)
                            assert c.get("a") == 1
                            assert c.get("b") == 2

                        def test_eviction():
                            c = LRUCache(2)
                            c.put("a", 1)
                            c.put("b", 2)
                            c.put("c", 3)  # Should evict "a" (least recently used)
                            assert c.get("a") is None  # Evicted
                            assert c.get("b") == 2
                            assert c.get("c") == 3

                        def test_access_refreshes():
                            c = LRUCache(2)
                            c.put("a", 1)
                            c.put("b", 2)
                            c.get("a")  # Refresh "a" — now "b" is LRU
                            c.put("c", 3)  # Should evict "b"
                            assert c.get("b") is None
                            assert c.get("a") == 1
                            assert c.get("c") == 3

                        def test_update_existing():
                            c = LRUCache(2)
                            c.put("a", 1)
                            c.put("b", 2)
                            c.put("a", 10)  # Update, not new entry
                            assert c.size() == 2
                            assert c.get("a") == 10

                        def test_capacity_one():
                            c = LRUCache(1)
                            c.put("a", 1)
                            c.put("b", 2)
                            assert c.get("a") is None
                            assert c.get("b") == 2

                        def test_keys_order():
                            c = LRUCache(3)
                            c.put("a", 1)
                            c.put("b", 2)
                            c.put("c", 3)
                            c.get("a")  # a is now most recent
                            assert c.keys() == ["b", "c", "a"]
                    """),
                },
            ),
            ground_truth="Fix eviction: change popitem(last=True) to popitem(last=False) to evict the least recently used (first) item instead of the most recently used (last) item",
            eval_spec=EvalSpec(
                method=EvalMethod.COMMAND_OUTPUT,
                check_command="python3 -m pytest test_cache.py -p no:xdist -p no:randomly -p no:cacheprovider -v 2>&1",
                output_contains=["6 passed"],
                output_not_contains=["FAILED", "ERROR"],
            ),
            capabilities=[
                Capability.TEST_RUNNING,
                Capability.ROOT_CAUSE_ANALYSIS,
                Capability.CODE_READING,
                Capability.CODE_EDITING,
            ],
            source="repo_debug_generator:race_condition_in_cache",
            estimated_minutes=5,
        )
