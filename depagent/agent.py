"""The dependency agent: plans updates, applies the approved ones, and keeps the project green."""

from __future__ import annotations

import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

from .policy import Policy
from .project import MANAGED_FILES, Dependency, load_dependencies, restore, snapshot, write_updates
from .versions import classify

DECISION_LABELS = {
    "auto": "auto-update",
    "review": "needs review",
    "skip": "skipped",
    "unknown": "latest unknown",
    "current": "up to date",
}


@dataclass
class PlannedUpdate:
    dep: Dependency
    latest: str | None
    level: str
    decision: str


@dataclass
class ApplyResult:
    status: str                 # "dry-run", "nothing", "applied", "reverted" or "error"
    message: str
    changed_files: list[str] = field(default_factory=list)


class DependencyAgent:
    def __init__(self, root: Path, registry, policy: Policy, test_command: str | None = None,
                 summarize: Callable[[str], str] | None = None):
        self.root = Path(root).resolve()
        self.registry = registry
        self.policy = policy
        self.test_command = test_command
        self.summarize = summarize

    # ----- planning -----
    def plan(self) -> list[PlannedUpdate]:
        planned = []
        for dep in load_dependencies(self.root):
            latest = self.registry.latest(dep.ecosystem, dep.name)
            level = classify(dep.current, latest) if dep.current and latest else "unknown"
            decision = self.policy.decide(dep, level, latest)
            planned.append(PlannedUpdate(dep, latest, level, decision))
        return planned

    def render(self, plan: list[PlannedUpdate]) -> str:
        if not plan:
            return "No dependencies found (looked for requirements.txt and package.json)."
        rows = [f"{'Package':<28}{'Type':<6}{'Current':<11}{'Latest':<11}{'Change':<9}Decision"]
        for p in plan:
            change = "" if p.level in ("current", "unknown") else p.level
            rows.append(
                f"{p.dep.name:<28}{p.dep.ecosystem:<6}{(p.dep.current or '-'):<11}"
                f"{(p.latest or '-'):<11}{change:<9}{DECISION_LABELS[p.decision]}"
            )
        counts = {k: sum(1 for p in plan if p.decision == k) for k in DECISION_LABELS}
        summary = (f"\n{counts['auto']} auto-update, {counts['review']} need review, "
                   f"{counts['skip']} skipped, {counts['current']} up to date, {counts['unknown']} unknown")
        return "\n".join(rows) + summary

    # ----- applying -----
    def apply(self, plan: list[PlannedUpdate], include_review: bool = False, dry_run: bool = False,
              branch: str | None = None, commit: bool = False) -> ApplyResult:
        wanted = {"auto", "review"} if include_review else {"auto"}
        chosen = [p for p in plan if p.decision in wanted and p.latest]
        if not chosen:
            return ApplyResult("nothing", "No updates to apply.")

        lines = [f"{p.dep.name}: {p.dep.current} -> {p.latest} ({p.level}, {p.dep.file})" for p in chosen]
        if dry_run:
            return ApplyResult("dry-run", "Would update:\n  " + "\n  ".join(lines))

        is_git = self._git("rev-parse", "--is-inside-work-tree")[0] == 0
        previous_branch = None
        if branch:
            if not is_git:
                return ApplyResult("error", "--branch needs the project to be a git repository.")
            if self._git("status", "--porcelain")[1]:
                return ApplyResult("error", "There are uncommitted changes. Commit or stash them first.")
            previous_branch = self._git("rev-parse", "--abbrev-ref", "HEAD")[1]
            if self._git("checkout", "-b", branch)[0] != 0:
                return ApplyResult("error", f"Could not create branch '{branch}' (does it already exist?).")

        saved = snapshot(self.root)
        write_updates(self.root, [(p.dep, p.latest) for p in chosen])

        ok, output = self._run_tests()
        if not ok:
            restore(self.root, saved)
            if branch:
                self._git("checkout", previous_branch)
                self._git("branch", "-D", branch)
            return ApplyResult("reverted", "Tests failed, so no changes were kept.\n\n" + output[-1500:])

        changed = [f for f in MANAGED_FILES if f in saved and (self.root / f).read_text(encoding="utf-8") != saved[f]]
        message = f"Updated {len(chosen)} dependenc{'y' if len(chosen) == 1 else 'ies'}:\n  " + "\n  ".join(lines)
        if self.test_command:
            message += "\nTests passed."
        else:
            message += "\nNo test command configured, so tests were not run."

        if commit and is_git and changed:
            self._git("add", *changed)
            title = f"Update {len(chosen)} dependenc{'y' if len(chosen) == 1 else 'ies'}"
            rc, out = self._git("commit", "-m", title, "-m", "\n".join(lines))
            message += "\nCommitted." if rc == 0 else f"\nCommit failed: {out}"
        if self.summarize:
            message += "\n\nSummary:\n" + self.summarize("\n".join(lines) + "\n\n" + output[-2000:])
        return ApplyResult("applied", message, changed)

    # ----- helpers -----
    def _run_tests(self) -> tuple[bool, str]:
        if not self.test_command:
            return True, ""
        command = self.test_command
        if command.startswith("python "):  # use the same Python that runs the agent
            command = f'"{sys.executable}" ' + command[len("python "):]
        try:
            proc = subprocess.run(command, shell=True, cwd=self.root, capture_output=True, text=True, timeout=900)
        except (OSError, subprocess.TimeoutExpired) as err:
            return False, str(err)
        return proc.returncode == 0, proc.stdout + proc.stderr

    def _git(self, *args: str) -> tuple[int, str]:
        try:
            proc = subprocess.run(["git", *args], cwd=self.root, capture_output=True, text=True)
        except OSError:
            return 1, "git is not installed"
        return proc.returncode, (proc.stdout + proc.stderr).strip()
