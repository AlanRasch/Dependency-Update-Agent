"""Decides what the agent may do with each update, based on dep-agent.json."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from pathlib import Path

from .project import Dependency

CONFIG_FILE = "dep-agent.json"
DEFAULT_TEST_COMMAND = "python -m pytest -q"


def normalize(name: str) -> str:
    return re.sub(r"[-_.]+", "-", name).lower()


@dataclass
class Policy:
    auto_levels: list[str] = field(default_factory=lambda: ["patch", "minor"])
    exclude: list[str] = field(default_factory=list)
    test_command: str = DEFAULT_TEST_COMMAND

    @classmethod
    def load(cls, path: Path) -> "Policy":
        if not path.exists():
            return cls()
        data = json.loads(path.read_text(encoding="utf-8"))
        return cls(
            auto_levels=list(data.get("auto_levels", ["patch", "minor"])),
            exclude=list(data.get("exclude", [])),
            test_command=data.get("test_command", DEFAULT_TEST_COMMAND),
        )

    def decide(self, dep: Dependency, level: str, latest: str | None) -> str:
        """Return one of:
        auto     - safe to apply without a human (e.g. patch or minor)
        review   - a newer version exists but needs a person (e.g. major)
        skip     - excluded, unknown current version, or not safely rewritable
        unknown  - could not look up the latest version
        current  - already up to date
        """
        if normalize(dep.name) in {normalize(e) for e in self.exclude}:
            return "skip"
        if dep.current is None:
            return "skip"
        if latest is None:
            return "unknown"
        if level in ("current", "unknown"):
            return "current"
        if not dep.updatable:
            return "skip"
        return "auto" if level in self.auto_levels else "review"
