"""Phase 6 proofs: IaC/IAM parsing (src/foundry/cloud/iac_parser.py,
src/foundry/cloud/iam_parser.py). No model call anywhere. Terraform tests
are skipped (not failed) when the `[cloud]` extra (`python-hcl2`) isn't
installed, matching test_observability.py's own convention for its
optional dependency.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from foundry.cloud.iac_parser import parse_cloudformation, parse_iac_file, parse_kubernetes
from foundry.cloud.iam_parser import parse_iam_policy_file, statements_to_grants

REPO_ROOT = Path(__file__).resolve().parent.parent
FIXTURE = REPO_ROOT / "data" / "cloud_toy_target"


def _write(tmp_path: Path, name: str, content: str) -> Path:
    path = tmp_path / name
    path.write_text(content)
    return path


# ---------------------------------------------------------------------------
# Terraform (requires the [cloud] extra)
# ---------------------------------------------------------------------------

# A module-level `pytest.importorskip("hcl2")` would skip this *entire
# file*, including the CloudFormation/Kubernetes/IAM tests below that
# don't touch hcl2 at all -- scoped to just the four Terraform tests
# instead, via this marker, so the rest of the file still runs without
# the [cloud] extra installed.
try:
    import hcl2  # noqa: F401

    _HAS_HCL2 = True
except ImportError:
    _HAS_HCL2 = False

requires_hcl2 = pytest.mark.skipif(not _HAS_HCL2, reason="python-hcl2 not installed (pip install -e '.[cloud]')")


@requires_hcl2
def test_parse_terraform_extracts_resources_from_the_fixture():
    result = parse_iac_file(FIXTURE / "main.tf", "main.tf", "terraform")
    addresses = {r.address for r in result.resources}
    assert addresses == {
        "aws_iam_role.lambda_exec",
        "aws_iam_role_policy.lambda_exec_inline",
        "aws_lambda_function.process_upload",
        "aws_s3_bucket.uploads",
        "aws_s3_bucket_public_access_block.uploads",
    }


@requires_hcl2
def test_parse_terraform_extracts_reference_edges_from_interpolation():
    result = parse_iac_file(FIXTURE / "main.tf", "main.tf", "terraform")
    assert ("aws_lambda_function.process_upload", "aws_iam_role.lambda_exec") in result.references
    assert ("aws_s3_bucket_public_access_block.uploads", "aws_s3_bucket.uploads") in result.references


@requires_hcl2
def test_parse_terraform_extracts_literal_json_inline_policy_as_a_grant():
    result = parse_iac_file(FIXTURE / "main.tf", "main.tf", "terraform")
    grants = [g for g in result.grants if g.principal == "aws_iam_role_policy.lambda_exec_inline"]
    assert len(grants) == 1
    assert grants[0].effect == "Allow"
    assert "s3:*" in grants[0].actions
    assert "arn:aws:s3:::prod-*" in grants[0].resources


@requires_hcl2
def test_parse_terraform_jsonencode_policy_yields_no_grants_not_an_error(tmp_path):
    """Documented limitation: jsonencode() is an unevaluated HCL
    expression, not literal JSON -- the resource still parses, just
    without grants, rather than raising or fabricating one."""
    content = """
    resource "aws_iam_role_policy" "x" {
      name   = "x"
      policy = jsonencode({ Version = "2012-10-17" })
    }
    """
    path = _write(tmp_path, "main.tf", content)
    result = parse_iac_file(path, "main.tf", "terraform")
    assert len(result.resources) == 1
    assert result.grants == []


# ---------------------------------------------------------------------------
# CloudFormation (no extra needed -- pyyaml/json only)
# ---------------------------------------------------------------------------


def test_parse_cloudformation_extracts_resources_and_ref_edges():
    """Uses the short-form `!GetAtt`/`!Ref` intrinsic tags real
    CloudFormation templates overwhelmingly use -- plain `yaml.safe_load`
    has no constructor for these at all (verified directly: raises
    ConstructorError), so this also proves parse_cloudformation's
    dedicated loader handles them, not just the long-form `Fn::GetAtt`
    dict shape."""
    text = """
Resources:
  MyRole:
    Type: AWS::IAM::Role
    Properties:
      RoleName: my-role
  MyFunction:
    Type: AWS::Lambda::Function
    Properties:
      Role: !GetAtt MyRole.Arn
      FunctionName: my-function
"""
    result = parse_cloudformation(text, "template.yaml")
    addresses = {r.address for r in result.resources}
    assert addresses == {"AWS::IAM::Role.MyRole", "AWS::Lambda::Function.MyFunction"}
    assert ("AWS::Lambda::Function.MyFunction", "AWS::IAM::Role.MyRole") in result.references


def test_parse_cloudformation_handles_ref_short_form_too():
    text = """
Resources:
  MyTopic:
    Type: AWS::SNS::Topic
  MySubscription:
    Type: AWS::SNS::Subscription
    Properties:
      TopicArn: !Ref MyTopic
"""
    result = parse_cloudformation(text, "template.yaml")
    assert ("AWS::SNS::Subscription.MySubscription", "AWS::SNS::Topic.MyTopic") in result.references


def test_parse_cloudformation_extracts_grants_from_iam_policy_resource():
    text = """
Resources:
  MyPolicy:
    Type: AWS::IAM::Policy
    Properties:
      PolicyDocument:
        Statement:
          - Effect: Allow
            Action: ["s3:GetObject"]
            Resource: ["arn:aws:s3:::bucket/*"]
"""
    result = parse_cloudformation(text, "template.yaml")
    assert len(result.grants) == 1
    assert result.grants[0].actions == ["s3:GetObject"]


# ---------------------------------------------------------------------------
# Kubernetes (no extra needed)
# ---------------------------------------------------------------------------


def test_parse_kubernetes_extracts_resources_from_the_fixture():
    text = (FIXTURE / "k8s-deployment.yaml").read_text()
    result = parse_kubernetes(text, "k8s-deployment.yaml")
    addresses = {r.address for r in result.resources}
    assert addresses == {
        "ServiceAccount.process-upload-sa",
        "RoleBinding.process-upload-binding",
        "Deployment.process-upload",
    }


def test_parse_kubernetes_role_ref_uses_the_actual_target_kind():
    """roleRef's target kind varies (Role vs ClusterRole) and must be
    read from roleRef.kind itself, not assumed to be a ServiceAccount."""
    text = (FIXTURE / "k8s-deployment.yaml").read_text()
    result = parse_kubernetes(text, "k8s-deployment.yaml")
    assert ("RoleBinding.process-upload-binding", "ClusterRole.prod-admin") in result.references


def test_parse_kubernetes_deployment_references_its_service_account():
    text = (FIXTURE / "k8s-deployment.yaml").read_text()
    result = parse_kubernetes(text, "k8s-deployment.yaml")
    assert ("Deployment.process-upload", "ServiceAccount.process-upload-sa") in result.references


# ---------------------------------------------------------------------------
# IAM policy files
# ---------------------------------------------------------------------------


def test_parse_iam_policy_file_wrapped_format():
    result = parse_iam_policy_file(FIXTURE / "iam_policy.json", "iam_policy.json")
    assert len(result.resources) == 1
    assert result.resources[0].resource_name == "prod-admin-policy"
    assert len(result.grants) == 1
    assert "s3:*" in result.grants[0].actions
    assert "secretsmanager:GetSecretValue" in result.grants[0].actions


def test_parse_iam_policy_file_bare_document(tmp_path):
    content = '{"Version": "2012-10-17", "Statement": [{"Effect": "Allow", "Action": "s3:GetObject", "Resource": "arn:aws:s3:::x/*"}]}'
    path = _write(tmp_path, "bare.json", content)
    result = parse_iam_policy_file(path, "bare.json")
    assert result.resources[0].resource_name == "bare"  # falls back to filename stem
    assert result.grants[0].actions == ["s3:GetObject"]


def test_statements_to_grants_normalizes_scalar_action_and_resource_to_lists():
    doc = {"Statement": {"Effect": "Allow", "Action": "s3:GetObject", "Resource": "arn:aws:s3:::x"}}
    grants = statements_to_grants(doc, principal="role.x", source_file="f.json")
    assert grants == [
        type(grants[0])(file="f.json", principal="role.x", effect="Allow", actions=["s3:GetObject"], resources=["arn:aws:s3:::x"])
    ]


def test_statements_to_grants_skips_statements_without_a_recognized_effect():
    doc = {"Statement": [{"Action": "s3:*"}]}  # no Effect at all
    assert statements_to_grants(doc, principal="role.x", source_file="f.json") == []
