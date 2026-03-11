"""
Base class for task generators.

Each generator produces tasks of a specific category by creating
complete executable worlds with environment setup, goals, and evaluators.
"""

import json
import os
from abc import ABC, abstractmethod
from pathlib import Path
from ..schema import Task, TaskCategory


class TaskGenerator(ABC):
    """Base class for task generators."""

    @property
    @abstractmethod
    def category(self) -> TaskCategory:
        """Which category this generator produces."""
        ...

    @abstractmethod
    def generate(self, count: int = 5, difficulty: str = "medium") -> list[Task]:
        """Generate a batch of tasks."""
        ...

    def save_tasks(self, tasks: list[Task], output_dir: str):
        """Save tasks to JSON files in the output directory."""
        os.makedirs(output_dir, exist_ok=True)
        for task in tasks:
            path = os.path.join(output_dir, f"{task.task_id}.json")
            Path(path).write_text(task.to_json())
            print(f"  Saved: {path}")

    def validate_task(self, task: Task) -> list[str]:
        """Validate a task has all required fields. Returns list of issues."""
        issues = []
        if not task.task_id:
            issues.append("Missing task_id")
        if not task.goal:
            issues.append("Missing goal")
        if not task.ground_truth:
            issues.append("Missing ground_truth")
        if not task.capabilities:
            issues.append("No capabilities tagged")
        if task.eval_spec.method.value == "command_output" and not task.eval_spec.check_command:
            issues.append("COMMAND_OUTPUT eval but no check_command")
        if task.eval_spec.method.value == "file_content" and not task.eval_spec.expected_content:
            issues.append("FILE_CONTENT eval but no expected_content")
        if task.eval_spec.method.value == "file_exists" and not task.eval_spec.expected_files:
            issues.append("FILE_EXISTS eval but no expected_files")
        return issues
