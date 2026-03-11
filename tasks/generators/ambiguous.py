"""
Ambiguous task generator.

Generates tasks with intentionally underspecified or ambiguous requirements.
The agent must investigate the codebase, read context clues, make reasonable
assumptions, and produce a correct solution. Tests clarification-seeking,
doc_reading, and prioritization capabilities.
"""

import textwrap
from ..schema import (
    Task, TaskCategory, Capability, EvalMethod,
    EnvironmentSetup, EvalSpec
)
from .base import TaskGenerator


class AmbiguousGenerator(TaskGenerator):
    """Generates tasks with ambiguous or underspecified requirements."""

    @property
    def category(self) -> TaskCategory:
        return TaskCategory.AMBIGUOUS

    def generate(self, count: int = 5, difficulty: str = "medium") -> list[Task]:
        generators = [
            self._fix_the_bug,
            self._make_it_work,
            self._clean_up_this_code,
            self._add_error_handling,
            self._update_config,
            self._finish_the_feature,
        ]

        tasks = []
        for i in range(count):
            gen = generators[i % len(generators)]
            task = gen(difficulty)
            tasks.append(task)
        return tasks

    def _fix_the_bug(self, difficulty: str) -> Task:
        """Task: vague 'fix the bug' — agent must find which bug."""
        return Task(
            category=TaskCategory.AMBIGUOUS,
            title="Fix the bug (underspecified)",
            difficulty=difficulty,
            goal=textwrap.dedent("""\
                There's a bug in this project. Fix it.

                Run `python3 main.py` to see it.
            """),
            environment=EnvironmentSetup(
                env_type="directory",
                seed_files={
                    "main.py": textwrap.dedent("""\
                        from processor import process_records
                        from report import print_report

                        def main():
                            records = [
                                {"name": "Alice", "score": 85, "grade": "B"},
                                {"name": "Bob", "score": 92, "grade": "A"},
                                {"name": "Charlie", "score": 78, "grade": "C"},
                                {"name": "Diana", "score": 95, "grade": "A"},
                                {"name": "Eve", "score": 61, "grade": "D"},
                            ]
                            results = process_records(records)
                            print_report(results)

                        if __name__ == '__main__':
                            main()
                    """),
                    "processor.py": textwrap.dedent("""\
                        def process_records(records):
                            \"\"\"Process student records and compute statistics.\"\"\"
                            total = 0
                            passing = []
                            failing = []

                            for r in records:
                                total += r["score"]
                                if r["score"] >= 70:
                                    passing.append(r)
                                else:
                                    failing.append(r)

                            # Bug: divides by len(passing) instead of len(records)
                            average = total / len(passing)

                            return {
                                "total_students": len(records),
                                "average_score": round(average, 1),
                                "passing": passing,
                                "failing": failing,
                                "pass_rate": round(len(passing) / len(records) * 100, 1),
                            }
                    """),
                    "report.py": textwrap.dedent("""\
                        def print_report(results):
                            print(f"Student Report")
                            print(f"=============")
                            print(f"Total: {results['total_students']}")
                            print(f"Average: {results['average_score']}")
                            print(f"Pass rate: {results['pass_rate']}%")
                            print(f"Passing: {len(results['passing'])}, Failing: {len(results['failing'])}")

                            # Sanity check
                            expected_avg = sum(s['score'] for s in results['passing'] + results['failing']) / results['total_students']
                            if abs(results['average_score'] - round(expected_avg, 1)) > 0.1:
                                print(f"WARNING: Average mismatch! Got {results['average_score']}, expected {round(expected_avg, 1)}")
                            else:
                                print("All checks passed.")
                    """),
                },
            ),
            ground_truth="Bug in processor.py: average is computed as total/len(passing) but should be total/len(records). Fix: change len(passing) to len(records).",
            eval_spec=EvalSpec(
                method=EvalMethod.COMMAND_OUTPUT,
                check_command="python3 main.py 2>&1",
                output_contains=["All checks passed"],
                output_not_contains=["WARNING", "Traceback", "Error"],
            ),
            capabilities=[
                Capability.ROOT_CAUSE_ANALYSIS,
                Capability.CODE_READING,
                Capability.CODE_EDITING,
                Capability.MULTI_FILE_REASONING,
                Capability.HYPOTHESIS_TESTING,
            ],
            source="ambiguous_generator:fix_the_bug",
            estimated_minutes=5,
        )

    def _make_it_work(self, difficulty: str) -> Task:
        """Task: vague 'make it work' — multiple things broken."""
        return Task(
            category=TaskCategory.AMBIGUOUS,
            title="Make it work (multiple issues)",
            difficulty=difficulty,
            goal=textwrap.dedent("""\
                This project should process CSV data and output a summary, but it doesn't work.
                Make it work. The output should look correct.
            """),
            environment=EnvironmentSetup(
                env_type="directory",
                seed_files={
                    "run.py": textwrap.dedent("""\
                        from csv_processor import load_csv, summarize

                        def main():
                            data = load_csv("data/sales.csv")
                            summary = summarize(data)
                            print(f"Total revenue: ${summary['total_revenue']:.2f}")
                            print(f"Average order: ${summary['avg_order']:.2f}")
                            print(f"Top product: {summary['top_product']}")
                            print(f"Records: {summary['count']}")
                            print("Processing complete.")

                        if __name__ == '__main__':
                            main()
                    """),
                    "csv_processor.py": textwrap.dedent("""\
                        import csv

                        def load_csv(path):
                            \"\"\"Load CSV file and return list of dicts.\"\"\"
                            with open(path) as f:
                                reader = csv.DictReader(f)
                                return list(reader)

                        def summarize(records):
                            \"\"\"Compute summary statistics from sales records.\"\"\"
                            total = 0
                            product_totals = {}

                            for r in records:
                                # Bug 1: CSV values are strings, not floats
                                amount = r["quantity"] * r["price"]
                                total += amount

                                product = r["product"]
                                if product not in product_totals:
                                    product_totals[product] = 0
                                product_totals[product] += amount

                            # Bug 2: max of empty dict crashes if no records
                            top_product = max(product_totals, key=product_totals.get)

                            return {
                                "total_revenue": total,
                                "avg_order": total / len(records),
                                "top_product": top_product,
                                "count": len(records),
                            }
                    """),
                    "data/sales.csv": textwrap.dedent("""\
                        product,quantity,price
                        Widget A,5,10.99
                        Widget B,2,24.50
                        Widget A,3,10.99
                        Widget C,1,7.25
                        Widget B,4,24.50
                    """).lstrip(),
                },
            ),
            ground_truth="Bug: quantity and price are strings from CSV. Fix: amount = float(r['quantity']) * float(r['price']). This also fixes the str*str TypeError.",
            eval_spec=EvalSpec(
                method=EvalMethod.COMPOSITE,
                sub_evals=[
                    {"method": "command_output",
                     "check_command": "python3 run.py 2>&1",
                     "output_contains": ["Processing complete", "Total revenue"],
                     "output_not_contains": ["Error", "Traceback"]},
                    {"method": "command_output",
                     "check_command": "python3 -c \"from csv_processor import load_csv, summarize; d=load_csv('data/sales.csv'); s=summarize(d); assert abs(s['total_revenue']-242.17)<0.1, f'wrong total: {s}'; print('OK')\" 2>&1",
                     "output_contains": ["OK"]},
                ]
            ),
            capabilities=[
                Capability.ERROR_INTERPRETATION,
                Capability.ROOT_CAUSE_ANALYSIS,
                Capability.CODE_READING,
                Capability.CODE_EDITING,
                Capability.HYPOTHESIS_TESTING,
            ],
            source="ambiguous_generator:make_it_work",
            estimated_minutes=5,
        )

    def _clean_up_this_code(self, difficulty: str) -> Task:
        """Task: vague 'clean up' — but there's a hidden functional bug too."""
        return Task(
            category=TaskCategory.AMBIGUOUS,
            title="Clean up this code (hidden bug)",
            difficulty=difficulty,
            goal=textwrap.dedent("""\
                Clean up this code. The tests should pass after cleanup.
                Run: `python3 -m pytest test_utils.py -p no:xdist -p no:randomly -p no:cacheprovider -v`
            """),
            environment=EnvironmentSetup(
                env_type="directory",
                seed_files={
                    "utils.py": textwrap.dedent("""\
                        # TODO: clean up this mess

                        def flatten(lst):
                            result = []
                            for item in lst:
                                if isinstance(item, list):
                                    # Bug: only flattens one level, should recurse
                                    result.extend(item)
                                else:
                                    result.append(item)
                            return result

                        def unique(lst):
                            # Preserves order
                            seen = set()
                            result = []
                            for item in lst:
                                if item not in seen:
                                    seen.add(item)
                                    result.append(item)
                            return result

                        def chunk(lst, size):
                            \"\"\"Split list into chunks of given size.\"\"\"
                            # Bug: uses wrong range step — creates overlapping chunks
                            return [lst[i:i+size] for i in range(0, len(lst), 1)]

                        def merge_dicts(*dicts):
                            result = {}
                            for d in dicts:
                                result.update(d)
                            return result

                        def deep_get(d, path, default=None):
                            \"\"\"Get nested dict value by dot-separated path.\"\"\"
                            keys = path.split(".")
                            current = d
                            for key in keys:
                                if isinstance(current, dict):
                                    current = current.get(key)
                                else:
                                    return default
                            # Bug: returns None instead of default when key exists but is None
                            return current if current is not None else default
                    """),
                    "test_utils.py": textwrap.dedent("""\
                        import pytest
                        from utils import flatten, unique, chunk, merge_dicts, deep_get

                        def test_flatten_simple():
                            assert flatten([1, [2, 3], 4]) == [1, 2, 3, 4]

                        def test_flatten_nested():
                            assert flatten([1, [2, [3, 4]], 5]) == [1, 2, 3, 4, 5]

                        def test_flatten_empty():
                            assert flatten([]) == []

                        def test_unique():
                            assert unique([1, 2, 2, 3, 1, 4]) == [1, 2, 3, 4]

                        def test_unique_empty():
                            assert unique([]) == []

                        def test_chunk_even():
                            assert chunk([1, 2, 3, 4], 2) == [[1, 2], [3, 4]]

                        def test_chunk_uneven():
                            assert chunk([1, 2, 3, 4, 5], 2) == [[1, 2], [3, 4], [5]]

                        def test_chunk_single():
                            assert chunk([1, 2, 3], 1) == [[1], [2], [3]]

                        def test_merge_dicts():
                            result = merge_dicts({"a": 1}, {"b": 2}, {"a": 3})
                            assert result == {"a": 3, "b": 2}

                        def test_deep_get():
                            d = {"a": {"b": {"c": 42}}}
                            assert deep_get(d, "a.b.c") == 42

                        def test_deep_get_missing():
                            d = {"a": {"b": 1}}
                            assert deep_get(d, "a.c.d", "default") == "default"

                        def test_deep_get_none_value():
                            d = {"a": {"b": None}}
                            # None is a valid value — should NOT return default
                            assert deep_get(d, "a.b", "default") is None
                    """),
                },
            ),
            ground_truth="Three bugs: 1) flatten needs recursion for nested lists, 2) chunk range step should be 'size' not '1', 3) deep_get should return current unconditionally (remove None check) to properly handle None values",
            eval_spec=EvalSpec(
                method=EvalMethod.COMMAND_OUTPUT,
                check_command="python3 -m pytest test_utils.py -p no:xdist -p no:randomly -p no:cacheprovider -v 2>&1",
                output_contains=["12 passed"],
                output_not_contains=["FAILED", "ERROR"],
            ),
            capabilities=[
                Capability.TEST_RUNNING,
                Capability.ROOT_CAUSE_ANALYSIS,
                Capability.CODE_READING,
                Capability.CODE_EDITING,
                Capability.HYPOTHESIS_TESTING,
                Capability.PRIORITIZATION,
            ],
            source="ambiguous_generator:clean_up_this_code",
            estimated_minutes=8,
        )

    def _add_error_handling(self, difficulty: str) -> Task:
        """Task: vague 'add error handling' — must infer what to handle."""
        return Task(
            category=TaskCategory.AMBIGUOUS,
            title="Add error handling (infer requirements)",
            difficulty=difficulty,
            goal=textwrap.dedent("""\
                This file processor crashes on bad input. Add appropriate error handling
                so it processes what it can and reports what it couldn't.

                Run the test to verify: `python3 test_processor.py`
                It should print "All tests passed."
            """),
            environment=EnvironmentSetup(
                env_type="directory",
                seed_files={
                    "file_processor.py": textwrap.dedent("""\
                        import json
                        import os

                        def process_file(path):
                            \"\"\"Read a JSON file, extract 'value' field, return as float.\"\"\"
                            with open(path) as f:
                                data = json.load(f)
                            return float(data["value"])

                        def process_directory(dirpath):
                            \"\"\"Process all JSON files in directory. Return results dict.\"\"\"
                            results = {}
                            errors = {}
                            for fname in sorted(os.listdir(dirpath)):
                                if not fname.endswith('.json'):
                                    continue
                                path = os.path.join(dirpath, fname)
                                result = process_file(path)
                                results[fname] = result
                            return {"results": results, "errors": errors}
                    """),
                    "test_processor.py": textwrap.dedent("""\
                        import os
                        import json
                        import tempfile
                        import shutil
                        from file_processor import process_file, process_directory

                        def test_process_valid():
                            d = tempfile.mkdtemp()
                            try:
                                with open(os.path.join(d, "a.json"), "w") as f:
                                    json.dump({"value": 42}, f)
                                result = process_file(os.path.join(d, "a.json"))
                                assert result == 42.0, f"Expected 42.0, got {result}"
                            finally:
                                shutil.rmtree(d)

                        def test_process_missing_file():
                            try:
                                process_file("/nonexistent/path.json")
                                assert False, "Should have raised an error"
                            except (FileNotFoundError, OSError):
                                pass  # expected

                        def test_process_bad_json():
                            d = tempfile.mkdtemp()
                            try:
                                with open(os.path.join(d, "bad.json"), "w") as f:
                                    f.write("not json {{{")
                                try:
                                    process_file(os.path.join(d, "bad.json"))
                                    assert False, "Should have raised an error"
                                except (json.JSONDecodeError, ValueError):
                                    pass  # expected
                            finally:
                                shutil.rmtree(d)

                        def test_process_missing_key():
                            d = tempfile.mkdtemp()
                            try:
                                with open(os.path.join(d, "nokey.json"), "w") as f:
                                    json.dump({"other": 1}, f)
                                try:
                                    process_file(os.path.join(d, "nokey.json"))
                                    assert False, "Should have raised an error"
                                except (KeyError, ValueError):
                                    pass  # expected
                            finally:
                                shutil.rmtree(d)

                        def test_directory_mixed():
                            d = tempfile.mkdtemp()
                            try:
                                # Good file
                                with open(os.path.join(d, "good.json"), "w") as f:
                                    json.dump({"value": 10}, f)
                                # Bad JSON
                                with open(os.path.join(d, "bad.json"), "w") as f:
                                    f.write("{corrupt")
                                # Missing key
                                with open(os.path.join(d, "nokey.json"), "w") as f:
                                    json.dump({"x": 1}, f)
                                # Non-JSON file (should be skipped)
                                with open(os.path.join(d, "readme.txt"), "w") as f:
                                    f.write("ignore me")

                                result = process_directory(d)
                                assert "good.json" in result["results"], f"Missing good.json in {result}"
                                assert result["results"]["good.json"] == 10.0
                                assert "bad.json" in result["errors"], f"bad.json should be in errors: {result}"
                                assert "nokey.json" in result["errors"], f"nokey.json should be in errors: {result}"
                                assert "readme.txt" not in result["results"]
                                assert "readme.txt" not in result["errors"]
                            finally:
                                shutil.rmtree(d)

                        if __name__ == '__main__':
                            test_process_valid()
                            test_process_missing_file()
                            test_process_bad_json()
                            test_process_missing_key()
                            test_directory_mixed()
                            print("All tests passed.")
                    """),
                },
            ),
            ground_truth="Add try/except in process_directory around process_file call. Catch json.JSONDecodeError, KeyError, ValueError and store in errors dict. process_file itself can raise naturally.",
            eval_spec=EvalSpec(
                method=EvalMethod.COMMAND_OUTPUT,
                check_command="python3 test_processor.py 2>&1",
                output_contains=["All tests passed"],
                output_not_contains=["Traceback", "AssertionError"],
            ),
            capabilities=[
                Capability.CODE_READING,
                Capability.CODE_EDITING,
                Capability.HYPOTHESIS_TESTING,
                Capability.PRIORITIZATION,
                Capability.TEST_RUNNING,
            ],
            source="ambiguous_generator:add_error_handling",
            estimated_minutes=5,
        )

    def _update_config(self, difficulty: str) -> Task:
        """Task: vague 'update the config' — must read code to understand what's needed."""
        return Task(
            category=TaskCategory.AMBIGUOUS,
            title="Update the configuration (infer from code)",
            difficulty=difficulty,
            goal=textwrap.dedent("""\
                Update the configuration. The app should start without errors.
                Run `python3 app.py` to check.
            """),
            environment=EnvironmentSetup(
                env_type="directory",
                seed_files={
                    "app.py": textwrap.dedent("""\
                        import json
                        import sys

                        def load_config():
                            with open("config.json") as f:
                                config = json.load(f)

                            # Validate required fields
                            errors = []
                            if config.get("version") != 2:
                                errors.append("Config version must be 2 (current format)")
                            if "database" not in config:
                                errors.append("Missing 'database' section")
                            else:
                                db = config["database"]
                                if "host" not in db:
                                    errors.append("Missing database.host")
                                if "port" not in db:
                                    errors.append("Missing database.port")
                                if not isinstance(db.get("port"), int):
                                    errors.append("database.port must be an integer")
                                if "name" not in db:
                                    errors.append("Missing database.name")

                            if "features" not in config:
                                errors.append("Missing 'features' section")
                            else:
                                feat = config["features"]
                                if not isinstance(feat.get("max_connections"), int):
                                    errors.append("features.max_connections must be an integer")
                                if "enable_cache" not in feat:
                                    errors.append("Missing features.enable_cache")
                                if feat.get("log_level") not in ("debug", "info", "warning", "error"):
                                    errors.append("features.log_level must be debug/info/warning/error")

                            if errors:
                                for e in errors:
                                    print(f"CONFIG ERROR: {e}", file=sys.stderr)
                                sys.exit(1)

                            return config

                        if __name__ == '__main__':
                            config = load_config()
                            print(f"App started with config v{config['version']}")
                            print(f"Database: {config['database']['host']}:{config['database']['port']}/{config['database']['name']}")
                            print(f"Cache: {'enabled' if config['features']['enable_cache'] else 'disabled'}")
                            print(f"Log level: {config['features']['log_level']}")
                            print("Startup complete.")
                    """),
                    "config.json": json.dumps({
                        "version": 1,
                        "database": {
                            "host": "localhost",
                            "port": "5432",
                        },
                        "features": {
                            "max_connections": "10",
                        }
                    }, indent=2) if False else textwrap.dedent("""\
                        {
                            "version": 1,
                            "database": {
                                "host": "localhost",
                                "port": "5432"
                            },
                            "features": {
                                "max_connections": "10"
                            }
                        }
                    """).strip(),
                },
            ),
            ground_truth="Update config.json: version->2, port->5432 (int), add database.name, max_connections->10 (int), add enable_cache (bool), add log_level (valid string)",
            eval_spec=EvalSpec(
                method=EvalMethod.COMMAND_OUTPUT,
                check_command="python3 app.py 2>&1",
                output_contains=["Startup complete"],
                output_not_contains=["CONFIG ERROR", "Traceback"],
            ),
            capabilities=[
                Capability.CODE_READING,
                Capability.CONFIG_READING,
                Capability.CONFIG_EDITING,
                Capability.ROOT_CAUSE_ANALYSIS,
                Capability.PRIORITIZATION,
            ],
            source="ambiguous_generator:update_config",
            estimated_minutes=5,
        )

    def _finish_the_feature(self, difficulty: str) -> Task:
        """Task: vague 'finish this' — partially implemented feature."""
        return Task(
            category=TaskCategory.AMBIGUOUS,
            title="Finish the half-implemented feature",
            difficulty=difficulty,
            goal=textwrap.dedent("""\
                Someone started implementing a task queue but didn't finish.
                There are TODO comments in the code. Finish the implementation.

                Run `python3 test_queue.py` — it should print "All tests passed."
            """),
            environment=EnvironmentSetup(
                env_type="directory",
                seed_files={
                    "task_queue.py": textwrap.dedent("""\
                        from collections import deque
                        from datetime import datetime

                        class TaskQueue:
                            def __init__(self):
                                self._queues = {"high": deque(), "normal": deque(), "low": deque()}
                                self._completed = []

                            def add_task(self, name, priority="normal"):
                                \"\"\"Add a task with given priority.\"\"\"
                                if priority not in self._queues:
                                    raise ValueError(f"Invalid priority: {priority}")
                                task = {
                                    "name": name,
                                    "priority": priority,
                                    "added_at": datetime.now().isoformat(),
                                    "status": "pending",
                                }
                                self._queues[priority].append(task)
                                return task

                            def next_task(self):
                                \"\"\"Get next task by priority (high > normal > low).\"\"\"
                                # TODO: implement — should return highest priority task
                                # and remove it from the queue. Return None if all empty.
                                pass

                            def complete_task(self, task):
                                \"\"\"Mark a task as completed.\"\"\"
                                task["status"] = "completed"
                                task["completed_at"] = datetime.now().isoformat()
                                self._completed.append(task)

                            def pending_count(self):
                                \"\"\"Return total number of pending tasks.\"\"\"
                                # TODO: implement — sum of all queue lengths
                                pass

                            def completed_count(self):
                                return len(self._completed)

                            def stats(self):
                                \"\"\"Return queue statistics.\"\"\"
                                # TODO: implement — return dict with:
                                # "pending": total pending, "completed": completed count,
                                # "by_priority": {"high": N, "normal": N, "low": N}
                                pass
                    """),
                    "test_queue.py": textwrap.dedent("""\
                        from task_queue import TaskQueue

                        def test_add_and_next():
                            q = TaskQueue()
                            q.add_task("low task", "low")
                            q.add_task("high task", "high")
                            q.add_task("normal task", "normal")

                            # Should get high first
                            t = q.next_task()
                            assert t["name"] == "high task", f"Expected high task, got {t}"

                            # Then normal
                            t = q.next_task()
                            assert t["name"] == "normal task", f"Expected normal task, got {t}"

                            # Then low
                            t = q.next_task()
                            assert t["name"] == "low task", f"Expected low task, got {t}"

                            # Then None
                            assert q.next_task() is None

                        def test_complete():
                            q = TaskQueue()
                            q.add_task("task1")
                            t = q.next_task()
                            q.complete_task(t)
                            assert q.completed_count() == 1
                            assert t["status"] == "completed"

                        def test_pending_count():
                            q = TaskQueue()
                            q.add_task("a")
                            q.add_task("b", "high")
                            q.add_task("c", "low")
                            assert q.pending_count() == 3
                            q.next_task()
                            assert q.pending_count() == 2

                        def test_stats():
                            q = TaskQueue()
                            q.add_task("a", "high")
                            q.add_task("b", "high")
                            q.add_task("c", "normal")
                            t = q.next_task()
                            q.complete_task(t)

                            s = q.stats()
                            assert s["pending"] == 2
                            assert s["completed"] == 1
                            assert s["by_priority"]["high"] == 1
                            assert s["by_priority"]["normal"] == 1
                            assert s["by_priority"]["low"] == 0

                        def test_invalid_priority():
                            q = TaskQueue()
                            try:
                                q.add_task("x", "urgent")
                                assert False, "Should raise ValueError"
                            except ValueError:
                                pass

                        if __name__ == '__main__':
                            test_add_and_next()
                            test_complete()
                            test_pending_count()
                            test_stats()
                            test_invalid_priority()
                            print("All tests passed.")
                    """),
                },
            ),
            ground_truth="Implement three TODO methods: next_task (iterate high/normal/low, popleft first non-empty), pending_count (sum of queue lengths), stats (dict with pending, completed, by_priority)",
            eval_spec=EvalSpec(
                method=EvalMethod.COMMAND_OUTPUT,
                check_command="python3 test_queue.py 2>&1",
                output_contains=["All tests passed"],
                output_not_contains=["Traceback", "AssertionError", "Error"],
            ),
            capabilities=[
                Capability.CODE_READING,
                Capability.CODE_WRITING,
                Capability.DOC_READING,
                Capability.DECOMPOSITION,
                Capability.HYPOTHESIS_TESTING,
            ],
            source="ambiguous_generator:finish_the_feature",
            estimated_minutes=8,
        )
