"""Phase 1 proofs: target ingestion (src/foundry/target/repo.py) --
building a TargetRepo from uploaded file content or a GitHub URL. No LLM
involved. `from_github_url`'s actual `git clone` is never invoked for real
in this suite (matches this project's "no external network calls in
tests" discipline, same as Galileo's) -- the clone-success/failure paths
are proven with a monkeypatched `subprocess.run`, and URL rejection is
proven by asserting `subprocess.run` is never even called for bad input.
"""
from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from foundry.target.repo import (
    TargetIngestionError,
    from_github_url,
    from_upload,
)

# ---------------------------------------------------------------------------
# from_upload
# ---------------------------------------------------------------------------


def test_from_upload_writes_files_and_detects_languages():
    repo = from_upload(
        {
            "app.py": b"def handler():\n    return 1\n",
            "src/app.js": b"function handler() { return 1; }\n",
        }
    )
    normalized = {f.normalized_path for f in repo.files}
    assert normalized == {"app.py", "src/app.js"}
    by_path = {f.normalized_path: f for f in repo.files}
    assert by_path["app.py"].language == "python"
    assert by_path["src/app.js"].language == "javascript"
    assert (repo.root / "app.py").read_bytes() == b"def handler():\n    return 1\n"


def test_from_upload_empty_dict_raises():
    with pytest.raises(TargetIngestionError, match="No files uploaded"):
        from_upload({})


def test_from_upload_rejects_path_traversal_filename():
    with pytest.raises(TargetIngestionError, match="outside"):
        from_upload({"../../etc/passwd": b"malicious"})


def test_from_upload_unsupported_extension_tracked_not_dropped():
    repo = from_upload({"README.md": b"# hello", "app.py": b"def f(): pass"})
    assert len(repo.unsupported_files) == 1
    assert repo.unsupported_files[0].normalized_path == "README.md"
    assert repo.languages == {"python"}


def test_from_upload_enforces_max_files():
    files = {f"file_{i}.py": b"pass" for i in range(5)}
    with pytest.raises(TargetIngestionError, match="more than 3 files"):
        from_upload(files, max_files=3)


def test_from_upload_enforces_max_total_bytes():
    files = {"big.py": b"x" * 1000}
    with pytest.raises(TargetIngestionError, match="exceeds"):
        from_upload(files, max_total_bytes=100)


def test_from_upload_cleans_up_scratch_dir_on_rejection():
    scratch_dirs_before = set(Path(tempfile_gettempdir()).glob("foundry-upload-*"))
    with pytest.raises(TargetIngestionError):
        from_upload({f"file_{i}.py": b"pass" for i in range(5)}, max_files=3)
    scratch_dirs_after = set(Path(tempfile_gettempdir()).glob("foundry-upload-*"))
    assert scratch_dirs_after == scratch_dirs_before  # nothing new left behind


def tempfile_gettempdir() -> str:
    import tempfile

    return tempfile.gettempdir()


# ---------------------------------------------------------------------------
# from_github_url: URL validation (no subprocess call at all for bad input)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "bad_url",
    [
        "not-a-url",
        "http://github.com/owner/repo",  # not https
        "https://gitlab.com/owner/repo",  # not github.com
        "https://github.com/owner/repo; rm -rf /",  # shell metacharacters
        "https://github.com/owner/repo && curl evil.com",
        "https://github.com/",  # no owner/repo
        "",
    ],
)
def test_from_github_url_rejects_invalid_urls_without_ever_calling_subprocess(monkeypatch, bad_url):
    def _fail_if_called(*args, **kwargs):
        raise AssertionError("subprocess.run must not be called for a rejected URL")

    monkeypatch.setattr(subprocess, "run", _fail_if_called)
    with pytest.raises(TargetIngestionError):
        from_github_url(bad_url)


def test_from_github_url_accepts_dot_git_suffix_and_trailing_slash(monkeypatch):
    calls = []

    def _fake_run(cmd, **kwargs):
        calls.append(cmd)
        Path(cmd[-1]).mkdir(parents=True, exist_ok=True)
        return subprocess.CompletedProcess(cmd, 0, stdout="", stderr="")

    monkeypatch.setattr(subprocess, "run", _fake_run)
    from_github_url("https://github.com/octocat/Hello-World.git/")
    assert calls[0] == ["git", "clone", "--quiet", "--depth", "1", "https://github.com/octocat/Hello-World.git", calls[0][-1]]


# ---------------------------------------------------------------------------
# from_github_url: clone success/failure, mocked subprocess.run
# ---------------------------------------------------------------------------


def test_from_github_url_clone_success_walks_the_result(monkeypatch):
    def _fake_run(cmd, **kwargs):
        dest = Path(cmd[-1])
        dest.mkdir(parents=True, exist_ok=True)
        (dest / "main.go").write_text("package main\nfunc main() {}\n")
        return subprocess.CompletedProcess(cmd, 0, stdout="", stderr="")

    monkeypatch.setattr(subprocess, "run", _fake_run)
    repo = from_github_url("https://github.com/some-owner/some-repo")
    assert {f.normalized_path for f in repo.files} == {"main.go"}
    assert repo.languages == {"go"}


def test_from_github_url_clone_failure_raises_with_stderr(monkeypatch):
    def _fake_run(cmd, **kwargs):
        return subprocess.CompletedProcess(cmd, 128, stdout="", stderr="fatal: repository not found")

    monkeypatch.setattr(subprocess, "run", _fake_run)
    with pytest.raises(TargetIngestionError, match="repository not found"):
        from_github_url("https://github.com/nonexistent/nonexistent")


def test_from_github_url_clone_timeout_raises(monkeypatch):
    def _fake_run(cmd, **kwargs):
        raise subprocess.TimeoutExpired(cmd, kwargs.get("timeout", 0))

    monkeypatch.setattr(subprocess, "run", _fake_run)
    with pytest.raises(TargetIngestionError, match="timed out"):
        from_github_url("https://github.com/some-owner/some-repo")


def test_from_github_url_command_never_uses_raw_input_string(monkeypatch):
    """The URL actually passed to git clone is rebuilt from the validated
    owner/repo regex groups, not the caller's raw string -- proven here by
    passing extra (harmless, regex-matching) whitespace/casing quirks and
    confirming the exact clone URL used."""
    calls = []

    def _fake_run(cmd, **kwargs):
        calls.append(cmd)
        Path(cmd[-1]).mkdir(parents=True, exist_ok=True)
        return subprocess.CompletedProcess(cmd, 0, stdout="", stderr="")

    monkeypatch.setattr(subprocess, "run", _fake_run)
    from_github_url("  https://github.com/octocat/Hello-World  ")
    assert calls[0][5] == "https://github.com/octocat/Hello-World.git"


def test_from_github_url_skips_dependency_directories(monkeypatch):
    def _fake_run(cmd, **kwargs):
        dest = Path(cmd[-1])
        (dest / "node_modules" / "some-package").mkdir(parents=True, exist_ok=True)
        (dest / "node_modules" / "some-package" / "index.js").write_text("function f() {}")
        (dest / "src").mkdir(parents=True, exist_ok=True)
        (dest / "src" / "app.js").write_text("function g() {}")
        return subprocess.CompletedProcess(cmd, 0, stdout="", stderr="")

    monkeypatch.setattr(subprocess, "run", _fake_run)
    repo = from_github_url("https://github.com/some-owner/some-repo")
    assert {f.normalized_path for f in repo.files} == {"src/app.js"}


def test_from_github_url_cleans_up_scratch_dir_on_clone_failure(monkeypatch):
    before = set(Path(tempfile_gettempdir()).glob("foundry-clone-*"))

    def _fake_run(cmd, **kwargs):
        return subprocess.CompletedProcess(cmd, 128, stdout="", stderr="fatal: not found")

    monkeypatch.setattr(subprocess, "run", _fake_run)
    with pytest.raises(TargetIngestionError):
        from_github_url("https://github.com/nonexistent/nonexistent")
    after = set(Path(tempfile_gettempdir()).glob("foundry-clone-*"))
    assert after == before  # nothing new left behind by the failed clone
