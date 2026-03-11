"""
Universal task evaluator.

Dispatches to the appropriate evaluation method based on the task's eval_spec.
"""

import subprocess
import os
import re
import tempfile
from pathlib import Path
from ..schema import Task, EvalSpec, EvalMethod


def evaluate_task(task: Task, workdir: str) -> dict:
    """
    Evaluate task completion. Returns:
    {
        "passed": bool,
        "score": float (0.0 to 1.0),
        "details": str,
        "checks": [{"name": str, "passed": bool, "detail": str}, ...]
    }
    """
    method = task.eval_spec.method

    evaluators = {
        EvalMethod.DIFF_MATCH: _eval_diff_match,
        EvalMethod.FILE_CONTENT: _eval_file_content,
        EvalMethod.FILE_EXISTS: _eval_file_exists,
        EvalMethod.COMMAND_OUTPUT: _eval_command_output,
        EvalMethod.TEST_PASS: _eval_test_pass,
        EvalMethod.SCRIPT_CHECK: _eval_script_check,
        EvalMethod.COMPOSITE: _eval_composite,
    }

    evaluator = evaluators.get(method)
    if not evaluator:
        return {"passed": False, "score": 0.0, "details": f"Unknown eval method: {method}", "checks": []}

    result = evaluator(task.eval_spec, workdir)

    # Apply pass threshold
    threshold = task.eval_spec.pass_threshold
    result["passed"] = result["score"] >= threshold

    return result


def _eval_diff_match(spec: EvalSpec, workdir: str) -> dict:
    """Compare git diff against expected patch."""
    proc = subprocess.run(
        ["git", "diff", "--no-color"],
        capture_output=True, text=True, cwd=workdir, timeout=30
    )
    actual_diff = proc.stdout

    # Also check staged changes
    proc2 = subprocess.run(
        ["git", "diff", "--staged", "--no-color"],
        capture_output=True, text=True, cwd=workdir, timeout=30
    )
    actual_diff += proc2.stdout

    if not spec.expected_patch:
        return {"score": 0.0, "details": "No expected patch defined", "checks": []}

    # Extract modified files from both diffs
    expected_files = _extract_diff_files(spec.expected_patch)
    actual_files = _extract_diff_files(actual_diff)

    overlap = expected_files & actual_files
    if not expected_files:
        return {"score": 0.0, "details": "Expected patch has no files", "checks": []}

    score = len(overlap) / len(expected_files)
    checks = []
    for f in expected_files:
        checks.append({
            "name": f"file:{f}",
            "passed": f in actual_files,
            "detail": "modified" if f in actual_files else "not modified"
        })

    return {
        "score": score,
        "details": f"File overlap: {len(overlap)}/{len(expected_files)} ({score:.0%})",
        "checks": checks
    }


def _eval_file_content(spec: EvalSpec, workdir: str) -> dict:
    """Check that specific files contain expected content."""
    checks = []
    for filepath, expected in spec.expected_content.items():
        full_path = os.path.join(workdir, filepath)
        try:
            content = Path(full_path).read_text()
            passed = expected in content
            checks.append({
                "name": f"content:{filepath}",
                "passed": passed,
                "detail": "content found" if passed else "content not found"
            })
        except FileNotFoundError:
            checks.append({
                "name": f"content:{filepath}",
                "passed": False,
                "detail": "file not found"
            })

    if not checks:
        return {"score": 0.0, "details": "No content checks defined", "checks": []}

    score = sum(1 for c in checks if c["passed"]) / len(checks)
    return {"score": score, "details": f"{sum(1 for c in checks if c['passed'])}/{len(checks)} content checks passed", "checks": checks}


def _eval_file_exists(spec: EvalSpec, workdir: str) -> dict:
    """Check that expected files exist."""
    checks = []
    for filepath in spec.expected_files:
        full_path = os.path.join(workdir, filepath)
        exists = os.path.exists(full_path)
        checks.append({
            "name": f"exists:{filepath}",
            "passed": exists,
            "detail": "exists" if exists else "missing"
        })

    if not checks:
        return {"score": 0.0, "details": "No file existence checks", "checks": []}

    score = sum(1 for c in checks if c["passed"]) / len(checks)
    return {"score": score, "details": f"{sum(1 for c in checks if c['passed'])}/{len(checks)} files exist", "checks": checks}


def _eval_command_output(spec: EvalSpec, workdir: str) -> dict:
    """Run a command and check its output."""
    if not spec.check_command:
        return {"score": 0.0, "details": "No check command defined", "checks": []}

    # Isolate from host venv plugins (SWE eval can install broken dev packages)
    env = {**os.environ, "PYTEST_DISABLE_PLUGIN_AUTOLOAD": "1"}
    try:
        proc = subprocess.run(
            spec.check_command, shell=True,
            capture_output=True, text=True, cwd=workdir, timeout=60, env=env
        )
        output = proc.stdout + proc.stderr
    except subprocess.TimeoutExpired:
        return {"score": 0.0, "details": "Check command timed out", "checks": []}

    checks = []

    # Check exact output match
    if spec.expected_output is not None:
        passed = output.strip() == spec.expected_output.strip()
        checks.append({
            "name": "exact_output",
            "passed": passed,
            "detail": f"got: {output[:200]}" if not passed else "matched"
        })

    # Check output contains
    if spec.output_contains:
        for needle in spec.output_contains:
            passed = needle in output
            checks.append({
                "name": f"contains:{needle[:50]}",
                "passed": passed,
                "detail": "found" if passed else "not found"
            })

    # Check output not contains
    if spec.output_not_contains:
        for needle in spec.output_not_contains:
            passed = needle not in output
            checks.append({
                "name": f"not_contains:{needle[:50]}",
                "passed": passed,
                "detail": "correctly absent" if passed else "unexpectedly present"
            })

    if not checks:
        # Fall back to exit code
        passed = proc.returncode == 0
        checks.append({
            "name": "exit_code",
            "passed": passed,
            "detail": f"exit code: {proc.returncode}"
        })

    score = sum(1 for c in checks if c["passed"]) / len(checks)
    return {"score": score, "details": f"{sum(1 for c in checks if c['passed'])}/{len(checks)} output checks passed", "checks": checks}


def _eval_test_pass(spec: EvalSpec, workdir: str) -> dict:
    """Run test command and check it passes."""
    if not spec.test_command:
        return {"score": 0.0, "details": "No test command defined", "checks": []}

    try:
        proc = subprocess.run(
            spec.test_command, shell=True,
            capture_output=True, text=True, cwd=workdir, timeout=120
        )
        passed = proc.returncode == 0
        detail = "tests passed" if passed else f"tests failed (exit {proc.returncode})"
        if not passed:
            detail += f"\n{proc.stdout[-500:]}\n{proc.stderr[-500:]}"
        return {
            "score": 1.0 if passed else 0.0,
            "details": detail,
            "checks": [{"name": "test_suite", "passed": passed, "detail": detail}]
        }
    except subprocess.TimeoutExpired:
        return {"score": 0.0, "details": "Tests timed out", "checks": [{"name": "test_suite", "passed": False, "detail": "timeout"}]}


def _eval_script_check(spec: EvalSpec, workdir: str) -> dict:
    """Run a validation script."""
    script_content = spec.check_script_content
    if not script_content and spec.check_script:
        script_path = os.path.join(workdir, spec.check_script)
        try:
            script_content = Path(script_path).read_text()
        except FileNotFoundError:
            return {"score": 0.0, "details": f"Check script not found: {spec.check_script}", "checks": []}

    if not script_content:
        return {"score": 0.0, "details": "No check script defined", "checks": []}

    with tempfile.NamedTemporaryFile(mode='w', suffix='.sh', delete=False) as f:
        f.write(script_content)
        f.flush()
        os.chmod(f.name, 0o755)
        try:
            env = {**os.environ, "WORKDIR": workdir}
            proc = subprocess.run(
                ["bash", f.name],
                capture_output=True, text=True, cwd=workdir, env=env, timeout=60
            )
            passed = proc.returncode == 0
            return {
                "score": 1.0 if passed else 0.0,
                "details": proc.stdout[:2000] if passed else (proc.stdout[:2000] or proc.stderr[:2000]),
                "checks": [{"name": "script_check", "passed": passed, "detail": f"exit {proc.returncode}"}]
            }
        except subprocess.TimeoutExpired:
            return {"score": 0.0, "details": "Script timed out", "checks": []}
        finally:
            os.unlink(f.name)


def _eval_composite(spec: EvalSpec, workdir: str) -> dict:
    """Run multiple evaluations, all must pass."""
    if not spec.sub_evals:
        return {"score": 0.0, "details": "No sub-evaluations defined", "checks": []}

    all_checks = []
    scores = []

    for sub_dict in spec.sub_evals:
        sub_spec = EvalSpec(**{k: v for k, v in sub_dict.items() if k != "method"})
        sub_spec.method = EvalMethod(sub_dict.get("method", "command_output"))

        # Create a temporary task to evaluate
        sub_task = Task(eval_spec=sub_spec)
        result = evaluate_task(sub_task, workdir)
        all_checks.extend(result["checks"])
        scores.append(result["score"])

    avg_score = sum(scores) / len(scores) if scores else 0.0
    return {
        "score": avg_score,
        "details": f"Composite: {sum(1 for s in scores if s >= 1.0)}/{len(scores)} sub-evals passed",
        "checks": all_checks
    }


def _extract_diff_files(diff: str) -> set[str]:
    """Extract file paths from a unified diff."""
    files = set()
    for line in diff.split("\n"):
        m = re.match(r'^(?:diff --git a/(.*?) b/|--- a/(.*)|[+]{3} b/(.*))', line)
        if m:
            path = m.group(1) or m.group(2) or m.group(3)
            if path and path != "/dev/null":
                files.add(path)
    return files
