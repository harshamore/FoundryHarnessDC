"""Detects whether a file is IaC/IAM content this package can parse, and
which kind. Unlike `foundry.indexer.parser.detect_language` (a pure
filename lookup), this has to read and sniff content: `.yaml`/`.yml`/
`.json` are used by CloudFormation, Kubernetes manifests, IAM policy
documents, *and* countless unrelated config files (docker-compose, CI
pipelines, package.json, ...) -- extension alone can't tell them apart,
and a false-positive match would feed garbage into `iac_parser`/
`iam_parser`. Every sniff fails closed: any read/parse error, or content
that doesn't match a known shape, returns `None` rather than guessing --
same "absent, not fabricated" discipline as everything else in this
codebase that classifies uncertain input.
"""
from __future__ import annotations

import json
from pathlib import Path

import yaml

CLOUD_KINDS = ("terraform", "cloudformation", "kubernetes", "iam-policy")

_CANDIDATE_EXTENSIONS = {".tf", ".yaml", ".yml", ".json"}


def _looks_like_cloudformation(doc: dict) -> bool:
    if "AWSTemplateFormatVersion" in doc:
        return True
    resources = doc.get("Resources")
    if not isinstance(resources, dict):
        return False
    return any(
        isinstance(r, dict) and isinstance(r.get("Type"), str) and r["Type"].startswith("AWS::")
        for r in resources.values()
    )


def _looks_like_kubernetes(doc: dict) -> bool:
    return isinstance(doc.get("apiVersion"), str) and isinstance(doc.get("kind"), str)


def _looks_like_iam_policy(doc: dict) -> bool:
    # Either a bare policy document, or the exported-policy wrapper shape
    # (`{"PolicyName": ..., "PolicyDocument": {...}}`) `aws iam
    # get-policy-version` produces -- foundry.cloud.iam_parser.
    # parse_iam_policy_file accepts both, so detection must recognize
    # both too.
    candidate = doc.get("PolicyDocument") if isinstance(doc.get("PolicyDocument"), dict) else doc
    statement = candidate.get("Statement")
    if isinstance(statement, dict):
        statement = [statement]
    if not isinstance(statement, list) or not statement:
        return False
    return all(isinstance(s, dict) and "Effect" in s and "Action" in s for s in statement)


def detect_cloud_kind(path: Path) -> str | None:
    """One of `CLOUD_KINDS`, or `None` if `path` isn't recognized IaC/IAM
    content (including: not one of the candidate extensions, unreadable,
    or valid YAML/JSON that just doesn't match any known shape)."""
    suffix = path.suffix.lower()
    if suffix not in _CANDIDATE_EXTENSIONS:
        return None

    if suffix == ".tf":
        return "terraform"

    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return None

    docs: list[dict] = []
    try:
        if suffix == ".json":
            parsed = json.loads(text)
            if isinstance(parsed, dict):
                docs = [parsed]
        else:
            for parsed in yaml.safe_load_all(text):
                if isinstance(parsed, dict):
                    docs.append(parsed)
    except (json.JSONDecodeError, yaml.YAMLError):
        return None

    if not docs:
        return None

    # Kubernetes manifests can be multi-document YAML; CloudFormation/IAM
    # documents are always exactly one. Checking the first document is
    # enough to classify the file -- a mixed-kind file isn't a real
    # authoring pattern for any of these formats.
    first = docs[0]
    if _looks_like_kubernetes(first):
        return "kubernetes"
    if _looks_like_cloudformation(first):
        return "cloudformation"
    if _looks_like_iam_policy(first):
        return "iam-policy"
    return None
