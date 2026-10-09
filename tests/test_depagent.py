"""Offline tests. The network is replaced by a fake registry; git tests run only if git is installed."""

import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from depagent.agent import DependencyAgent
from depagent.policy import Policy
from depagent.project import load_dependencies
from depagent.registry import Registry
from depagent.versions import classify, parse_requirement_line

PASS = f'"{sys.executable}" -c "import sys; sys.exit(0)"'
FAIL = f'"{sys.executable}" -c "import sys; sys.exit(1)"'


class FakeRegistry:
    def __init__(self, versions):
        self.versions = versions  # {(ecosystem, name): latest}

    def latest(self, ecosystem, name):
        return self.versions.get((ecosystem, name))


@pytest.fixture
def project(tmp_path):
    (tmp_path / "requirements.txt").write_text(
        "# app dependencies\n"
        "requests==2.31.0  # http client\n"
        "flask==2.0.0\n"
        "numpy>=1.20\n"
        "-r extra.txt\n"
        "click==8.1.0; python_version >= '3.8'\n",
        encoding="utf-8",
    )
    (tmp_path / "package.json").write_text(json.dumps({
        "name": "demo",
        "dependencies": {"lodash": "^4.17.20", "express": "~4.17.1", "weird": ">=1 <3"},
        "devDependencies": {"jest": "29.0.0"},
    }, indent=2), encoding="utf-8")
    return tmp_path


LATEST = {
    ("pypi", "requests"): "2.32.0",   # minor
    ("pypi", "flask"): "3.0.0",       # major
    ("pypi", "numpy"): "1.26.0",
    ("pypi", "click"): "8.1.7",       # patch
    ("npm", "lodash"): "4.17.21",     # patch
    ("npm", "express"): "5.0.0",      # major
    ("npm", "weird"): "3.0.0",
    ("npm", "jest"): "29.0.0",        # current
}


# ---------- version logic ----------
@pytest.mark.parametrize("current,latest,expected", [
    ("1.2.3", "1.2.4", "patch"),
    ("1.2.3", "1.3.0", "minor"),
    ("1.2.3", "2.0.0", "major"),
    ("2.0.0", "1.9.9", "current"),
    ("1.0", "not-a-version!", "unknown"),
])
def test_classify(current, latest, expected):
    assert classify(current, latest) == expected


def test_parse_requirement_lines():
    assert parse_requirement_line("requests==2.31.0  # note") == ("requests", "==", "2.31.0")
    assert parse_requirement_line("numpy>=1.20") == ("numpy", ">=", "1.20")
    assert parse_requirement_line("pkg[extra]==1.0") == ("pkg", "==", "1.0")
    assert parse_requirement_line("-r other.txt") is None
    assert parse_requirement_line("# just a comment") is None
    assert parse_requirement_line("") is None


# ---------- reading projects ----------
def test_load_dependencies_reads_both_files(project):
    deps = {(d.ecosystem, d.name): d for d in load_dependencies(project)}
    assert deps[("pypi", "requests")].updatable is True
    assert deps[("pypi", "numpy")].updatable is False         # range, not an exact pin
    assert deps[("npm", "lodash")].prefix == "^"
    assert deps[("npm", "weird")].current is None
    assert ("pypi", "extra") not in deps                       # -r lines are ignored


# ---------- policy ----------
def test_policy_decisions(project):
    policy = Policy(auto_levels=["patch", "minor"], exclude=["Flask"])
    deps = {d.name: d for d in load_dependencies(project)}
    assert policy.decide(deps["requests"], "minor", "2.32.0") == "auto"
    assert policy.decide(deps["click"], "patch", "8.1.7") == "auto"
    assert policy.decide(deps["flask"], "major", "3.0.0") == "skip"      # excluded (case-insensitive)
    assert policy.decide(deps["requests"], "major", "3.0.0") == "review"
    assert policy.decide(deps["requests"], "current", "2.31.0") == "current"


def test_policy_load_defaults_when_missing(tmp_path):
    policy = Policy.load(tmp_path / "dep-agent.json")
    assert policy.auto_levels == ["patch", "minor"]


# ---------- planning ----------
def test_plan_marks_each_dependency(project):
    agent = DependencyAgent(project, FakeRegistry(LATEST), Policy(exclude=["flask"]))
    decisions = {p.dep.name: p.decision for p in agent.plan()}
    assert decisions["requests"] == "auto"
    assert decisions["click"] == "auto"
    assert decisions["flask"] == "skip"          # excluded
    assert decisions["numpy"] == "skip"          # range, not updatable
    assert decisions["express"] == "review"      # major
    assert decisions["lodash"] == "auto"
    assert decisions["jest"] == "current"
    assert decisions["weird"] == "skip"


def test_render_has_summary_line(project):
    agent = DependencyAgent(project, FakeRegistry(LATEST), Policy())
    text = agent.render(agent.plan())
    assert "auto-update" in text and "need review" in text


# ---------- applying ----------
def test_dry_run_changes_nothing(project):
    before = (project / "requirements.txt").read_text()
    agent = DependencyAgent(project, FakeRegistry(LATEST), Policy(), test_command=PASS)
    result = agent.apply(agent.plan(), dry_run=True)
    assert result.status == "dry-run"
    assert (project / "requirements.txt").read_text() == before


def test_apply_updates_safe_versions_only(project):
    agent = DependencyAgent(project, FakeRegistry(LATEST), Policy(), test_command=PASS)
    result = agent.apply(agent.plan())
    assert result.status == "applied"

    req = (project / "requirements.txt").read_text()
    assert "requests==2.32.0  # http client" in req   # comment kept
    assert "click==8.1.7" in req
    assert "flask==2.0.0" in req                     # major: not applied
    assert "numpy>=1.20" in req                      # range: untouched

    pkg = json.loads((project / "package.json").read_text())
    assert pkg["dependencies"]["lodash"] == "^4.17.21"  # prefix kept
    assert pkg["dependencies"]["express"] == "~4.17.1"  # major: not applied
    assert pkg["devDependencies"]["jest"] == "29.0.0"


def test_include_review_applies_major_updates(project):
    agent = DependencyAgent(project, FakeRegistry(LATEST), Policy(exclude=["flask"]), test_command=PASS)
    agent.apply(agent.plan(), include_review=True)
    assert "express" in json.loads((project / "package.json").read_text())["dependencies"]
    pkg = json.loads((project / "package.json").read_text())
    assert pkg["dependencies"]["express"] == "~5.0.0"


def test_failed_tests_restore_original_files(project):
    originals = {f: (project / f).read_text() for f in ("requirements.txt", "package.json")}
    agent = DependencyAgent(project, FakeRegistry(LATEST), Policy(), test_command=FAIL)
    result = agent.apply(agent.plan())
    assert result.status == "reverted"
    for name, text in originals.items():
        assert (project / name).read_text() == text


def test_no_updates_message(project):
    agent = DependencyAgent(project, FakeRegistry({}), Policy(), test_command=PASS)
    assert agent.apply(agent.plan()).status == "nothing"


def test_summarizer_output_is_added(project):
    agent = DependencyAgent(project, FakeRegistry(LATEST), Policy(), test_command=PASS,
                            summarize=lambda text: "- looks safe")
    result = agent.apply(agent.plan())
    assert "- looks safe" in result.message


# ---------- registry ----------
def test_registry_uses_fetch_and_caches():
    calls = []

    def fake_fetch(url):
        calls.append(url)
        return {"info": {"version": "9.9.9"}} if "pypi" in url else {"version": "1.1.1"}

    registry = Registry(fetch=fake_fetch)
    assert registry.latest("pypi", "requests") == "9.9.9"
    assert registry.latest("pypi", "requests") == "9.9.9"
    assert registry.latest("npm", "@types/node") == "1.1.1"
    assert len(calls) == 2
    assert "%2F" in calls[1] or "@types" in calls[1]


def test_registry_returns_none_on_failure():
    def broken(url):
        raise OSError("offline")

    assert Registry(fetch=broken).latest("pypi", "requests") is None


# ---------- git (only when git is available) ----------
@pytest.mark.skipif(shutil.which("git") is None, reason="git not installed")
def test_branch_and_commit(project, monkeypatch):
    monkeypatch.setenv("GIT_AUTHOR_NAME", "test")
    monkeypatch.setenv("GIT_AUTHOR_EMAIL", "test@example.com")
    monkeypatch.setenv("GIT_COMMITTER_NAME", "test")
    monkeypatch.setenv("GIT_COMMITTER_EMAIL", "test@example.com")
    git = lambda *a: subprocess.run(["git", *a], cwd=project, capture_output=True, text=True, check=True).stdout
    git("init", "-q", "-b", "main")
    git("add", "-A")
    git("commit", "-q", "-m", "initial")

    agent = DependencyAgent(project, FakeRegistry(LATEST), Policy(), test_command=PASS)
    result = agent.apply(agent.plan(), branch="deps/test-branch", commit=True)

    assert result.status == "applied"
    assert git("rev-parse", "--abbrev-ref", "HEAD").strip() == "deps/test-branch"
    assert git("log", "--oneline").count("\n") == 2  # two commits
