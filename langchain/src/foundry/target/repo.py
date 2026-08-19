"""Target ingestion (Phase 1 of the productization plan): produces a
`TargetRepo` -- a local directory of source files ready for the Indexer --
from either uploaded file content or a public GitHub repository URL.
Deterministic file/network I/O only; no agent, no model call anywhere in
this module.

Two things this module exists specifically to get right, not just "make it
work": GitHub URLs are user-supplied input reaching a subprocess, so `git
clone` is invoked with an explicit argument list built from a validated
owner/repo match, never a shell string interpolated from the raw input
(command-injection risk otherwise); and a real repo can be far larger than
this harness should try to swallow whole, so both a file-count and a
total-byte cap are enforced before anything gets indexed, with common
dependency/build directories (`node_modules`, `.venv`, `vendor`, ...)
skipped during the walk so those caps measure the actual source tree, not
a checked-out dependency graph.
"""
from __future__ import annotations

import re
import shutil
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path

from foundry.cloud.detect import detect_cloud_kind
from foundry.indexer.parser import detect_language

DEFAULT_MAX_FILES = 200
DEFAULT_MAX_TOTAL_BYTES = 5 * 1024 * 1024  # 5 MB
CLONE_TIMEOUT_SECONDS = 120

# Only a public GitHub repo URL, optionally with a trailing `.git` or `/`.
# Anything else is rejected outright, before `git clone` ever sees it.
_GITHUB_URL_RE = re.compile(r"^https://github\.com/(?P<owner>[\w.-]+)/(?P<repo>[\w.-]+?)(\.git)?/?$")

# A pragmatic denylist, not full .gitignore parsing: the directories most
# likely to make a real repo's file count explode with content that was
# never going to be indexed anyway (dependencies, build output, caches).
_SKIP_DIR_NAMES = {
    ".git",
    "node_modules",
    "__pycache__",
    ".venv",
    "venv",
    "dist",
    "build",
    "target",  # Java/Maven build output
    "vendor",  # Go (and some JS tooling) vendored dependencies
    ".next",
    ".pytest_cache",
    "bin",
    "obj",  # .NET build output
}


class TargetIngestionError(ValueError):
    """Raised for any invalid/rejected target input -- a malformed URL, an
    oversized upload, a failed clone, a path-traversal attempt in an
    uploaded filename. Always a ValueError subclass, matching this
    codebase's existing convention (e.g. CoverageStore.build_checklist,
    IndexStore.get_function_body) of raising ValueError for invalid input
    rather than a bespoke exception hierarchy callers have to learn."""


@dataclass(frozen=True)
class TargetFile:
    path: Path  # absolute path on disk
    normalized_path: str  # relative to the target root -- matches IndexStore's `file` column convention
    language: str | None  # foundry.indexer.parser language name, or None if not one of Phase 1's supported languages


@dataclass(frozen=True)
class CloudFile:
    path: Path
    normalized_path: str
    kind: str  # one of foundry.cloud.detect.CLOUD_KINDS


@dataclass(frozen=True)
class TargetRepo:
    root: Path
    files: list[TargetFile]

    @property
    def languages(self) -> set[str]:
        """Every distinct supported language actually present -- the real
        input to CodeGuard's language-filtered rule-sweep
        (`foundry.codeguard.loader.load_rules`'s `languages=` argument)."""
        return {f.language for f in self.files if f.language is not None}

    @property
    def cloud_files(self) -> list[CloudFile]:
        """IaC/IAM content among the unsupported (not-a-code-language)
        files, content-sniffed (see `foundry.cloud.detect`) since
        extension alone can't tell a Kubernetes manifest from an
        unrelated YAML config file. Computed lazily, not during the walk
        itself -- `_walk_target` stays a pure filename lookup, and this
        property re-reads only the small subset of files whose extension
        is even a candidate."""
        cloud: list[CloudFile] = []
        for f in self.unsupported_files:
            kind = detect_cloud_kind(f.path)
            if kind is not None:
                cloud.append(CloudFile(path=f.path, normalized_path=f.normalized_path, kind=kind))
        return cloud

    @property
    def unsupported_files(self) -> list[TargetFile]:
        """Files walked but not structurally indexable as *code* -- Phase
        1's language set is Python/JavaScript/TypeScript/TSX/Java/Go, not
        every language. Tracked explicitly, not silently dropped, so a
        caller can still show them as a file inventory even though the
        Indexer can't parse them. Some of these are further recognized as
        IaC/IAM content by `cloud_files` above -- "unsupported as code"
        and "cloud-analyzable" are not mutually exclusive categories."""
        return [f for f in self.files if f.language is None]


def _walk_target(root: Path, max_files: int, max_total_bytes: int) -> list[TargetFile]:
    files: list[TargetFile] = []
    total_bytes = 0
    for path in sorted(root.rglob("*")):
        if not path.is_file():
            continue
        relative_parts = path.relative_to(root).parts
        if _SKIP_DIR_NAMES & set(relative_parts[:-1]):
            continue
        if len(files) >= max_files:
            raise TargetIngestionError(
                f"Target has more than {max_files} files (after skipping dependency/build "
                f"directories) -- refusing to index an unbounded repo. Pass max_files explicitly "
                f"to raise this if you really mean it."
            )
        total_bytes += path.stat().st_size
        if total_bytes > max_total_bytes:
            raise TargetIngestionError(
                f"Target exceeds {max_total_bytes} bytes total -- refusing to index an unbounded repo."
            )
        normalized = str(path.relative_to(root))
        files.append(TargetFile(path=path, normalized_path=normalized, language=detect_language(path)))
    return files


def from_upload(
    files: dict[str, bytes],
    max_files: int = DEFAULT_MAX_FILES,
    max_total_bytes: int = DEFAULT_MAX_TOTAL_BYTES,
) -> TargetRepo:
    """Build a TargetRepo from uploaded file content. `files` maps a
    relative filename to its raw bytes -- the shape a multipart upload or
    Colab's `google.colab.files.upload()` naturally produces."""
    if not files:
        raise TargetIngestionError("No files uploaded.")

    scratch = Path(tempfile.mkdtemp(prefix="foundry-upload-")).resolve()
    try:
        for name, content in files.items():
            dest = (scratch / name).resolve()
            if scratch not in dest.parents and dest != scratch:
                raise TargetIngestionError(f"Refusing to write outside the upload's scratch directory: {name!r}")
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_bytes(content)
        return TargetRepo(root=scratch, files=_walk_target(scratch, max_files, max_total_bytes))
    except Exception:
        shutil.rmtree(scratch, ignore_errors=True)
        raise


def from_github_url(
    url: str,
    max_files: int = DEFAULT_MAX_FILES,
    max_total_bytes: int = DEFAULT_MAX_TOTAL_BYTES,
) -> TargetRepo:
    """Shallow-clone a public GitHub repository and build a TargetRepo from
    it. `url` MUST match `https://github.com/<owner>/<repo>` -- anything
    else is rejected before `git clone` ever runs, and the URL actually
    passed to `git clone` is rebuilt from the validated owner/repo capture
    groups, not the raw input string, so a regex gap can't become a
    command-injection path even in principle."""
    match = _GITHUB_URL_RE.match(url.strip())
    if not match:
        raise TargetIngestionError(
            f"'{url}' doesn't look like a public GitHub repo URL (expected https://github.com/<owner>/<repo>)."
        )
    clone_url = f"https://github.com/{match['owner']}/{match['repo']}.git"

    scratch = Path(tempfile.mkdtemp(prefix="foundry-clone-")).resolve()
    try:
        try:
            result = subprocess.run(
                ["git", "clone", "--quiet", "--depth", "1", clone_url, str(scratch)],
                capture_output=True,
                text=True,
                timeout=CLONE_TIMEOUT_SECONDS,
            )
        except subprocess.TimeoutExpired as e:
            raise TargetIngestionError(f"Cloning {clone_url} timed out after {CLONE_TIMEOUT_SECONDS}s.") from e
        if result.returncode != 0:
            raise TargetIngestionError(f"Failed to clone {clone_url}: {result.stderr.strip()}")
        return TargetRepo(root=scratch, files=_walk_target(scratch, max_files, max_total_bytes))
    except Exception:
        shutil.rmtree(scratch, ignore_errors=True)
        raise
