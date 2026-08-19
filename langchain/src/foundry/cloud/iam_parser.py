"""IAM policy document parsing -- both standalone policy JSON files and
the shared `statements_to_grants` helper `foundry.cloud.iac_parser` calls
for policies it finds embedded in Terraform/CloudFormation resources. No
model call; a policy document's `Statement` list is already fully
structured data, nothing here requires judgment.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from foundry.cloud.models import CloudParseResult, CloudResource, Grant


def _as_list(value: Any) -> list[str]:
    """IAM's own JSON grammar allows `Action`/`Resource` to be either a
    bare string or a list of strings -- normalized to a list either way,
    same shape regardless of which an author used."""
    if value is None:
        return []
    if isinstance(value, str):
        return [value]
    if isinstance(value, list):
        return [v for v in value if isinstance(v, str)]
    return []


def statements_to_grants(policy_document: dict, principal: str, source_file: str) -> list[Grant]:
    """`policy_document` is a real IAM policy document (`{"Version": ...,
    "Statement": [...]}`) -- `principal` is the resource address this
    policy is attached to (or, for a standalone policy file, the policy
    resource's own address; Phase 8's correlation step resolves the real
    attachment via reference edges, not this function)."""
    statement = policy_document.get("Statement")
    if isinstance(statement, dict):
        statement = [statement]
    if not isinstance(statement, list):
        return []

    grants: list[Grant] = []
    for s in statement:
        if not isinstance(s, dict):
            continue
        effect = s.get("Effect")
        if effect not in ("Allow", "Deny"):
            continue
        grants.append(
            Grant(
                file=source_file,
                principal=principal,
                effect=effect,
                actions=_as_list(s.get("Action")),
                resources=_as_list(s.get("Resource")),
            )
        )
    return grants


def parse_iam_policy_file(path: Path, normalized_path: str) -> CloudParseResult:
    """A standalone IAM policy JSON file -- either a bare policy document
    (`{"Version": ..., "Statement": [...]}`) or an exported-policy wrapper
    (`{"PolicyName": ..., "PolicyDocument": {...}}`, the shape `aws iam
    get-policy-version` produces). Represented as its own `CloudResource`
    (type `iam-policy`, named by the file's stem) so later phases can
    record which role/resource it's attached to via a reference edge, the
    same way any other resource reference works."""
    data = json.loads(path.read_text(encoding="utf-8"))
    policy_document = data.get("PolicyDocument") if isinstance(data.get("PolicyDocument"), dict) else data
    resource_name = data.get("PolicyName") or Path(normalized_path).stem

    resource = CloudResource(
        file=normalized_path,
        resource_type="iam-policy",
        resource_name=resource_name,
        provider="iam",
        attributes=data,
    )
    grants = statements_to_grants(policy_document, principal=resource.address, source_file=normalized_path)
    return CloudParseResult(resources=[resource], grants=grants)
