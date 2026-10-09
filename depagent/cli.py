"""Command-line interface.

  python -m depagent init   [PATH]                       create dep-agent.json
  python -m depagent scan   [PATH] [--json] [--ai]       list outdated dependencies
  python -m depagent apply  [PATH] [options]             apply approved updates
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import date
from pathlib import Path

from .agent import DependencyAgent
from .ai import make_summarizer
from .policy import CONFIG_FILE, DEFAULT_TEST_COMMAND, Policy
from .registry import Registry

DEFAULT_CONFIG = {
    "auto_levels": ["patch", "minor"],
    "exclude": [],
    "test_command": DEFAULT_TEST_COMMAND,
}


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="depagent", description="Keep Python and npm dependencies up to date.")
    sub = parser.add_subparsers(dest="cmd", required=True)

    init = sub.add_parser("init", help="Create a dep-agent.json settings file")
    init.add_argument("path", nargs="?", default=".")

    scan = sub.add_parser("scan", help="Show outdated dependencies and what the agent would do")
    scan.add_argument("path", nargs="?", default=".")
    scan.add_argument("--json", action="store_true", help="Print machine-readable output")
    scan.add_argument("--ai", action="store_true", help="Add a plain-language summary (needs ANTHROPIC_API_KEY)")

    apply = sub.add_parser("apply", help="Apply approved updates and run the tests")
    apply.add_argument("path", nargs="?", default=".")
    apply.add_argument("--include-review", action="store_true", help="Also apply major updates")
    apply.add_argument("--dry-run", action="store_true", help="Show the changes without making them")
    apply.add_argument("--branch", nargs="?", const="auto", metavar="NAME",
                       help="Work on a new git branch (default name: deps/update-YYYYMMDD)")
    apply.add_argument("--commit", action="store_true", help="Commit the changes (needs git)")
    apply.add_argument("--test-cmd", help="Command that must pass before changes are kept")
    apply.add_argument("--no-tests", action="store_true", help="Do not run tests (not recommended)")
    apply.add_argument("--ai", action="store_true", help="Add a plain-language summary to the result")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    root = Path(args.path).resolve()

    if args.cmd == "init":
        target = root / CONFIG_FILE
        if target.exists():
            print(f"{target} already exists. Nothing changed.")
            return 0
        target.write_text(json.dumps(DEFAULT_CONFIG, indent=2) + "\n", encoding="utf-8")
        print(f"Created {target}")
        return 0

    try:
        policy = Policy.load(root / CONFIG_FILE)
        test_command = None if getattr(args, "no_tests", False) else (
            getattr(args, "test_cmd", None) or policy.test_command)
        summarize = make_summarizer() if getattr(args, "ai", False) else None
        agent = DependencyAgent(root, Registry(), policy, test_command=test_command, summarize=summarize)
        plan = agent.plan()
    except (OSError, ValueError, json.JSONDecodeError) as err:
        print(f"Error: {err}", file=sys.stderr)
        return 2

    if args.cmd == "scan":
        if args.json:
            print(json.dumps([{
                "name": p.dep.name, "type": p.dep.ecosystem, "file": p.dep.file,
                "current": p.dep.current, "latest": p.latest, "change": p.level, "decision": p.decision,
            } for p in plan], indent=2))
            return 0
        print(agent.render(plan))
        if args.ai:
            summarize_fn = make_summarizer()
            if summarize_fn:
                print("\nSummary:\n" + summarize_fn(agent.render(plan)))
            else:
                print("\nNo ANTHROPIC_API_KEY set, so no AI summary was made.")
        return 0

    if args.cmd == "apply":
        branch = f"deps/update-{date.today():%Y%m%d}" if args.branch == "auto" else args.branch
        result = agent.apply(plan, include_review=args.include_review, dry_run=args.dry_run,
                             branch=branch, commit=args.commit)
        print(result.message)
        return 0 if result.status in ("applied", "dry-run", "nothing") else 1

    return 0


if __name__ == "__main__":
    sys.exit(main())
