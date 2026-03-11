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
from tasks.evaluators.evaluate import evaluate_task
from tasks.coverage import CoverageTracker


GENERATORS = {
    "local_ops": LocalOpsGenerator(),
    "env_debug": EnvDebugGenerator(),
    "data_analysis": DataAnalysisGenerator(),
    "multi_step": MultiStepGenerator(),
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
        "--timeout", str(args.timeout),
    ]

    start = time.time()
    proc = subprocess.run(cmd, capture_output=True, text=True, timeout=args.timeout + 60)
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
    elif args.command == "coverage":
        cmd_coverage(args)
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
