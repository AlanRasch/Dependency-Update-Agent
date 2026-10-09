"""Reads dependencies from a project and writes updated versions back."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path

from .versions import parse_requirement_line

REQ_FILE = "requirements.txt"
NPM_FILE = "package.json"
NPM_SECTIONS = ("dependencies", "devDependencies")
NPM_SIMPLE_VERSION = re.compile(r"^([\^~]?)(\d+\.\d+\.\d+)$")
MANAGED_FILES = (REQ_FILE, NPM_FILE)


@dataclass
class Dependency:
    name: str
    ecosystem: str                 # "pypi" or "npm"
    current: str | None            # installed/pinned version, None if unknown
    file: str                      # file the dependency is declared in
    updatable: bool                # can the agent safely rewrite this declaration?
    section: str = ""              # npm section ("dependencies" or "devDependencies")
    prefix: str = ""               # npm range prefix: "^", "~" or ""
    line_no: int = -1              # line index in requirements.txt


def load_dependencies(root: Path) -> list[Dependency]:
    deps: list[Dependency] = []

    req = root / REQ_FILE
    if req.exists():
        for index, line in enumerate(req.read_text(encoding="utf-8").splitlines()):
            parsed = parse_requirement_line(line)
            if not parsed:
                continue
            name, op, version = parsed
            deps.append(Dependency(
                name=name, ecosystem="pypi", current=version, file=REQ_FILE,
                updatable=(op == "==" and bool(version)), line_no=index,
            ))

    pkg = root / NPM_FILE
    if pkg.exists():
        data = json.loads(pkg.read_text(encoding="utf-8"))
        for section in NPM_SECTIONS:
            for name, spec in (data.get(section) or {}).items():
                match = NPM_SIMPLE_VERSION.match(str(spec).strip())
                if match:
                    prefix, version = match.groups()
                    deps.append(Dependency(name, "npm", version, NPM_FILE, True, section, prefix))
                else:
                    # ranges such as ">=1 <3", git URLs or tags: shown in reports but not rewritten
                    deps.append(Dependency(name, "npm", None, NPM_FILE, False, section))
    return deps


def snapshot(root: Path) -> dict[str, str]:
    """Current text of every managed file that exists, used to restore after a failed test run."""
    return {f: (root / f).read_text(encoding="utf-8") for f in MANAGED_FILES if (root / f).exists()}


def restore(root: Path, saved: dict[str, str]) -> None:
    for name, text in saved.items():
        (root / name).write_text(text, encoding="utf-8")


def write_updates(root: Path, changes: list[tuple[Dependency, str]]) -> None:
    """Rewrite declarations. Only exact pins (==) and simple npm versions are touched."""
    pypi = [(d, new) for d, new in changes if d.ecosystem == "pypi"]
    if pypi:
        path = root / REQ_FILE
        lines = path.read_text(encoding="utf-8").splitlines(keepends=True)
        for dep, new in pypi:
            lines[dep.line_no] = lines[dep.line_no].replace(f"=={dep.current}", f"=={new}", 1)
        path.write_text("".join(lines), encoding="utf-8")

    npm = [(d, new) for d, new in changes if d.ecosystem == "npm"]
    if npm:
        path = root / NPM_FILE
        data = json.loads(path.read_text(encoding="utf-8"))
        for dep, new in npm:
            data[dep.section][dep.name] = f"{dep.prefix}{new}"
        path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
