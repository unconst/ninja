#!/usr/bin/env python3
"""
Task generation and evaluation runner.

Usage:
  python tasks/runner.py generate --category local_ops --count 5
  python tasks/runner.py generate --category env_debug --count 5
  python tasks/runner.py generate --all --count 3
  python tasks/runner.py evaluate <task_file> --workdir <dir>
  python tasks/runner.py coverage [--dataset-dir tasks/dataset]
  python tasks/runner.py setup <task_file> [--workdir <dir>]
  python tasks/runner.py run <task_file> --agent <path_to_ninja> [--workdir <dir>]
"""

import argparse
import json
import os
import subprocess
import sys
import tempfile
import time
from pathlib import Path

# Add parent for imports
sys.path.insert(0, str(Path(__file__).parent.parent))

from tasks.schema import Task, TaskCategory
from tasks.generators.local_ops import LocalOpsGenerator
from tasks.generators.env_debug import EnvDebugGenerator
from tasks.generators.data_analysis import DataAnalysisGenerator
from tasks.generators.multi_step import MultiStepGenerator
from tasks.generators.docs_reconciliation import DocsReconciliationGenerator
from tasks.generators.repo_debug import RepoDebugGenerator
from tasks.generators.ambiguous import AmbiguousGenerator
from tasks.generators.web_search import WebSearchGenerator
from tasks.generators.diagnostic import DiagnosticGenerator
from tasks.generators.boundary import BoundaryGenerator
from tasks.evaluators.evaluate import evaluate_task
from tasks.coverage import CoverageTracker


GENERATORS = {
    "local_ops": LocalOpsGenerator(),
    "env_debug": EnvDebugGenerator(),
    "data_analysis": DataAnalysisGenerator(),
    "multi_step": MultiStepGenerator(),
    "docs_reconciliation": DocsReconciliationGenerator(),
    "repo_debug": RepoDebugGenerator(),
    "ambiguous": AmbiguousGenerator(),
    "web_search": WebSearchGenerator(),
    "diagnostic": DiagnosticGenerator(),
    "boundary": BoundaryGenerator(),
}

DATASET_DIR = os.path.join(os.path.dirname(__file__), "dataset")


def cmd_generate(args):
    """Generate tasks."""
    if args.all:
        categories = list(GENERATORS.keys())
    else:
        categories = [args.category]

    total = 0
    for cat in categories:
        gen = GENERATORS.get(cat)
        if not gen:
            print(f"Unknown category: {cat}. Available: {list(GENERATORS.keys())}")
            continue

        print(f"\nGenerating {args.count} {cat} tasks...")
        tasks = gen.generate(count=args.count, difficulty=args.difficulty)

        gen.save_tasks(tasks, DATASET_DIR)
        total += len(tasks)

        for task in tasks:
            issues = gen.validate_task(task)
            status = "OK" if not issues else f"ISSUES: {issues}"
            print(f"  [{task.task_id}] {task.title} ({task.difficulty}) - {status}")

    print(f"\nGenerated {total} tasks in {DATASET_DIR}")


def cmd_setup(args):
    """Set up a task environment for manual inspection or agent run."""
    task = Task.from_json(Path(args.task_file).read_text())

    workdir = args.workdir or tempfile.mkdtemp(prefix=f"task_{task.task_id}_")
    os.makedirs(workdir, exist_ok=True)

    print(f"Setting up task: {task.task_id}")
    print(f"  Title: {task.title}")
    print(f"  Category: {task.category.value}")
    print(f"  Workdir: {workdir}")

    # Create seed files
    env = task.environment
    for filepath, content in env.seed_files.items():
        full_path = os.path.join(workdir, filepath)
        os.makedirs(os.path.dirname(full_path), exist_ok=True)
        Path(full_path).write_text(content)
        print(f"  Created: {filepath}")

    # Run setup commands
    for cmd in env.setup_commands:
        print(f"  Running: {cmd}")
        subprocess.run(cmd, shell=True, cwd=workdir, capture_output=True, timeout=120)

    # Set env vars
    for k, v in env.env_vars.items():
        os.environ[k] = v

    print(f"\nEnvironment ready at: {workdir}")
    print(f"Goal:\n{task.goal}")
    return workdir


def cmd_evaluate(args):
    """Evaluate a completed task."""
    task = Task.from_json(Path(args.task_file).read_text())

    if not args.workdir:
        print("Error: --workdir required for evaluation")
        sys.exit(1)

    print(f"Evaluating: {task.task_id}")
    result = evaluate_task(task, args.workdir)

    print(f"  Passed: {result['passed']}")
    print(f"  Score: {result['score']:.1%}")
    print(f"  Details: {result['details']}")
    for check in result.get("checks", []):
        status = "PASS" if check["passed"] else "FAIL"
        print(f"    [{status}] {check['name']}: {check['detail']}")

    return result


def cmd_run(args):
    """Set up environment, run agent, evaluate."""
    task = Task.from_json(Path(args.task_file).read_text())

    # Setup
    workdir = args.workdir or tempfile.mkdtemp(prefix=f"task_{task.task_id}_")
    os.makedirs(workdir, exist_ok=True)

    env = task.environment
    for filepath, content in env.seed_files.items():
        full_path = os.path.join(workdir, filepath)
        os.makedirs(os.path.dirname(full_path), exist_ok=True)
        Path(full_path).write_text(content)

    for cmd in env.setup_commands:
        subprocess.run(cmd, shell=True, cwd=workdir, capture_output=True, timeout=120)

    # Write prompt file
    prompt_path = os.path.join(workdir, ".task_prompt.md")
    Path(prompt_path).write_text(task.goal)

    # Run agent
    agent = args.agent
    rollout_path = os.path.join(workdir, "rollout.json")

    print(f"Running agent on: {task.task_id}")
    print(f"  Agent: {agent}")
    print(f"  Workdir: {workdir}")

    cmd = [
        agent,
        "--prompt-file", prompt_path,
        "--workdir", workdir,
        "--rollout", rollout_path,
        "--max-iterations", str(args.max_iterations),
    ]

    start = time.time()
    proc = subprocess.run(cmd, capture_output=True, text=True, timeout=args.timeout)
    elapsed = time.time() - start

    print(f"  Agent finished in {elapsed:.1f}s (exit {proc.returncode})")

    # Evaluate
    result = evaluate_task(task, workdir)

    print(f"  Passed: {result['passed']}")
    print(f"  Score: {result['score']:.1%}")
    print(f"  Details: {result['details']}")

    # Save result
    output = {
        "task_id": task.task_id,
        "category": task.category.value,
        "title": task.title,
        "difficulty": task.difficulty,
        "agent": agent,
        "elapsed_seconds": elapsed,
        "exit_code": proc.returncode,
        "result": result,
        "workdir": workdir,
    }

    result_path = os.path.join(DATASET_DIR, "..", "results", f"{task.task_id}_{int(time.time())}.json")
    os.makedirs(os.path.dirname(result_path), exist_ok=True)
    Path(result_path).write_text(json.dumps(output, indent=2))
    print(f"  Result saved: {result_path}")

    return output


def cmd_coverage(args):
    """Show coverage report."""
    dataset_dir = args.dataset_dir or DATASET_DIR
    tracker = CoverageTracker(dataset_dir)
    print(tracker.summary())

    suggestions = tracker.suggest_next_tasks(n=10)
    if suggestions and args.verbose:
        print("\nDetailed Suggestions:")
        for s in suggestions:
            print(f"  [{s['priority']}] {s['reason']}")
            print(f"    -> {s['suggestion']}")


def cmd_batch(args):
    """Run all tasks in a category (or all) through the agent."""
    import concurrent.futures

    agent = args.agent
    task_files = sorted(Path(DATASET_DIR).glob("*.json"))

    if args.category:
        task_files = [f for f in task_files if f.name.startswith(args.category)]

    if args.sample and args.sample < len(task_files):
        import random
        random.seed(42)
        task_files = random.sample(task_files, args.sample)

    print(f"Batch run: {len(task_files)} tasks, agent={agent}, "
          f"max_iter={args.max_iterations}, timeout={args.timeout}s")

    results = []

    def run_single(task_file):
        try:
            task = Task.from_json(task_file.read_text())

            # Setup
            workdir = tempfile.mkdtemp(prefix=f"task_{task.task_id}_")
            env = task.environment
            for filepath, content in env.seed_files.items():
                full_path = os.path.join(workdir, filepath)
                os.makedirs(os.path.dirname(full_path), exist_ok=True)
                Path(full_path).write_text(content)
            for cmd in env.setup_commands:
                subprocess.run(cmd, shell=True, cwd=workdir, capture_output=True, timeout=120)

            # Write prompt
            prompt_path = os.path.join(workdir, ".task_prompt.md")
            Path(prompt_path).write_text(task.goal)

            # Run agent
            rollout_path = os.path.join(workdir, "rollout.json")
            cmd = [
                agent,
                "--prompt-file", prompt_path,
                "--workdir", workdir,
                "--rollout", rollout_path,
                "--max-iterations", str(args.max_iterations),
            ]

            start = time.time()
            proc = subprocess.run(cmd, capture_output=True, text=True, timeout=args.timeout)
            elapsed = time.time() - start

            # Evaluate
            result = evaluate_task(task, workdir)

            return {
                "task_id": task.task_id,
                "category": task.category.value,
                "title": task.title,
                "passed": result["passed"],
                "score": result["score"],
                "elapsed": elapsed,
                "exit_code": proc.returncode,
            }
        except subprocess.TimeoutExpired:
            return {
                "task_id": task.task_id if 'task' in dir() else str(task_file),
                "category": "timeout",
                "title": "",
                "passed": False,
                "score": 0.0,
                "elapsed": args.timeout,
                "exit_code": -1,
            }
        except Exception as e:
            return {
                "task_id": str(task_file.stem),
                "category": "error",
                "title": "",
                "passed": False,
                "score": 0.0,
                "elapsed": 0,
                "exit_code": -1,
                "error": str(e),
            }

    with concurrent.futures.ThreadPoolExecutor(max_workers=args.concurrency) as pool:
        futures = {pool.submit(run_single, f): f for f in task_files}
        for future in concurrent.futures.as_completed(futures):
            r = future.result()
            status = "PASS" if r["passed"] else "FAIL"
            print(f"  [{status}] {r['task_id']:40s} {r['score']:.0%} {r['elapsed']:.0f}s")
            results.append(r)

    # Summary
    passed = sum(1 for r in results if r["passed"])
    print(f"\n{'='*60}")
    print(f"Results: {passed}/{len(results)} passed ({passed/len(results)*100:.1f}%)")
    by_cat = {}
    for r in results:
        cat = r["category"]
        if cat not in by_cat:
            by_cat[cat] = {"pass": 0, "total": 0}
        by_cat[cat]["total"] += 1
        if r["passed"]:
            by_cat[cat]["pass"] += 1
    for cat, counts in sorted(by_cat.items()):
        print(f"  {cat:25s} {counts['pass']}/{counts['total']}")

    # Save batch results
    batch_path = os.path.join(DATASET_DIR, "..", "results",
                               f"batch_{int(time.time())}.json")
    os.makedirs(os.path.dirname(batch_path), exist_ok=True)
    Path(batch_path).write_text(json.dumps(results, indent=2))
    print(f"Batch results: {batch_path}")


def main():
    parser = argparse.ArgumentParser(description="Task generation and evaluation runner")
    sub = parser.add_subparsers(dest="command", help="Command")

    # generate
    gen_p = sub.add_parser("generate", help="Generate tasks")
    gen_p.add_argument("--category", "-c", choices=list(GENERATORS.keys()), help="Category")
    gen_p.add_argument("--all", "-a", action="store_true", help="Generate for all categories")
    gen_p.add_argument("--count", "-n", type=int, default=5, help="Number of tasks per category")
    gen_p.add_argument("--difficulty", "-d", default="medium", choices=["easy", "medium", "hard"])

    # setup
    setup_p = sub.add_parser("setup", help="Set up task environment")
    setup_p.add_argument("task_file", help="Path to task JSON")
    setup_p.add_argument("--workdir", "-w", help="Working directory")

    # evaluate
    eval_p = sub.add_parser("evaluate", help="Evaluate completed task")
    eval_p.add_argument("task_file", help="Path to task JSON")
    eval_p.add_argument("--workdir", "-w", required=True, help="Working directory")

    # run
    run_p = sub.add_parser("run", help="Setup + run agent + evaluate")
    run_p.add_argument("task_file", help="Path to task JSON")
    run_p.add_argument("--agent", "-a", required=True, help="Path to agent binary")
    run_p.add_argument("--workdir", "-w", help="Working directory")
    run_p.add_argument("--max-iterations", type=int, default=50)
    run_p.add_argument("--timeout", type=int, default=600)

    # batch
    batch_p = sub.add_parser("batch", help="Run all tasks through agent")
    batch_p.add_argument("--agent", "-a", required=True, help="Path to agent binary")
    batch_p.add_argument("--category", "-c", help="Filter by category prefix")
    batch_p.add_argument("--sample", "-s", type=int, help="Random sample of N tasks")
    batch_p.add_argument("--concurrency", type=int, default=3, help="Parallel tasks")
    batch_p.add_argument("--max-iterations", type=int, default=30)
    batch_p.add_argument("--timeout", type=int, default=300)

    # coverage
    cov_p = sub.add_parser("coverage", help="Show coverage report")
    cov_p.add_argument("--dataset-dir", help="Dataset directory")
    cov_p.add_argument("--verbose", "-v", action="store_true")

    args = parser.parse_args()

    if args.command == "generate":
        cmd_generate(args)
    elif args.command == "setup":
        cmd_setup(args)
    elif args.command == "evaluate":
        cmd_evaluate(args)
    elif args.command == "run":
        cmd_run(args)
    elif args.command == "batch":
        cmd_batch(args)
    elif args.command == "coverage":
        cmd_coverage(args)
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
