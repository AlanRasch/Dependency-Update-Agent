"""Version comparison and requirement-line parsing."""

from __future__ import annotations

import re

from packaging.version import InvalidVersion, Version

# name, optional [extras], operator, version. Example: "requests[socks]==2.31.0  # note"
_REQ_RE = re.compile(
    r"^\s*([A-Za-z0-9][A-Za-z0-9._-]*)"   # package name
    r"(?:\[[^\]]*\])?"                    # optional extras, ignored
    r"\s*(==|~=|>=|<=|!=|>|<)?\s*"        # optional operator
    r"([A-Za-z0-9.*+!_-]+)?"              # optional version
)


def classify(current: str, latest: str) -> str:
    """Return 'major', 'minor', 'patch', 'current' or 'unknown' for an update from current to latest."""
    try:
        cur, new = Version(current), Version(latest)
    except (InvalidVersion, TypeError):
        return "unknown"
    if new <= cur:
        return "current"
    if new.major != cur.major:
        return "major"
    if new.minor != cur.minor:
        return "minor"
    return "patch"


def parse_requirement_line(line: str) -> tuple[str, str | None, str | None] | None:
    """Return (name, operator, version) for a requirements.txt line, or None for comments and options."""
    content = line.split("#", 1)[0].strip()
    if not content or content.startswith("-"):
        return None  # blank, comment, or pip option such as -r other.txt
    match = _REQ_RE.match(content)
    if not match:
        return None
    name, op, version = match.groups()
    return name, op, version
