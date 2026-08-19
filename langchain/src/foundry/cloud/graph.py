"""Deterministic grant resolution (Phase 7): given the reference graph
Phase 6 already extracted, walk from a resource to its attached
identity, then to that identity's grants, to answer "what can this
resource's identity actually reach?" A real, bounded graph walk over
already-persisted facts -- no model call, same spirit as Phase 6's
parsers and `exposure.py`.

The reference shape this walks is exactly what Phase 6 produces for the
"inline policy attached to a role" pattern both Terraform and
CloudFormation use: a Lambda references its role directly
(`aws_lambda_function.x -> aws_iam_role.y`), and the *policy* resource
separately references the same role to declare the attachment
(`aws_iam_role_policy.z -> aws_iam_role.y`) while carrying the grant
itself (`principal=aws_iam_role_policy.z`). Reaching a role's real
grants therefore means checking both the role's own address *and* every
resource that references the role, not just the role's address alone.
"""
from __future__ import annotations

import fnmatch
from dataclasses import dataclass

from foundry.cloud.models import CloudResource, Grant


@dataclass(frozen=True)
class ReachabilityEdge:
    from_address: str  # the resource whose identity was walked
    principal: str  # the role/identity address the grant is attached to
    actions: list[str]
    resource_pattern: str  # the raw ARN/resource pattern from the grant
    matched_resource: str | None  # a known CloudResource address, if confidently matched


# Provider/resource-type-specific ARN construction -- a real, growing
# mapping problem (each AWS resource type has its own ARN format), not
# attempted exhaustively. A resource type with no entry here simply never
# gets matched_resource set, the same honest "not correlated" default
# used throughout this phase rather than a fabricated guess.
def _guess_arn(resource: CloudResource) -> str | None:
    if resource.resource_type in ("aws_s3_bucket", "AWS::S3::Bucket"):
        name = resource.attributes.get("bucket") or resource.attributes.get("BucketName") or resource.resource_name
        return f"arn:aws:s3:::{name}"
    return None


def _match_resource(pattern: str, resources: list[CloudResource]) -> str | None:
    for r in resources:
        arn = _guess_arn(r)
        if arn and fnmatch.fnmatchcase(arn, pattern):
            return r.address
    return None


# Identity/policy-definition resource types are never themselves treated
# as a "workload" to compute reachability *from* -- an IAM policy
# resource referencing its own role would otherwise be walked exactly
# like a Lambda referencing that same role, and inherit its own grant as
# a circular "self-reaches" edge. Only actual compute/workload resources
# have a meaningful blast radius to ask about.
_IDENTITY_RESOURCE_TYPES = {
    "aws_iam_role",
    "aws_iam_role_policy",
    "aws_iam_policy",
    "aws_iam_user_policy",
    "aws_iam_group_policy",
    "iam-policy",
    "AWS::IAM::Role",
    "AWS::IAM::Policy",
    "AWS::IAM::ManagedPolicy",
}


def compute_reachability(
    resources: list[CloudResource],
    references: list[tuple[str, str]],
    grants: list[Grant],
) -> list[ReachabilityEdge]:
    outgoing: dict[str, list[str]] = {}
    incoming: dict[str, list[str]] = {}
    for src, dst in references:
        outgoing.setdefault(src, []).append(dst)
        incoming.setdefault(dst, []).append(src)

    grants_by_principal: dict[str, list[Grant]] = {}
    for g in grants:
        grants_by_principal.setdefault(g.principal, []).append(g)

    edges: list[ReachabilityEdge] = []
    for resource in resources:
        if resource.resource_type in _IDENTITY_RESOURCE_TYPES:
            continue
        for identity_address in outgoing.get(resource.address, []):
            attached_grants = list(grants_by_principal.get(identity_address, []))
            for attacher in incoming.get(identity_address, []):
                attached_grants.extend(grants_by_principal.get(attacher, []))

            for grant in attached_grants:
                if grant.effect != "Allow":
                    continue
                for pattern in grant.resources:
                    edges.append(
                        ReachabilityEdge(
                            from_address=resource.address,
                            principal=identity_address,
                            actions=grant.actions,
                            resource_pattern=pattern,
                            matched_resource=_match_resource(pattern, resources),
                        )
                    )
    return edges
