"""
Capability coverage tracker.

Tracks which capabilities and capability combinations are covered by existing
tasks, identifies gaps, and suggests what to generate next.
"""

import json
from collections import Counter, defaultdict
from pathlib import Path
from itertools import combinations
from .schema import Task, TaskCategory, Capability


class CoverageTracker:
    """Tracks capability coverage across all generated tasks."""

    def __init__(self, dataset_dir: str = None):
        self.tasks: list[Task] = []
        if dataset_dir:
            self.load_dataset(dataset_dir)

    def load_dataset(self, dataset_dir: str):
        """Load all task JSON files from a directory."""
        p = Path(dataset_dir)
        for f in sorted(p.glob("*.json")):
            try:
                task = Task.from_json(f.read_text())
                self.tasks.append(task)
            except Exception as e:
                print(f"Warning: skipping {f.name}: {e}")

    def add_task(self, task: Task):
        self.tasks.append(task)

    # --- Coverage metrics ---

    def category_counts(self) -> dict[str, int]:
        """Count tasks per category."""
        counts = Counter(t.category.value for t in self.tasks)
        # Include zeros for categories with no tasks
        for cat in TaskCategory:
            if cat.value not in counts:
                counts[cat.value] = 0
        return dict(sorted(counts.items()))

    def capability_counts(self) -> dict[str, int]:
        """Count how many tasks exercise each capability."""
        counts = Counter()
        for t in self.tasks:
            for cap in t.capabilities:
                counts[cap.value] += 1
        # Include zeros
        for cap in Capability:
            if cap.value not in counts:
                counts[cap.value] = 0
        return dict(sorted(counts.items()))

    def capability_pair_counts(self) -> dict[str, int]:
        """Count how many tasks exercise each pair of capabilities."""
        counts = Counter()
        for t in self.tasks:
            caps = sorted(set(c.value for c in t.capabilities))
            for pair in combinations(caps, 2):
                counts[f"{pair[0]}+{pair[1]}"] += 1
        return dict(counts.most_common())

    def difficulty_distribution(self) -> dict[str, int]:
        """Distribution of task difficulty levels."""
        return dict(Counter(t.difficulty for t in self.tasks))

    def eval_method_distribution(self) -> dict[str, int]:
        """Distribution of evaluation methods used."""
        return dict(Counter(t.eval_spec.method.value for t in self.tasks))

    # --- Gap analysis ---

    def uncovered_categories(self) -> list[str]:
        """Categories with zero tasks."""
        cc = self.category_counts()
        return [cat for cat, count in cc.items() if count == 0]

    def uncovered_capabilities(self) -> list[str]:
        """Capabilities with zero tasks."""
        cc = self.capability_counts()
        return [cap for cap, count in cc.items() if count == 0]

    def weakest_categories(self, n: int = 3) -> list[tuple[str, int]]:
        """N categories with fewest tasks."""
        cc = self.category_counts()
        return sorted(cc.items(), key=lambda x: x[1])[:n]

    def weakest_capabilities(self, n: int = 5) -> list[tuple[str, int]]:
        """N capabilities with fewest tasks."""
        cc = self.capability_counts()
        return sorted(cc.items(), key=lambda x: x[1])[:n]

    def suggest_next_tasks(self, n: int = 5) -> list[dict]:
        """Suggest what kinds of tasks to generate next to fill gaps."""
        suggestions = []

        # Priority 1: uncovered categories
        for cat in self.uncovered_categories():
            suggestions.append({
                "priority": "high",
                "reason": f"Category '{cat}' has zero tasks",
                "suggestion": f"Generate tasks for category: {cat}",
                "target_category": cat
            })

        # Priority 2: uncovered capabilities
        for cap in self.uncovered_capabilities():
            suggestions.append({
                "priority": "medium",
                "reason": f"Capability '{cap}' is never exercised",
                "suggestion": f"Generate tasks exercising: {cap}",
                "target_capability": cap
            })

        # Priority 3: weakest capability pairs
        cap_counts = self.capability_counts()
        weakest = self.weakest_capabilities(n=10)
        for cap, count in weakest:
            if count > 0 and count < 3:
                suggestions.append({
                    "priority": "low",
                    "reason": f"Capability '{cap}' only has {count} task(s)",
                    "suggestion": f"Add more tasks exercising: {cap}",
                    "target_capability": cap
                })

        return suggestions[:n]

    # --- Reporting ---

    def summary(self) -> str:
        """Human-readable coverage summary."""
        lines = []
        lines.append(f"=== Coverage Report ({len(self.tasks)} tasks) ===\n")

        lines.append("Category Distribution:")
        for cat, count in sorted(self.category_counts().items()):
            bar = "#" * count
            lines.append(f"  {cat:25s} {count:3d} {bar}")

        lines.append(f"\nCapability Coverage ({len(self.uncovered_capabilities())} uncovered):")
        for cap, count in sorted(self.capability_counts().items(), key=lambda x: x[1]):
            marker = " !!!" if count == 0 else ""
            lines.append(f"  {cap:25s} {count:3d}{marker}")

        lines.append(f"\nDifficulty: {self.difficulty_distribution()}")
        lines.append(f"Eval Methods: {self.eval_method_distribution()}")

        suggestions = self.suggest_next_tasks()
        if suggestions:
            lines.append(f"\nTop Suggestions:")
            for s in suggestions:
                lines.append(f"  [{s['priority']}] {s['suggestion']}")

        return "\n".join(lines)
