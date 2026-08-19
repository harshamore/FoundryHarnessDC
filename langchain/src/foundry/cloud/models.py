"""Shapes shared by every IaC/IAM parser and `CloudResourceStore` -- the
cloud-domain equivalent of `foundry.indexer.parser`'s `FunctionDef`/
`CallEdge`/`IndexResult`, extended with the one thing infra parsing needs
that code parsing didn't: cross-resource references (a Lambda's `role`
attribute pointing at an IAM role) and permission grants (an IAM policy
statement), since Phase 7/8's exposure and exploitability analysis is
built entirely on top of these two.
"""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class CloudResource:
    file: str  # path normalized relative to the repo root
    resource_type: str  # e.g. "aws_lambda_function", "AWS::Lambda::Function", "Deployment"
    resource_name: str  # the block/logical-ID/metadata.name identifying it within its file
    provider: str  # "terraform" | "cloudformation" | "kubernetes"
    attributes: dict  # raw parsed attributes, JSON-serializable

    @property
    def address(self) -> str:
        """`resource_type.resource_name` -- the same shape Terraform's own
        reference syntax uses (`aws_iam_role.exec`), reused as the
        canonical identity for resources from every provider so
        `cloud_references` doesn't need a provider-specific join."""
        return f"{self.resource_type}.{self.resource_name}"


@dataclass(frozen=True)
class Grant:
    file: str
    principal: str  # the role/resource address this grant is attached to
    effect: str  # "Allow" | "Deny"
    actions: list[str]
    resources: list[str]


@dataclass(frozen=True)
class CloudParseResult:
    resources: list[CloudResource] = field(default_factory=list)
    references: list[tuple[str, str]] = field(default_factory=list)  # (from_address, to_address)
    grants: list[Grant] = field(default_factory=list)
