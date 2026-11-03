"""Repository hygiene: secrets and private files must never be committable."""

import re
import shutil
import subprocess

import pytest

from tests.conftest import REPO_ROOT

SECRET_PATTERNS = [
    re.compile(r"sb_(secret|publishable)_[A-Za-z0-9_-]{16,}"),
    re.compile(r"eyJ[A-Za-z0-9_-]{10,}\.eyJ[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}"),
    re.compile(r"postgres(ql)?://[^:/@\s]+:[^@\s]{3,}@"),
]

MUST_BE_IGNORED = [
    ".env",
    ".env.local",
    ".env.production",
    "chromite-backend-review.zip",
    "any/other.zip",
    "app/core/config.py.backup",
    "chromite_structure.txt",
    "supabase/.temp/project-ref",
    "supabase/.temp/start-secrets/x/env/docker.env",
    "supabase/.branches/_current_branch",
    "data/uploads/report.pdf",
    "records/audit/log.json",
    "_archive/x.txt",
    ".phase0-baseline/app/main.py",
    ".venv/pyvenv.cfg",
    "node_modules/supabase/package.json",
]

MUST_NOT_BE_IGNORED = [".env.example", "app/main.py", "supabase/migrations/x.sql",
                       "supabase/migrations-proposed/x.sql", ".githooks/pre-commit"]

SKIP_DIRS = {".git", ".venv", "venv", "node_modules", "__pycache__", ".pytest_cache",
             "data", "records", "_archive", ".phase0-baseline"}


def _in_git_repo() -> bool:
    if not shutil.which("git"):
        return False
    r = subprocess.run(["git", "rev-parse", "--is-inside-work-tree"], cwd=REPO_ROOT,
                       capture_output=True, text=True)
    return r.returncode == 0 and r.stdout.strip() == "true"


def _committable_files():
    if _in_git_repo():
        out = subprocess.run(
            ["git", "ls-files", "--cached", "--others", "--exclude-standard", "-z"],
            cwd=REPO_ROOT, capture_output=True, check=True,
        ).stdout.decode("utf-8")
        return [REPO_ROOT / p for p in out.split("\0") if p]
    files = []
    for path in REPO_ROOT.rglob("*"):
        rel = path.relative_to(REPO_ROOT)
        if any(part in SKIP_DIRS for part in rel.parts):
            continue
        if rel.parts[:2] == ("supabase", ".temp") or rel.parts[:2] == ("supabase", ".branches"):
            continue
        name = path.name
        if (name == ".env" or name.startswith(".env.") and name != ".env.example"
                or name.endswith((".zip", ".backup")) or name == "chromite_structure.txt"):
            continue
        if path.is_file():
            files.append(path)
    return files


def test_no_secret_patterns_in_committable_files():
    hits = []
    for path in _committable_files():
        if not path.is_file():
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue
        for pattern in SECRET_PATTERNS:
            if pattern.search(text):
                hits.append(f"{path.relative_to(REPO_ROOT)}: {pattern.pattern[:20]}...")
    assert not hits, "secret-looking content found:\n" + "\n".join(hits)


def test_env_example_contains_placeholders_only():
    text = (REPO_ROOT / ".env.example").read_text(encoding="utf-8")
    assert "YOUR_" in text
    assert not any(p.search(text) for p in SECRET_PATTERNS)
    assert ".supabase.co" not in text.replace("YOUR_PROJECT.supabase.co", "")


def test_gitignore_covers_private_paths():
    if not _in_git_repo():
        pytest.skip("not a Git repository yet (run tools/git/phase0-commit.ps1)")
    r = subprocess.run(["git", "check-ignore", "--no-index", "-v", *MUST_BE_IGNORED],
                       cwd=REPO_ROOT, capture_output=True, text=True)
    ignored = {line.split("\t", 1)[1] for line in r.stdout.splitlines() if "\t" in line}
    assert set(MUST_BE_IGNORED) <= ignored, set(MUST_BE_IGNORED) - ignored


def test_gitignore_does_not_hide_source():
    if not _in_git_repo():
        pytest.skip("not a Git repository yet")
    r = subprocess.run(["git", "check-ignore", "--no-index", *MUST_NOT_BE_IGNORED],
                       cwd=REPO_ROOT, capture_output=True, text=True)
    assert r.stdout.strip() == ""


def test_no_private_files_tracked():
    if not _in_git_repo():
        pytest.skip("not a Git repository yet")
    tracked = subprocess.run(["git", "ls-files"], cwd=REPO_ROOT, capture_output=True,
                             text=True, check=True).stdout.splitlines()
    bad = [t for t in tracked
           if re.search(r"(^|/)\.env($|\.)", t) and not t.endswith(".env.example")
           or t.endswith((".zip", ".backup"))
           or t.startswith(("supabase/.temp/", "data/", "records/", "_archive/", ".phase0-baseline/"))]
    assert not bad, bad


def test_pre_commit_hook_present():
    hook = REPO_ROOT / ".githooks" / "pre-commit"
    assert hook.is_file()
    assert "sb_(secret|publishable)_" in hook.read_text(encoding="utf-8")
