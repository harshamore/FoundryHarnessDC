"""Phase 7 proofs: deterministic grant/reachability resolution
(src/foundry/cloud/graph.py). No model call -- hand-built resource/
reference/grant sets, same as test_cloud_exposure.py's approach.
"""
from __future__ import annotations

from foundry.cloud.graph import compute_reachability
from foundry.cloud.models import CloudResource, Grant


def _resource(rtype: str, resource_name: str, **attrs) -> CloudResource:
    return CloudResource(file="f", resource_type=rtype, resource_name=resource_name, provider="terraform", attributes=attrs)


def test_resource_reaches_grants_attached_directly_to_its_identity():
    role = _resource("aws_iam_role", "exec")
    fn = _resource("aws_lambda_function", "handler")
    grant = Grant(file="f", principal=role.address, effect="Allow", actions=["s3:GetObject"], resources=["arn:aws:s3:::x"])

    edges = compute_reachability([role, fn], [(fn.address, role.address)], [grant])
    assert len(edges) == 1
    assert edges[0].from_address == fn.address
    assert edges[0].principal == role.address
    assert edges[0].actions == ["s3:GetObject"]


def test_resource_reaches_grants_attached_via_an_inline_policy_resource():
    """The real-world Terraform/CloudFormation shape: the grant is on a
    separate policy resource that itself references the role, not on the
    role's own address."""
    role = _resource("aws_iam_role", "exec")
    policy = _resource("aws_iam_role_policy", "inline")
    fn = _resource("aws_lambda_function", "handler")
    grant = Grant(file="f", principal=policy.address, effect="Allow", actions=["s3:*"], resources=["arn:aws:s3:::x"])

    references = [(fn.address, role.address), (policy.address, role.address)]
    edges = compute_reachability([role, policy, fn], references, [grant])
    assert len(edges) == 1
    assert edges[0].from_address == fn.address
    assert edges[0].principal == role.address
    assert edges[0].actions == ["s3:*"]


def test_deny_grants_never_produce_a_reachability_edge():
    role = _resource("aws_iam_role", "exec")
    fn = _resource("aws_lambda_function", "handler")
    grant = Grant(file="f", principal=role.address, effect="Deny", actions=["s3:*"], resources=["arn:aws:s3:::x"])

    edges = compute_reachability([role, fn], [(fn.address, role.address)], [grant])
    assert edges == []


def test_unreferenced_grant_is_never_reachable_from_anything():
    """A grant that exists in the parsed data but isn't attached to
    anything via a reference edge -- the 'not correlated' honesty case,
    proven at the graph level: no fabricated edge appears."""
    role = _resource("aws_iam_role", "orphaned")
    fn = _resource("aws_lambda_function", "handler")  # does not reference role at all
    grant = Grant(file="f", principal=role.address, effect="Allow", actions=["s3:*"], resources=["arn:aws:s3:::x"])

    edges = compute_reachability([role, fn], [], [grant])
    assert edges == []


def test_matched_resource_is_set_when_a_known_resource_matches_the_arn_pattern():
    role = _resource("aws_iam_role", "exec")
    fn = _resource("aws_lambda_function", "handler")
    bucket = _resource("aws_s3_bucket", "prod_data", bucket="prod-data-bucket")
    grant = Grant(file="f", principal=role.address, effect="Allow", actions=["s3:*"], resources=["arn:aws:s3:::prod-*"])

    edges = compute_reachability([role, fn, bucket], [(fn.address, role.address)], [grant])
    assert edges[0].matched_resource == bucket.address


def test_matched_resource_is_none_when_no_known_resource_matches():
    role = _resource("aws_iam_role", "exec")
    fn = _resource("aws_lambda_function", "handler")
    grant = Grant(file="f", principal=role.address, effect="Allow", actions=["s3:*"], resources=["arn:aws:s3:::prod-*"])

    edges = compute_reachability([role, fn], [(fn.address, role.address)], [grant])
    assert edges[0].matched_resource is None


def test_matched_resource_is_none_for_unmodeled_resource_types():
    """DynamoDB ARN construction isn't implemented -- a grant naming a
    DynamoDB table never gets a fabricated match, even if a same-named
    aws_dynamodb_table resource exists."""
    role = _resource("aws_iam_role", "exec")
    fn = _resource("aws_lambda_function", "handler")
    table = _resource("aws_dynamodb_table", "orders", name="orders")
    grant = Grant(file="f", principal=role.address, effect="Allow", actions=["dynamodb:*"], resources=["arn:aws:dynamodb:*:*:table/orders"])

    edges = compute_reachability([role, fn, table], [(fn.address, role.address)], [grant])
    assert edges[0].matched_resource is None
