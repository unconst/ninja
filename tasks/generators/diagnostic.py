"""
Diagnostic task generator — boundary-probing tasks designed to find failure modes.

These tasks are intentionally harder than other categories. They probe:
1. Multi-file architectural reasoning (5+ interconnected files)
2. Non-obvious root causes (symptom far from source)
3. Conflicting requirements requiring trade-off decisions
4. Verification of own generated code (catch subtle bugs)
5. Large codebase navigation (many files, one relevant)
6. Long reasoning chains (must connect 4+ pieces of evidence)
"""

import textwrap
from ..schema import (
    Task, TaskCategory, Capability, EvalMethod,
    EnvironmentSetup, EvalSpec
)
from .base import TaskGenerator


class DiagnosticGenerator(TaskGenerator):
    """Generates boundary-probing diagnostic tasks."""

    @property
    def category(self) -> TaskCategory:
        return TaskCategory.DIAGNOSTIC

    def generate(self, count: int = 5, difficulty: str = "hard") -> list[Task]:
        generators = [
            self._distant_root_cause,
            self._multi_file_cascade,
            self._subtle_semantic_bug,
            self._conflicting_tests,
            self._large_codebase_needle,
            self._circular_dependency_fix,
            self._performance_regression,
            self._verify_own_implementation,
        ]

        tasks = []
        for i in range(count):
            gen = generators[i % len(generators)]
            task = gen(difficulty)
            tasks.append(task)
        return tasks

    def _distant_root_cause(self, difficulty: str) -> Task:
        """Bug symptoms appear in file C, but root cause is in file A which affects B which affects C."""
        return Task(
            category=TaskCategory.DIAGNOSTIC,
            title="Fix crash — root cause 3 files away from symptom",
            difficulty=difficulty,
            goal=textwrap.dedent("""\
                The application crashes when processing orders.
                Run: `python3 main.py`

                The error appears in order_processor.py but the fix is NOT there.
                Trace the actual root cause and fix it.
                After fixing, `python3 main.py` should print "All orders processed successfully"
            """),
            environment=EnvironmentSetup(
                env_type="directory",
                seed_files={
                    "main.py": textwrap.dedent("""\
                        from order_processor import process_all_orders

                        orders = [
                            {"id": 1, "items": ["apple", "banana"], "customer": "alice"},
                            {"id": 2, "items": ["cherry"], "customer": "bob"},
                            {"id": 3, "items": ["date", "elderberry", "fig"], "customer": "carol"},
                        ]

                        results = process_all_orders(orders)
                        print("All orders processed successfully")
                        for r in results:
                            print(f"  Order {r['id']}: {r['status']} (total: ${r['total']:.2f})")
                    """),
                    "order_processor.py": textwrap.dedent("""\
                        from pricing import calculate_order_total
                        from validator import validate_order

                        def process_all_orders(orders):
                            results = []
                            for order in orders:
                                validated = validate_order(order)
                                total = calculate_order_total(validated)
                                results.append({
                                    "id": order["id"],
                                    "status": "complete",
                                    "total": total,
                                })
                            return results
                    """),
                    "validator.py": textwrap.dedent("""\
                        from config import get_config

                        def validate_order(order):
                            config = get_config()
                            max_items = config["max_items_per_order"]
                            if len(order["items"]) > max_items:
                                order["items"] = order["items"][:max_items]
                            # Add normalized customer name
                            order["customer_normalized"] = order["customer"].upper()
                            return order
                    """),
                    "pricing.py": textwrap.dedent("""\
                        PRICES = {
                            "apple": 1.50, "banana": 0.75, "cherry": 2.00,
                            "date": 3.50, "elderberry": 4.00, "fig": 2.50,
                        }

                        def calculate_order_total(order):
                            total = 0
                            for item in order["items"]:
                                total += PRICES[item]
                            # Apply discount for validated customers
                            if order.get("customer_normalized"):
                                total *= 0.9  # 10% discount
                            return total
                    """),
                    "config.py": textwrap.dedent("""\
                        _CONFIG = None

                        def get_config():
                            global _CONFIG
                            if _CONFIG is None:
                                _CONFIG = _load_config()
                            return _CONFIG

                        def _load_config():
                            # Bug: max_items should be an int, but it's a string from "config file"
                            return {
                                "max_items_per_order": "5",  # Should be int 5
                                "currency": "USD",
                                "tax_rate": 0.08,
                            }
                    """),
                },
            ),
            ground_truth="The root cause is in config.py: max_items_per_order is '5' (string) not 5 (int). "
                        "The comparison len(items) > max_items in validator.py compares int > str, which "
                        "raises TypeError in Python 3. Fix: change '5' to 5 in config.py.",
            eval_spec=EvalSpec(
                method=EvalMethod.COMMAND_OUTPUT,
                check_command="python3 main.py 2>&1",
                output_contains=["All orders processed successfully"],
                output_not_contains=["Error", "Traceback", "TypeError"],
            ),
            capabilities=[
                Capability.ROOT_CAUSE_ANALYSIS,
                Capability.CODE_READING,
                Capability.CODE_EDITING,
                Capability.MULTI_FILE_REASONING,
                Capability.ERROR_INTERPRETATION,
            ],
            source="diagnostic_generator:distant_root_cause",
            estimated_minutes=10,
        )

    def _multi_file_cascade(self, difficulty: str) -> Task:
        """Changing one file requires coordinated changes in 4 other files."""
        return Task(
            category=TaskCategory.DIAGNOSTIC,
            title="Add new user role requiring changes across 5 files",
            difficulty=difficulty,
            goal=textwrap.dedent("""\
                This project has a role-based access control system spread across 5 files.
                Add a new role "moderator" with these permissions:
                - Can read and write posts (like editor)
                - Can delete posts (like admin)
                - Cannot manage users (unlike admin)
                - Has access level 3 (between editor=2 and admin=4)

                Run tests: `python3 -m pytest test_rbac.py -p no:xdist -p no:randomly -p no:cacheprovider -v`
                All tests must pass including the new moderator tests.
            """),
            environment=EnvironmentSetup(
                env_type="directory",
                seed_files={
                    "roles.py": textwrap.dedent("""\
                        from enum import IntEnum

                        class Role(IntEnum):
                            VIEWER = 1
                            EDITOR = 2
                            ADMIN = 4

                        ROLE_NAMES = {
                            Role.VIEWER: "Viewer",
                            Role.EDITOR: "Editor",
                            Role.ADMIN: "Admin",
                        }
                    """),
                    "permissions.py": textwrap.dedent("""\
                        from roles import Role

                        # Permission matrix: role -> set of allowed actions
                        PERMISSIONS = {
                            Role.VIEWER: {"read_posts"},
                            Role.EDITOR: {"read_posts", "write_posts"},
                            Role.ADMIN: {"read_posts", "write_posts", "delete_posts", "manage_users"},
                        }

                        def has_permission(role: Role, action: str) -> bool:
                            return action in PERMISSIONS.get(role, set())

                        def get_permissions(role: Role) -> set:
                            return PERMISSIONS.get(role, set()).copy()
                    """),
                    "user.py": textwrap.dedent("""\
                        from roles import Role, ROLE_NAMES
                        from permissions import has_permission

                        class User:
                            def __init__(self, name: str, role: Role):
                                self.name = name
                                self.role = role

                            def can(self, action: str) -> bool:
                                return has_permission(self.role, action)

                            def role_name(self) -> str:
                                return ROLE_NAMES.get(self.role, "Unknown")

                            def __repr__(self):
                                return f"User({self.name}, {self.role_name()})"
                    """),
                    "access_control.py": textwrap.dedent("""\
                        from roles import Role
                        from permissions import has_permission

                        def check_access(user, resource_type: str, action: str) -> bool:
                            \"\"\"Check if a user can perform an action on a resource type.\"\"\"
                            full_action = f"{action}_{resource_type}"
                            return has_permission(user.role, full_action)

                        def get_accessible_roles(action: str) -> list:
                            \"\"\"Get all roles that can perform a given action.\"\"\"
                            from permissions import PERMISSIONS
                            return [role for role, perms in PERMISSIONS.items() if action in perms]

                        def minimum_role_for(action: str) -> Role:
                            \"\"\"Get the minimum role that can perform an action.\"\"\"
                            roles = get_accessible_roles(action)
                            if not roles:
                                raise ValueError(f"No role has permission: {action}")
                            return min(roles)
                    """),
                    "test_rbac.py": textwrap.dedent("""\
                        import pytest
                        from roles import Role, ROLE_NAMES
                        from permissions import has_permission, get_permissions
                        from user import User
                        from access_control import check_access, get_accessible_roles, minimum_role_for

                        # Existing tests
                        def test_viewer_permissions():
                            assert has_permission(Role.VIEWER, "read_posts")
                            assert not has_permission(Role.VIEWER, "write_posts")

                        def test_editor_permissions():
                            assert has_permission(Role.EDITOR, "read_posts")
                            assert has_permission(Role.EDITOR, "write_posts")
                            assert not has_permission(Role.EDITOR, "delete_posts")

                        def test_admin_permissions():
                            assert has_permission(Role.ADMIN, "read_posts")
                            assert has_permission(Role.ADMIN, "write_posts")
                            assert has_permission(Role.ADMIN, "delete_posts")
                            assert has_permission(Role.ADMIN, "manage_users")

                        def test_user_can():
                            admin = User("alice", Role.ADMIN)
                            assert admin.can("manage_users")
                            viewer = User("bob", Role.VIEWER)
                            assert not viewer.can("delete_posts")

                        def test_role_names():
                            assert ROLE_NAMES[Role.VIEWER] == "Viewer"
                            assert ROLE_NAMES[Role.ADMIN] == "Admin"

                        def test_access_control():
                            admin = User("alice", Role.ADMIN)
                            assert check_access(admin, "posts", "read")
                            viewer = User("bob", Role.VIEWER)
                            assert not check_access(viewer, "posts", "delete")

                        def test_minimum_role():
                            assert minimum_role_for("read_posts") == Role.VIEWER
                            assert minimum_role_for("manage_users") == Role.ADMIN

                        # Tests for the NEW moderator role
                        def test_moderator_exists():
                            assert hasattr(Role, "MODERATOR")
                            assert Role.MODERATOR == 3

                        def test_moderator_name():
                            assert ROLE_NAMES[Role.MODERATOR] == "Moderator"

                        def test_moderator_permissions():
                            assert has_permission(Role.MODERATOR, "read_posts")
                            assert has_permission(Role.MODERATOR, "write_posts")
                            assert has_permission(Role.MODERATOR, "delete_posts")
                            assert not has_permission(Role.MODERATOR, "manage_users")

                        def test_moderator_user():
                            mod = User("charlie", Role.MODERATOR)
                            assert mod.can("delete_posts")
                            assert not mod.can("manage_users")
                            assert mod.role_name() == "Moderator"

                        def test_moderator_access_control():
                            mod = User("charlie", Role.MODERATOR)
                            assert check_access(mod, "posts", "delete")
                            assert not check_access(mod, "users", "manage")

                        def test_moderator_in_accessible_roles():
                            roles = get_accessible_roles("delete_posts")
                            assert Role.MODERATOR in roles
                            assert Role.ADMIN in roles

                        def test_moderator_level():
                            assert Role.VIEWER < Role.MODERATOR < Role.ADMIN

                        def test_delete_minimum_role():
                            # With moderator, minimum role for delete should be MODERATOR, not ADMIN
                            assert minimum_role_for("delete_posts") == Role.MODERATOR
                    """),
                },
            ),
            ground_truth="Must modify roles.py (add MODERATOR=3), permissions.py (add moderator perms), "
                        "and ROLE_NAMES in roles.py (add Moderator entry). All 4 existing files "
                        "need awareness of the new role. The IntEnum ordering matters.",
            eval_spec=EvalSpec(
                method=EvalMethod.COMMAND_OUTPUT,
                check_command="python3 -m pytest test_rbac.py -p no:xdist -p no:randomly -p no:cacheprovider -v 2>&1",
                output_contains=["passed"],
                output_not_contains=["FAILED", "ERROR"],
            ),
            capabilities=[
                Capability.CODE_READING,
                Capability.CODE_EDITING,
                Capability.MULTI_FILE_REASONING,
                Capability.DECOMPOSITION,
                Capability.TEST_RUNNING,
            ],
            source="diagnostic_generator:multi_file_cascade",
            estimated_minutes=10,
        )

    def _subtle_semantic_bug(self, difficulty: str) -> Task:
        """Code that runs without errors but produces subtly wrong results."""
        return Task(
            category=TaskCategory.DIAGNOSTIC,
            title="Fix statistics library producing wrong results",
            difficulty=difficulty,
            goal=textwrap.dedent("""\
                The statistics library passes most tests but several are failing.
                Run: `python3 -m pytest test_stats.py -p no:xdist -p no:randomly -p no:cacheprovider -v`

                The bugs are SUBTLE — the code runs without errors but produces
                wrong numerical results. Read the tests carefully to understand what
                the correct behavior should be.

                Do NOT just make the tests pass by changing expected values.
                Fix the implementation bugs.
            """),
            environment=EnvironmentSetup(
                env_type="directory",
                seed_files={
                    "stats.py": textwrap.dedent("""\
                        import math

                        def mean(data):
                            if not data:
                                raise ValueError("data must not be empty")
                            return sum(data) / len(data)

                        def median(data):
                            if not data:
                                raise ValueError("data must not be empty")
                            sorted_data = sorted(data)
                            n = len(sorted_data)
                            mid = n // 2
                            if n % 2 == 0:
                                # Bug: should average two middle elements, but uses wrong indices
                                return (sorted_data[mid] + sorted_data[mid + 1]) / 2
                            return sorted_data[mid]

                        def variance(data):
                            if len(data) < 2:
                                raise ValueError("need at least 2 data points")
                            m = mean(data)
                            # Bug: population variance instead of sample variance (divides by n, not n-1)
                            return sum((x - m) ** 2 for x in data) / len(data)

                        def std_dev(data):
                            return math.sqrt(variance(data))

                        def percentile(data, p):
                            if not data:
                                raise ValueError("data must not be empty")
                            if not (0 <= p <= 100):
                                raise ValueError("percentile must be 0-100")
                            sorted_data = sorted(data)
                            # Bug: off-by-one in index calculation
                            idx = (p / 100) * len(sorted_data)
                            if idx == int(idx):
                                return sorted_data[int(idx)]
                            lower = int(idx)
                            upper = lower + 1
                            if upper >= len(sorted_data):
                                return sorted_data[-1]
                            frac = idx - lower
                            return sorted_data[lower] * (1 - frac) + sorted_data[upper] * frac

                        def correlation(x, y):
                            if len(x) != len(y):
                                raise ValueError("x and y must have same length")
                            if len(x) < 2:
                                raise ValueError("need at least 2 data points")
                            mx, my = mean(x), mean(y)
                            numerator = sum((xi - mx) * (yi - my) for xi, yi in zip(x, y))
                            # Bug: uses population std (n) instead of consistent formula
                            dx = math.sqrt(sum((xi - mx) ** 2 for xi in x) / len(x))
                            dy = math.sqrt(sum((yi - my) ** 2 for yi in y) / len(y))
                            if dx == 0 or dy == 0:
                                return 0.0
                            return numerator / (len(x) * dx * dy)
                    """),
                    "test_stats.py": textwrap.dedent("""\
                        import pytest
                        import math
                        from stats import mean, median, variance, std_dev, percentile, correlation

                        def test_mean_basic():
                            assert mean([1, 2, 3, 4, 5]) == 3.0

                        def test_mean_single():
                            assert mean([42]) == 42.0

                        def test_mean_empty():
                            with pytest.raises(ValueError):
                                mean([])

                        def test_median_odd():
                            assert median([3, 1, 2]) == 2

                        def test_median_even():
                            # Median of [1, 2, 3, 4] should be (2+3)/2 = 2.5
                            assert median([4, 1, 3, 2]) == 2.5

                        def test_median_single():
                            assert median([7]) == 7

                        def test_variance_sample():
                            # Sample variance of [2, 4, 4, 4, 5, 5, 7, 9]
                            # Mean = 5, sum of squared diffs = 32, n-1 = 7
                            # Sample variance = 32/7 ≈ 4.571
                            data = [2, 4, 4, 4, 5, 5, 7, 9]
                            assert abs(variance(data) - 4.571428571) < 0.001

                        def test_std_dev():
                            data = [2, 4, 4, 4, 5, 5, 7, 9]
                            assert abs(std_dev(data) - math.sqrt(4.571428571)) < 0.001

                        def test_percentile_50():
                            # 50th percentile = median
                            data = [1, 2, 3, 4, 5]
                            assert percentile(data, 50) == 3

                        def test_percentile_25():
                            data = [1, 2, 3, 4, 5, 6, 7, 8]
                            # 25th percentile of [1,2,3,4,5,6,7,8]
                            # index = 0.25 * 8 = 2.0, so value at index 2 = 3
                            # But with proper 0-based: idx = (p/100) * (n-1) = 0.25*7 = 1.75
                            # interpolate: data[1]*(1-0.75) + data[2]*0.75 = 2*0.25 + 3*0.75 = 2.75
                            assert abs(percentile(data, 25) - 2.75) < 0.01

                        def test_percentile_0():
                            assert percentile([5, 10, 15], 0) == 5

                        def test_percentile_100():
                            assert percentile([5, 10, 15], 100) == 15

                        def test_correlation_perfect():
                            x = [1, 2, 3, 4, 5]
                            y = [2, 4, 6, 8, 10]
                            assert abs(correlation(x, y) - 1.0) < 0.001

                        def test_correlation_negative():
                            x = [1, 2, 3, 4, 5]
                            y = [10, 8, 6, 4, 2]
                            assert abs(correlation(x, y) - (-1.0)) < 0.001

                        def test_correlation_zero():
                            # Perpendicular data should have ~0 correlation
                            x = [1, 0, -1, 0]
                            y = [0, 1, 0, -1]
                            assert abs(correlation(x, y)) < 0.1
                    """),
                },
            ),
            ground_truth="Three bugs: 1) median uses mid and mid+1 but should use mid-1 and mid for even-length, "
                        "2) variance divides by n (population) instead of n-1 (sample), "
                        "3) percentile index should be (p/100)*(n-1) not (p/100)*n, "
                        "4) correlation numerator should divide by (n-1) not n",
            eval_spec=EvalSpec(
                method=EvalMethod.COMMAND_OUTPUT,
                check_command="python3 -m pytest test_stats.py -p no:xdist -p no:randomly -p no:cacheprovider -v 2>&1",
                output_contains=["passed"],
                output_not_contains=["FAILED", "ERROR"],
            ),
            capabilities=[
                Capability.CODE_READING,
                Capability.CODE_EDITING,
                Capability.ROOT_CAUSE_ANALYSIS,
                Capability.HYPOTHESIS_TESTING,
                Capability.TEST_RUNNING,
            ],
            source="diagnostic_generator:subtle_semantic_bug",
            estimated_minutes=15,
        )

    def _conflicting_tests(self, difficulty: str) -> Task:
        """Two test files that define conflicting expected behavior — must reconcile."""
        return Task(
            category=TaskCategory.DIAGNOSTIC,
            title="Fix code to satisfy two conflicting test suites",
            difficulty=difficulty,
            goal=textwrap.dedent("""\
                The cache module has TWO test files: test_behavior.py and test_threading.py.
                Currently both are failing.

                The challenge: the tests have conflicting requirements:
                - test_behavior.py expects the cache to be LRU (evict least recently used)
                - test_threading.py expects thread-safe access with a lock
                - Both must pass simultaneously

                Fix cache.py to satisfy ALL tests from BOTH files.
                Run: `python3 -m pytest test_behavior.py test_threading.py -p no:xdist -p no:randomly -p no:cacheprovider -v`
            """),
            environment=EnvironmentSetup(
                env_type="directory",
                seed_files={
                    "cache.py": textwrap.dedent("""\
                        import threading

                        class Cache:
                            def __init__(self, maxsize=100):
                                self.maxsize = maxsize
                                self._store = {}
                                self._access_order = []
                                # Lock exists but isn't used anywhere
                                self._lock = threading.Lock()

                            def get(self, key):
                                if key in self._store:
                                    # Bug: doesn't update access order
                                    return self._store[key]
                                return None

                            def put(self, key, value):
                                if key in self._store:
                                    self._store[key] = value
                                    return
                                if len(self._store) >= self.maxsize:
                                    # Bug: evicts most recent, not least recent
                                    victim = self._access_order.pop()
                                    del self._store[victim]
                                self._store[key] = value
                                self._access_order.append(key)

                            def delete(self, key):
                                if key in self._store:
                                    del self._store[key]
                                    self._access_order.remove(key)

                            def size(self):
                                return len(self._store)

                            def clear(self):
                                self._store.clear()
                                self._access_order.clear()
                    """),
                    "test_behavior.py": textwrap.dedent("""\
                        import pytest
                        from cache import Cache

                        def test_basic_put_get():
                            c = Cache(10)
                            c.put("a", 1)
                            assert c.get("a") == 1

                        def test_lru_eviction():
                            c = Cache(2)
                            c.put("a", 1)
                            c.put("b", 2)
                            c.put("c", 3)  # Should evict "a" (LRU)
                            assert c.get("a") is None
                            assert c.get("b") == 2
                            assert c.get("c") == 3

                        def test_access_refreshes_lru():
                            c = Cache(2)
                            c.put("a", 1)
                            c.put("b", 2)
                            c.get("a")  # Refresh a; b is now LRU
                            c.put("c", 3)  # Should evict b
                            assert c.get("b") is None
                            assert c.get("a") == 1

                        def test_update_doesnt_evict():
                            c = Cache(2)
                            c.put("a", 1)
                            c.put("b", 2)
                            c.put("a", 10)  # Update, not insert
                            assert c.size() == 2
                            assert c.get("a") == 10

                        def test_delete():
                            c = Cache(10)
                            c.put("a", 1)
                            c.delete("a")
                            assert c.get("a") is None
                            assert c.size() == 0

                        def test_clear():
                            c = Cache(10)
                            c.put("a", 1)
                            c.put("b", 2)
                            c.clear()
                            assert c.size() == 0
                    """),
                    "test_threading.py": textwrap.dedent("""\
                        import pytest
                        import threading
                        import time
                        from cache import Cache

                        def test_concurrent_puts():
                            c = Cache(1000)
                            errors = []

                            def writer(prefix, count):
                                try:
                                    for i in range(count):
                                        c.put(f"{prefix}_{i}", i)
                                except Exception as e:
                                    errors.append(str(e))

                            threads = [threading.Thread(target=writer, args=(f"t{i}", 100)) for i in range(5)]
                            for t in threads: t.start()
                            for t in threads: t.join()

                            assert not errors, f"Errors during concurrent writes: {errors}"
                            assert c.size() <= 1000

                        def test_concurrent_get_put():
                            c = Cache(100)
                            for i in range(50):
                                c.put(f"key_{i}", i)

                            errors = []
                            def reader():
                                try:
                                    for i in range(100):
                                        c.get(f"key_{i % 50}")
                                except Exception as e:
                                    errors.append(str(e))

                            def writer():
                                try:
                                    for i in range(50, 100):
                                        c.put(f"key_{i}", i)
                                except Exception as e:
                                    errors.append(str(e))

                            threads = [threading.Thread(target=reader) for _ in range(3)]
                            threads.append(threading.Thread(target=writer))
                            for t in threads: t.start()
                            for t in threads: t.join()

                            assert not errors, f"Errors: {errors}"

                        def test_concurrent_eviction():
                            c = Cache(10)
                            errors = []

                            def writer():
                                try:
                                    for i in range(100):
                                        c.put(f"key_{i}", i)
                                except Exception as e:
                                    errors.append(str(e))

                            threads = [threading.Thread(target=writer) for _ in range(3)]
                            for t in threads: t.start()
                            for t in threads: t.join()

                            assert not errors, f"Errors during eviction: {errors}"
                            assert c.size() <= 10
                    """),
                },
            ),
            ground_truth="Fix cache.py: 1) use lock in get/put/delete/clear/size, 2) evict LRU (pop from front, "
                         "not back), 3) update access order on get (move to end). All ops must be thread-safe.",
            eval_spec=EvalSpec(
                method=EvalMethod.COMMAND_OUTPUT,
                check_command="python3 -m pytest test_behavior.py test_threading.py -p no:xdist -p no:randomly -p no:cacheprovider -v 2>&1",
                output_contains=["passed"],
                output_not_contains=["FAILED", "ERROR"],
            ),
            capabilities=[
                Capability.CODE_READING,
                Capability.CODE_EDITING,
                Capability.ROOT_CAUSE_ANALYSIS,
                Capability.MULTI_FILE_REASONING,
                Capability.TEST_RUNNING,
                Capability.DECOMPOSITION,
            ],
            source="diagnostic_generator:conflicting_tests",
            estimated_minutes=10,
        )

    def _large_codebase_needle(self, difficulty: str) -> Task:
        """20+ files, bug is in one of them. Tests point to the wrong area."""
        # Generate a project with many files, where the bug is subtly hidden
        seed_files = {}
        # Create a large project structure with many modules
        for i in range(15):
            seed_files[f"modules/module_{i:02d}.py"] = textwrap.dedent(f"""\
                \"\"\"Module {i} — {'data processing' if i < 5 else 'utilities' if i < 10 else 'formatters'}\"\"\"

                def func_{i}_a(x):
                    return x * {i + 1}

                def func_{i}_b(x, y):
                    return x + y + {i}

                def func_{i}_c(items):
                    return [item for item in items if item > {i}]
            """)

        seed_files["modules/__init__.py"] = ""

        # The pipeline imports from several modules
        seed_files["pipeline.py"] = textwrap.dedent("""\
            from modules.module_00 import func_0_a
            from modules.module_03 import func_3_b
            from modules.module_07 import func_7_a, func_7_c
            from modules.module_11 import func_11_b
            from modules.module_14 import func_14_a
            from formatter import format_result

            def run_pipeline(data):
                # Stage 1: scale
                scaled = [func_0_a(x) for x in data]

                # Stage 2: combine pairs
                combined = []
                for i in range(0, len(scaled) - 1, 2):
                    combined.append(func_3_b(scaled[i], scaled[i+1]))
                if len(scaled) % 2 == 1:
                    combined.append(scaled[-1])

                # Stage 3: filter
                filtered = func_7_c(combined)

                # Stage 4: amplify
                amplified = [func_7_a(x) for x in filtered]

                # Stage 5: aggregate
                total = 0
                for x in amplified:
                    total = func_11_b(total, x)

                # Stage 6: final transform
                result = func_14_a(total)

                return format_result(result, len(data))
        """)

        # The bug is in the formatter, not in any module
        seed_files["formatter.py"] = textwrap.dedent("""\
            def format_result(value, count):
                # Bug: integer division truncates result
                average = value // count  # Should be value / count (float division)
                return {
                    "total": value,
                    "count": count,
                    "average": average,
                    "formatted": f"Total: {value}, Avg: {average:.2f}",
                }
        """)

        seed_files["test_pipeline.py"] = textwrap.dedent("""\
            import pytest
            from pipeline import run_pipeline

            def test_small_input():
                result = run_pipeline([1, 2, 3, 4])
                assert result["count"] == 4
                assert result["total"] > 0
                # Average should be float, not truncated int
                assert isinstance(result["average"], float), f"average should be float, got {type(result['average'])}"

            def test_large_input():
                result = run_pipeline(list(range(1, 11)))
                assert result["count"] == 10
                assert result["total"] > 0
                # Average should not lose precision
                assert result["average"] == result["total"] / result["count"]

            def test_formatted_output():
                result = run_pipeline([5, 10, 15])
                # Formatted string should show precise average
                assert ".00" in result["formatted"] or "." in result["formatted"]
                # The average in the string should match the actual average
                avg_str = result["formatted"].split("Avg: ")[1]
                assert float(avg_str) == pytest.approx(result["average"], abs=0.01)
        """)

        return Task(
            category=TaskCategory.DIAGNOSTIC,
            title="Find bug in large project with misleading module structure",
            difficulty=difficulty,
            goal=textwrap.dedent("""\
                This project has 15+ modules in modules/, a pipeline.py, and a formatter.py.
                Tests are failing.

                Run: `python3 -m pytest test_pipeline.py -p no:xdist -p no:randomly -p no:cacheprovider -v`

                Find and fix the bug. It's somewhere in the codebase — might be in any file.
                Don't waste time reading every module. Be strategic about where you look.
            """),
            environment=EnvironmentSetup(
                env_type="directory",
                seed_files=seed_files,
            ),
            ground_truth="Bug is in formatter.py: uses // (integer division) instead of / (float division). "
                        "The modules/ directory is a distraction — the pipeline is fine, it's the output formatting.",
            eval_spec=EvalSpec(
                method=EvalMethod.COMMAND_OUTPUT,
                check_command="python3 -m pytest test_pipeline.py -p no:xdist -p no:randomly -p no:cacheprovider -v 2>&1",
                output_contains=["3 passed"],
                output_not_contains=["FAILED", "ERROR"],
            ),
            capabilities=[
                Capability.CODE_READING,
                Capability.CODE_EDITING,
                Capability.CODE_SEARCH,
                Capability.ROOT_CAUSE_ANALYSIS,
                Capability.FILE_SEARCH,
                Capability.PRIORITIZATION,
            ],
            source="diagnostic_generator:large_codebase_needle",
            estimated_minutes=10,
        )

    def _circular_dependency_fix(self, difficulty: str) -> Task:
        """Code has a circular import that needs architectural thinking to resolve."""
        return Task(
            category=TaskCategory.DIAGNOSTIC,
            title="Fix circular import without restructuring everything",
            difficulty=difficulty,
            goal=textwrap.dedent("""\
                The application crashes on import with: `ImportError: cannot import name 'Registry' from partially initialized module 'registry'`

                This is a circular import issue. Fix it with minimal changes.

                After fix: `python3 main.py` should print "System initialized"
                and `python3 -m pytest test_system.py -p no:xdist -p no:randomly -p no:cacheprovider -v` should pass.

                Do NOT restructure the entire project. Find the minimal fix.
            """),
            environment=EnvironmentSetup(
                env_type="directory",
                seed_files={
                    "main.py": textwrap.dedent("""\
                        from registry import Registry
                        from handlers import DefaultHandler, SpecialHandler

                        reg = Registry()
                        reg.register("default", DefaultHandler)
                        reg.register("special", SpecialHandler)

                        for name, handler_cls in reg.all():
                            h = handler_cls()
                            h.handle({"type": name, "data": "test"})

                        print("System initialized")
                    """),
                    "registry.py": textwrap.dedent("""\
                        class Registry:
                            def __init__(self):
                                self._handlers = {}

                            def register(self, name, handler_cls):
                                self._handlers[name] = handler_cls

                            def get(self, name):
                                return self._handlers.get(name)

                            def all(self):
                                return list(self._handlers.items())

                        # Circular: registry imports from handlers to auto-register defaults
                        from handlers import DefaultHandler
                        _default_registry = Registry()
                        _default_registry.register("default", DefaultHandler)
                    """),
                    "handlers.py": textwrap.dedent("""\
                        # Circular: handlers imports from registry to type-hint
                        from registry import Registry

                        class BaseHandler:
                            registry: Registry = None  # Type hint causes the import

                            def handle(self, event: dict):
                                raise NotImplementedError

                        class DefaultHandler(BaseHandler):
                            def handle(self, event: dict):
                                print(f"Default handling: {event['type']}")

                        class SpecialHandler(BaseHandler):
                            def handle(self, event: dict):
                                print(f"Special handling: {event['type']} - {event.get('data', '')}")
                    """),
                    "test_system.py": textwrap.dedent("""\
                        import pytest

                        def test_import_works():
                            from registry import Registry
                            from handlers import DefaultHandler, SpecialHandler
                            assert Registry is not None

                        def test_registry():
                            from registry import Registry
                            from handlers import DefaultHandler
                            reg = Registry()
                            reg.register("test", DefaultHandler)
                            assert reg.get("test") is DefaultHandler

                        def test_handler():
                            from handlers import DefaultHandler
                            h = DefaultHandler()
                            # Should not raise
                            h.handle({"type": "test"})

                        def test_main_runs(capsys):
                            import subprocess
                            result = subprocess.run(["python3", "main.py"], capture_output=True, text=True, timeout=10)
                            assert result.returncode == 0
                            assert "System initialized" in result.stdout
                    """),
                },
            ),
            ground_truth="Fix by either: 1) moving the auto-registration out of registry.py module scope, "
                        "2) using TYPE_CHECKING import in handlers.py, or 3) using a string annotation. "
                        "The minimal fix is to remove the circular auto-registration at module level in registry.py.",
            eval_spec=EvalSpec(
                method=EvalMethod.COMPOSITE,
                sub_evals=[
                    {
                        "method": "command_output",
                        "check_command": "python3 main.py 2>&1",
                        "output_contains": ["System initialized"],
                        "output_not_contains": ["ImportError", "Traceback"],
                    },
                    {
                        "method": "command_output",
                        "check_command": "python3 -m pytest test_system.py -p no:xdist -p no:randomly -p no:cacheprovider -v 2>&1",
                        "output_contains": ["passed"],
                        "output_not_contains": ["FAILED", "ERROR"],
                    },
                ],
            ),
            capabilities=[
                Capability.CODE_READING,
                Capability.CODE_EDITING,
                Capability.ROOT_CAUSE_ANALYSIS,
                Capability.MULTI_FILE_REASONING,
                Capability.ERROR_INTERPRETATION,
            ],
            source="diagnostic_generator:circular_dependency",
            estimated_minutes=10,
        )

    def _performance_regression(self, difficulty: str) -> Task:
        """Code is correct but too slow — must optimize without breaking tests."""
        return Task(
            category=TaskCategory.DIAGNOSTIC,
            title="Fix performance regression — correct but too slow",
            difficulty=difficulty,
            goal=textwrap.dedent("""\
                The search function works correctly but is too slow for large inputs.

                Run tests: `python3 -m pytest test_search.py -p no:xdist -p no:randomly -p no:cacheprovider -v`

                The correctness tests pass but the performance test times out.
                Optimize the search without breaking any correctness tests.
                The performance test requires completing 100K lookups in under 2 seconds.
            """),
            environment=EnvironmentSetup(
                env_type="directory",
                seed_files={
                    "search.py": textwrap.dedent("""\
                        class TextIndex:
                            def __init__(self):
                                self.documents = []

                            def add(self, doc_id, text):
                                self.documents.append({"id": doc_id, "text": text.lower()})

                            def search(self, query):
                                \"\"\"Find all documents containing the query.\"\"\"
                                query = query.lower()
                                results = []
                                # Bug: O(n) scan for every search — no index
                                for doc in self.documents:
                                    if query in doc["text"]:
                                        results.append(doc["id"])
                                return results

                            def search_all(self, queries):
                                \"\"\"Search for multiple queries, return union of results.\"\"\"
                                all_results = set()
                                for q in queries:
                                    all_results.update(self.search(q))
                                return sorted(all_results)
                    """),
                    "test_search.py": textwrap.dedent("""\
                        import pytest
                        import time
                        from search import TextIndex

                        @pytest.fixture
                        def small_index():
                            idx = TextIndex()
                            idx.add(1, "the quick brown fox")
                            idx.add(2, "jumped over the lazy dog")
                            idx.add(3, "the fox and the hound")
                            return idx

                        def test_basic_search(small_index):
                            assert small_index.search("fox") == [1, 3]

                        def test_no_results(small_index):
                            assert small_index.search("cat") == []

                        def test_case_insensitive(small_index):
                            assert small_index.search("FOX") == [1, 3]

                        def test_multi_word(small_index):
                            assert small_index.search("brown fox") == [1]

                        def test_search_all(small_index):
                            results = small_index.search_all(["fox", "dog"])
                            assert results == [1, 2, 3]

                        def test_empty_query(small_index):
                            # Empty string matches everything
                            assert len(small_index.search("")) == 3

                        def test_add_and_search():
                            idx = TextIndex()
                            idx.add(1, "hello world")
                            assert idx.search("hello") == [1]
                            idx.add(2, "hello again")
                            assert idx.search("hello") == [1, 2]

                        def test_performance():
                            \"\"\"100K lookups on 10K documents must complete in <2s.\"\"\"
                            idx = TextIndex()
                            # Build index with 10K documents
                            words = ["alpha", "beta", "gamma", "delta", "epsilon",
                                     "zeta", "eta", "theta", "iota", "kappa"]
                            for i in range(10000):
                                text = " ".join(words[j] for j in range(10) if (i >> j) & 1)
                                if not text:
                                    text = words[0]
                                idx.add(i, text)

                            # Measure search time
                            start = time.time()
                            for i in range(100000):
                                idx.search(words[i % 10])
                            elapsed = time.time() - start

                            assert elapsed < 2.0, f"Too slow: {elapsed:.2f}s for 100K searches (limit: 2s)"
                    """),
                },
            ),
            ground_truth="Build an inverted index (word -> set of doc_ids) in add(). "
                        "Search looks up words in the index instead of scanning all documents. "
                        "Must handle multi-word queries and substring matching correctly.",
            eval_spec=EvalSpec(
                method=EvalMethod.COMMAND_OUTPUT,
                check_command="python3 -m pytest test_search.py -p no:xdist -p no:randomly -p no:cacheprovider -v 2>&1",
                output_contains=["passed"],
                output_not_contains=["FAILED", "ERROR"],
            ),
            capabilities=[
                Capability.CODE_READING,
                Capability.CODE_EDITING,
                Capability.ROOT_CAUSE_ANALYSIS,
                Capability.TEST_RUNNING,
                Capability.HYPOTHESIS_TESTING,
            ],
            source="diagnostic_generator:performance_regression",
            estimated_minutes=15,
        )

    def _verify_own_implementation(self, difficulty: str) -> Task:
        """Write implementation AND catch deliberate test bugs — must verify both sides."""
        return Task(
            category=TaskCategory.DIAGNOSTIC,
            title="Implement feature and fix the broken test",
            difficulty=difficulty,
            goal=textwrap.dedent("""\
                Implement a `TaskQueue` class in task_queue.py with these features:
                - `push(task, priority)` — add a task with numeric priority (lower = higher priority)
                - `pop()` — remove and return the highest-priority (lowest number) task
                - `peek()` — return highest-priority task without removing
                - `size()` — return number of tasks
                - `is_empty()` — return True if empty
                - Pop/peek should raise `IndexError` when queue is empty

                A test file is provided but WARNING: the test file itself has 2 bugs.
                You must BOTH implement the class AND fix the broken tests.

                Run: `python3 -m pytest test_queue.py -p no:xdist -p no:randomly -p no:cacheprovider -v`
            """),
            environment=EnvironmentSetup(
                env_type="directory",
                seed_files={
                    "task_queue.py": textwrap.dedent("""\
                        # TODO: Implement TaskQueue class
                        pass
                    """),
                    "test_queue.py": textwrap.dedent("""\
                        import pytest
                        from task_queue import TaskQueue

                        def test_push_pop():
                            q = TaskQueue()
                            q.push("low", 10)
                            q.push("high", 1)
                            q.push("med", 5)
                            assert q.pop() == "high"
                            assert q.pop() == "med"
                            assert q.pop() == "low"

                        def test_peek():
                            q = TaskQueue()
                            q.push("a", 3)
                            q.push("b", 1)
                            assert q.peek() == "b"
                            assert q.size() == 2  # peek shouldn't remove

                        def test_empty():
                            q = TaskQueue()
                            assert q.is_empty()
                            q.push("x", 1)
                            assert not q.is_empty()

                        def test_pop_empty():
                            q = TaskQueue()
                            with pytest.raises(IndexError):
                                q.pop()

                        def test_peek_empty():
                            q = TaskQueue()
                            with pytest.raises(IndexError):
                                q.peek()

                        def test_same_priority():
                            q = TaskQueue()
                            q.push("first", 1)
                            q.push("second", 1)
                            # Same priority: FIFO order
                            result = q.pop()
                            assert result == "first"

                        def test_size():
                            q = TaskQueue()
                            assert q.size() == 0
                            q.push("a", 1)
                            q.push("b", 2)
                            assert q.size() == 2
                            q.pop()
                            # Bug: test expects wrong size after pop
                            assert q.size() == 2  # BUG: should be 1

                        def test_mixed_operations():
                            q = TaskQueue()
                            q.push("a", 5)
                            q.push("b", 1)
                            assert q.pop() == "b"
                            q.push("c", 3)
                            q.push("d", 2)
                            assert q.pop() == "d"
                            # Bug: forgets about c, expects wrong value
                            assert q.pop() == "d"  # BUG: should be "c" (the only one with priority 3, and "a" has 5)
                    """),
                },
            ),
            ground_truth="1) Implement TaskQueue using heapq with (priority, insertion_order, task) tuples "
                        "for stable FIFO ordering. 2) Fix test_size: change assert q.size() == 2 to == 1. "
                        "3) Fix test_mixed_operations: change assert q.pop() == 'd' to == 'c'.",
            eval_spec=EvalSpec(
                method=EvalMethod.COMMAND_OUTPUT,
                check_command="python3 -m pytest test_queue.py -p no:xdist -p no:randomly -p no:cacheprovider -v 2>&1",
                output_contains=["8 passed"],
                output_not_contains=["FAILED", "ERROR"],
            ),
            capabilities=[
                Capability.CODE_WRITING,
                Capability.CODE_READING,
                Capability.CODE_EDITING,
                Capability.TEST_RUNNING,
                Capability.HYPOTHESIS_TESTING,
                Capability.ROOT_CAUSE_ANALYSIS,
            ],
            source="diagnostic_generator:verify_own_implementation",
            estimated_minutes=10,
        )
