# Dependency Update Agent

A small, safe agent that keeps the libraries in your project up to date.

It reads your **Python** (`requirements.txt`) and **npm** (`package.json`) dependencies, finds newer versions on PyPI and npm, and sorts every update by risk:

- **Patch and minor updates** are applied automatically, but only if your tests pass.
- **Major updates** are listed for a person to review. They are never applied unless you ask.
- **Excluded packages** are never touched.

If the tests fail, every file is restored to exactly what it was before. Nothing is left half-updated.

The agent can also work on a new git branch, commit the changes, and open a pull request from a scheduled GitHub Action.

---

## Contents

1. [Why use it](#why-use-it)
2. [Requirements](#requirements)
3. [Installation](#installation)
4. [Quick start](#quick-start)
5. [Commands](#commands)
6. [Settings: dep-agent.json](#settings-dep-agentjson)
7. [How decisions are made](#how-decisions-are-made)
8. [Running on a schedule with GitHub Actions](#running-on-a-schedule-with-github-actions)
9. [Using it in other CI systems](#using-it-in-other-ci-systems)
10. [AI summaries (optional)](#ai-summaries-optional)
11. [Project structure](#project-structure)
12. [Running the tests](#running-the-tests)
13. [Limits and safety notes](#limits-and-safety-notes)
14. [Troubleshooting](#troubleshooting)
15. [Extending the agent](#extending-the-agent)

---

## Why use it

Keeping dependencies current is important for security fixes and bug fixes, but it is tedious and easy to postpone. This agent does the routine part for you:

| Task | Without the agent | With the agent |
|---|---|---|
| Find outdated packages | Run several commands, compare versions by hand | One `scan` command |
| Decide what is safe | Read each changelog | Patch and minor updates are applied after tests; majors are flagged |
| Verify the update | Run the tests yourself | Tests run automatically; failures roll everything back |
| Share the change | Write the pull request by hand | Branch, commit and pull request created for you |

---

## Requirements

- **Python 3.10 or newer**
- **git** (only if you want branches, commits and pull requests)
- Internet access to `pypi.org` and `registry.npmjs.org` (to look up the latest versions)
- Optional: an Anthropic API key, for plain-language summaries

---

## Installation

Copy the `depagent` folder into your project, or install the package:

```bash
# Option A: copy the folder into your project (for example tools/depagent)
# Option B: install it from the project folder
pip install -e .
```

Install the single required library:

```bash
pip install -r requirements.txt       # packaging, plus pytest and anthropic if you want them
```

---

## Quick start

Run these commands from your project folder (or pass the folder path).

```bash
# 1. Create the settings file (you can edit it later)
python -m depagent init

# 2. See what is outdated and what the agent would do. Nothing is changed.
python -m depagent scan

# 3. Preview the changes the agent would make
python -m depagent apply --dry-run

# 4. Apply the safe updates and run the tests
python -m depagent apply

# 5. Also apply major updates (only after you have reviewed them)
python -m depagent apply --include-review
```

Example output of `scan`:

```
Package                     Type  Current    Latest     Change   Decision
requests                    pypi  2.0.0      2.34.2     minor    auto-update
flask                       pypi  2.0.0      3.1.0      major    needs review
numpy                       pypi  -          1.26.4     -        skipped
lodash                      npm   4.17.20    4.17.21    patch    auto-update

2 auto-update, 1 need review, 1 skipped, 0 up to date, 0 unknown
```

---

## Commands

| Command | What it does |
|---|---|
| `init [PATH]` | Creates `dep-agent.json` with safe defaults. Does nothing if the file exists. |
| `scan [PATH]` | Lists dependencies, the latest version of each, and the decision for each. |
| `scan [PATH] --json` | Same information as JSON, for other tools. |
| `scan [PATH] --ai` | Adds a plain-language summary (needs `ANTHROPIC_API_KEY`). |
| `apply [PATH]` | Applies the auto-update decisions, then runs the tests. Reverts on failure. |
| `apply [PATH] --dry-run` | Shows what would change. Changes nothing. |
| `apply [PATH] --include-review` | Also applies major updates. |
| `apply [PATH] --branch [NAME]` | Works on a new git branch. Without a name, uses `deps/update-YYYYMMDD`. |
| `apply [PATH] --commit` | Commits the updated files (use with `--branch`). |
| `apply [PATH] --test-cmd "CMD"` | Uses a different test command for this run. |
| `apply [PATH] --no-tests` | Skips the tests. Not recommended. |
| `apply [PATH] --ai` | Adds a plain-language summary to the result. |

Exit codes: `0` success or nothing to do, `1` the update was reverted or failed, `2` a configuration or file error.

---

## Settings: dep-agent.json

`init` creates this file in your project folder:

```json
{
  "auto_levels": ["patch", "minor"],
  "exclude": [],
  "test_command": "python -m pytest -q"
}
```

| Setting | Meaning |
|---|---|
| `auto_levels` | Which kinds of update are applied automatically. Usually `["patch", "minor"]`. Add `"major"` only if you trust your tests fully. |
| `exclude` | Package names the agent must never change, for example `["django"]`. Names are not case-sensitive. |
| `test_command` | The command that must pass before updates are kept. For a Python project that installs the new versions first, use `"pip install -q -r requirements.txt && python -m pytest -q"`. For npm, use `"npm install && npm test"`. |

---

## How decisions are made

Each dependency gets one decision:

| Decision | Meaning | Applied by default? |
|---|---|---|
| `auto-update` | Newer patch or minor version, and the package is allowed | Yes, after tests pass |
| `needs review` | Newer major version | No. Use `--include-review`. |
| `skipped` | Excluded, has a range such as `>=1.20` or `>1 <3`, or the current version is unknown | Never. Update these by hand. |
| `up to date` | Already on the latest version | Nothing to do |
| `latest unknown` | The registry could not be reached | Nothing to do |

The agent only rewrites **exact pins** in `requirements.txt` (for example `requests==2.31.0`) and **simple versions** in `package.json` (for example `"^4.17.20"` or `"~4.17.1"`). The `^` or `~` prefix is kept. Ranges are reported but not rewritten, so the agent never changes what your project is allowed to install unless you pin it.

---

## Running on a schedule with GitHub Actions

The repository includes `.github/workflows/dependency-updates.yml`. It runs every Monday and:

1. Installs Python.
2. Applies the safe updates on a new branch and commits them.
3. Installs the new versions and runs the tests. If they fail, nothing is committed and no pull request is opened.
4. Pushes the branch and opens a pull request.

To use it:

1. Copy the `depagent` folder to `tools/depagent` in your repository.
2. Copy `.github/workflows/dependency-updates.yml` into your repository.
3. Adjust the `test-cmd` in the workflow if your project uses something other than pytest or npm.
4. In GitHub, go to *Settings > Actions > General* and allow workflows to create pull requests if that option is off.
5. Run the workflow once by hand from the *Actions* tab (`workflow_dispatch`) to test it.

Major updates are never included. Review them with `scan` and apply them by hand or with `--include-review` in a separate, deliberate step.

---

## Using it in other CI systems

The agent is a normal command-line tool, so it works in any CI system (GitLab CI, Jenkins, Azure Pipelines, and others). Run:

```bash
python -m depagent apply . --branch --commit --test-cmd "pip install -q -r requirements.txt && python -m pytest -q"
```

Then push the branch and open a merge request with your system's own tools.

---

## AI summaries (optional)

Add an Anthropic API key to get a short, plain-language summary of each update run, written for the pull request description:

```bash
export ANTHROPIC_API_KEY=your-key          # Windows PowerShell: $env:ANTHROPIC_API_KEY="your-key"
python -m depagent scan --ai
python -m depagent apply --ai
```

Without a key, everything works the same, but the summary is not added. Set `DEP_MODEL` to choose a different Claude model.

The summary is based on the list of updated packages and the test output. It does not send your source code.

---

## Project structure

```
dependency-update-agent/
├── depagent/
│   ├── __init__.py       version
│   ├── __main__.py       allows: python -m depagent
│   ├── agent.py          plans updates, applies them, runs tests, restores on failure, git branch and commit
│   ├── ai.py             optional plain-language summaries
│   ├── cli.py            command-line interface
│   ├── policy.py         decides what is safe, reads dep-agent.json
│   ├── project.py        reads requirements.txt and package.json, writes updates back
│   ├── registry.py       looks up the latest versions on PyPI and npm
│   └── versions.py       version comparison and requirement parsing
├── .github/workflows/
│   └── dependency-updates.yml   weekly job that opens pull requests
├── tests/
│   └── test_depagent.py  20 offline tests
├── dep-agent.json        example settings
├── pyproject.toml
├── requirements.txt
├── .gitignore
└── README.md
```

---

## Running the tests

```bash
pip install -r requirements.txt
python -m pytest -q
```

The tests do not use the internet. The registry is replaced by a fake, so the tests are fast and repeatable. The git test runs only if git is installed.

---

## Limits and safety notes

- **Tests are the safety net.** The agent is only as safe as your test suite. A project with no tests should use `--dry-run` and review the changes by hand.
- **Only exact pins and simple npm versions are rewritten.** Other formats (such as `>=`, extras that change the meaning, git URLs, or lock files) need a person.
- **Lock files are not updated.** After an update, run your package manager's install command so that `package-lock.json`, `poetry.lock` or similar files stay in step. The workflow's test command does this for Python and npm.
- **Transitive dependencies are not managed.** Only the packages you declare are checked.
- **The agent never deletes files** and never changes anything outside `requirements.txt` and `package.json`.
- **Reverting is automatic only for the managed files.** If your test command changes other files, review them before committing.

---

## Troubleshooting

| Problem | What to try |
|---|---|
| `latest unknown` for every package | Check your internet connection. The agent needs `pypi.org` and `registry.npmjs.org`. |
| `--branch needs the project to be a git repository` | Run `git init` and commit once, or leave out `--branch`. |
| `There are uncommitted changes` | Commit or stash your work first. The agent refuses to mix its changes with yours. |
| `Tests failed, so no changes were kept` | Read the test output shown below the message. Fix the test or wait for the package to be compatible, then run again. |
| `Could not create branch` | The branch name already exists. Use `--branch NEWNAME`. |
| `pytest` not found during tests | Add `pytest` to your environment, or set `--test-cmd` to your project's real test command. |
| Scheduled workflow opened no pull request | Check the *Actions* log. No pull request is opened when there are no updates or when tests fail. |
| Lock file is out of date after an update | Run your package manager's install command and commit the lock file. |

---

## Extending the agent

- **Another ecosystem** (for example Maven or Cargo): add a loader in `project.py`, a registry lookup in `registry.py`, and extend `versions.py` if the version format is different.
- **Stricter rules**: change `Policy.decide` in `policy.py`, for example to skip a package when its newest release is less than a week old.
- **Other notification channels**: add a function in `cli.py` that posts the `apply` result to chat or email.

---

**Author:** Dr. Firend Alan Rasch, American University of Phnom Penh
**License:** MIT (or your preferred license)
