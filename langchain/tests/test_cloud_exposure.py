"""Phase 7 proofs: deterministic exposure classification
(src/foundry/cloud/exposure.py). No model call, no store dependency --
every test builds small resource sets by hand, same verification
approach the plan itself specifies.
"""
from __future__ import annotations

from foundry.cloud.exposure import classify_all_exposure, classify_exposure
from foundry.cloud.models import CloudResource


def _resource(rtype: str, name: str, provider: str, **attrs) -> CloudResource:
    return CloudResource(file="f", resource_type=rtype, resource_name=name, provider=provider, attributes=attrs)


# ---------------------------------------------------------------------------
# Security groups
# ---------------------------------------------------------------------------


def test_security_group_with_public_ingress_is_exposed():
    sg = _resource("aws_security_group", "open", "terraform", ingress=[{"cidr_blocks": ["0.0.0.0/0"]}])
    fact = classify_exposure(sg, [])
    assert fact.is_exposed is True
    assert "0.0.0.0/0" in fact.reason


def test_security_group_with_only_private_ingress_is_not_exposed():
    sg = _resource("aws_security_group", "closed", "terraform", ingress=[{"cidr_blocks": ["10.0.0.0/8"]}])
    fact = classify_exposure(sg, [])
    assert fact.is_exposed is False


def test_security_group_with_no_ingress_rules_is_not_exposed():
    sg = _resource("aws_security_group", "empty", "terraform")
    assert classify_exposure(sg, []).is_exposed is False


# ---------------------------------------------------------------------------
# S3 buckets
# ---------------------------------------------------------------------------


def test_s3_bucket_with_public_access_block_disabled_is_exposed():
    bucket = _resource("aws_s3_bucket", "uploads", "terraform", bucket="my-bucket")
    block = _resource(
        "aws_s3_bucket_public_access_block", "uploads", "terraform",
        block_public_acls=False, block_public_policy=False, ignore_public_acls=False, restrict_public_buckets=False,
    )
    fact = classify_exposure(bucket, [block])
    assert fact.is_exposed is True


def test_s3_bucket_with_public_access_block_enabled_is_not_exposed():
    bucket = _resource("aws_s3_bucket", "uploads", "terraform", bucket="my-bucket")
    block = _resource(
        "aws_s3_bucket_public_access_block", "uploads", "terraform",
        block_public_acls=True, block_public_policy=True, ignore_public_acls=True, restrict_public_buckets=True,
    )
    assert classify_exposure(bucket, [block]).is_exposed is False


def test_s3_bucket_with_no_public_access_block_at_all_is_not_exposed():
    """Absence of the block resource isn't itself a public-exposure
    signal -- default S3 buckets already block public access; only an
    explicit override (checked above) or a public ACL makes one exposed."""
    bucket = _resource("aws_s3_bucket", "uploads", "terraform", bucket="my-bucket")
    assert classify_exposure(bucket, []).is_exposed is False


def test_s3_bucket_with_public_read_acl_is_exposed():
    bucket = _resource("aws_s3_bucket", "uploads", "terraform", bucket="my-bucket", acl="public-read")
    assert classify_exposure(bucket, []).is_exposed is True


# ---------------------------------------------------------------------------
# Lambda function URLs
# ---------------------------------------------------------------------------


def test_lambda_with_public_function_url_is_exposed():
    fn = _resource("aws_lambda_function", "handler", "terraform")
    url = _resource("aws_lambda_function_url", "handler", "terraform", authorization_type="NONE")
    assert classify_exposure(fn, [url]).is_exposed is True


def test_lambda_with_iam_authorized_function_url_is_not_exposed():
    fn = _resource("aws_lambda_function", "handler", "terraform")
    url = _resource("aws_lambda_function_url", "handler", "terraform", authorization_type="AWS_IAM")
    assert classify_exposure(fn, [url]).is_exposed is False


def test_lambda_with_no_function_url_is_not_exposed():
    fn = _resource("aws_lambda_function", "handler", "terraform")
    assert classify_exposure(fn, []).is_exposed is False


# ---------------------------------------------------------------------------
# Kubernetes Services
# ---------------------------------------------------------------------------


def test_kubernetes_loadbalancer_service_is_exposed():
    svc = _resource("Service", "web", "kubernetes", spec={"type": "LoadBalancer"})
    assert classify_exposure(svc, []).is_exposed is True


def test_kubernetes_clusterip_service_referenced_by_ingress_is_exposed():
    svc = _resource("Service", "web", "kubernetes", spec={"type": "ClusterIP"})
    ingress = _resource("Ingress", "web-ingress", "kubernetes")
    assert classify_exposure(svc, [ingress]).is_exposed is True


def test_kubernetes_clusterip_service_with_no_ingress_is_not_exposed():
    svc = _resource("Service", "web", "kubernetes", spec={"type": "ClusterIP"})
    assert classify_exposure(svc, []).is_exposed is False


# ---------------------------------------------------------------------------
# Unmodeled resource types -- honest, not guessed
# ---------------------------------------------------------------------------


def test_unmodeled_resource_type_is_not_exposed_with_an_honest_reason():
    r = _resource("aws_dynamodb_table", "orders", "terraform")
    fact = classify_exposure(r, [])
    assert fact.is_exposed is False
    assert "no known public-exposure signal" in fact.reason


# ---------------------------------------------------------------------------
# classify_all_exposure -- relatedness via the reference graph
# ---------------------------------------------------------------------------


def test_classify_all_builds_relatedness_from_references_in_either_direction():
    bucket = _resource("aws_s3_bucket", "uploads", "terraform", bucket="my-bucket")
    block = _resource(
        "aws_s3_bucket_public_access_block", "uploads", "terraform",
        block_public_acls=False, block_public_policy=False, ignore_public_acls=False, restrict_public_buckets=False,
    )
    # The public-access-block resource references the bucket (not the
    # other way around) -- exposure still needs to see it as "related".
    references = [(block.address, bucket.address)]
    facts = {f.address: f for f in classify_all_exposure([bucket, block], references)}
    assert facts[bucket.address].is_exposed is True
