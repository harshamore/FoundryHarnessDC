"""Deterministic exposure classification (Phase 7): no LLM, no code
correlation yet -- purely "is this resource network-reachable, given its
own and its related resources' attributes." Same mechanically-derivable
spirit as the Indexer's parser and Cartographer's FR-036a fallback,
applied to infra configuration instead of code/security-map structure.

A pragmatic, growing rule set (like CodeGuard's own rule corpus), not an
exhaustive cloud security posture management engine -- a resource type
with no rule here reports not-exposed with an honest reason ("no known
public-exposure signal for this resource type"), never guessed either
way. Broader coverage is architecturally additive later (one more rule
function, appended to `_RULES`), not a redesign.
"""
from __future__ import annotations

from dataclasses import dataclass

from foundry.cloud.models import CloudResource

_PUBLIC_CIDRS = {"0.0.0.0/0", "::/0"}


@dataclass(frozen=True)
class ExposureFact:
    address: str
    is_exposed: bool
    reason: str


def _as_list(value) -> list:
    if value is None:
        return []
    return value if isinstance(value, list) else [value]


def _security_group_exposure(resource: CloudResource, related: list[CloudResource]) -> ExposureFact | None:
    if resource.resource_type not in ("aws_security_group", "AWS::EC2::SecurityGroup"):
        return None
    for rule in _as_list(resource.attributes.get("ingress") or resource.attributes.get("SecurityGroupIngress")):
        if not isinstance(rule, dict):
            continue
        cidrs = _as_list(rule.get("cidr_blocks") or rule.get("CidrIp"))
        if _PUBLIC_CIDRS & set(cidrs):
            return ExposureFact(resource.address, True, "ingress rule allows 0.0.0.0/0")
    return ExposureFact(resource.address, False, "no public ingress rule found")


def _s3_bucket_exposure(resource: CloudResource, related: list[CloudResource]) -> ExposureFact | None:
    if resource.resource_type not in ("aws_s3_bucket", "AWS::S3::Bucket"):
        return None
    for r in related:
        if r.resource_type == "aws_s3_bucket_public_access_block":
            flags = [
                r.attributes.get("block_public_acls", True),
                r.attributes.get("block_public_policy", True),
                r.attributes.get("ignore_public_acls", True),
                r.attributes.get("restrict_public_buckets", True),
            ]
            if not all(flags):
                return ExposureFact(resource.address, True, f"{r.address} does not block public access")
    acl = resource.attributes.get("acl")
    if isinstance(acl, str) and acl.startswith("public"):
        return ExposureFact(resource.address, True, f"bucket ACL is '{acl}'")
    return ExposureFact(resource.address, False, "no public-access-block override or public ACL found")


def _lambda_function_url_exposure(resource: CloudResource, related: list[CloudResource]) -> ExposureFact | None:
    if resource.resource_type != "aws_lambda_function":
        return None
    for r in related:
        if r.resource_type == "aws_lambda_function_url" and r.attributes.get("authorization_type") == "NONE":
            return ExposureFact(resource.address, True, f"{r.address} has authorization_type=NONE")
    return ExposureFact(resource.address, False, "no public function URL found")


def _kubernetes_service_exposure(resource: CloudResource, related: list[CloudResource]) -> ExposureFact | None:
    if resource.resource_type != "Service":
        return None
    spec = resource.attributes.get("spec") or {}
    service_type = spec.get("type") if isinstance(spec, dict) else None
    if service_type in ("LoadBalancer", "NodePort"):
        return ExposureFact(resource.address, True, f"Service type is {service_type}")
    for r in related:
        if r.resource_type == "Ingress":
            return ExposureFact(resource.address, True, f"referenced by Ingress {r.address}")
    return ExposureFact(resource.address, False, "ClusterIP Service with no referencing Ingress found")


_RULES = (
    _security_group_exposure,
    _s3_bucket_exposure,
    _lambda_function_url_exposure,
    _kubernetes_service_exposure,
)


def classify_exposure(resource: CloudResource, related: list[CloudResource]) -> ExposureFact:
    for rule in _RULES:
        fact = rule(resource, related)
        if fact is not None:
            return fact
    return ExposureFact(resource.address, False, "no known public-exposure signal for this resource type")


def classify_all_exposure(resources: list[CloudResource], references: list[tuple[str, str]]) -> list[ExposureFact]:
    """`related` for a resource is every resource it references plus
    every resource that references it -- e.g. an `aws_s3_bucket` and the
    `aws_s3_bucket_public_access_block` pointing at it are two separate
    resources, and exposure can only be determined by looking at both."""
    by_address = {r.address: r for r in resources}
    neighbors: dict[str, set[str]] = {}
    for src, dst in references:
        neighbors.setdefault(src, set()).add(dst)
        neighbors.setdefault(dst, set()).add(src)

    facts = []
    for resource in resources:
        related = [by_address[addr] for addr in neighbors.get(resource.address, ()) if addr in by_address]
        facts.append(classify_exposure(resource, related))
    return facts
