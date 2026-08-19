"""Phase 6 proofs: content-sniffing detection (src/foundry/cloud/detect.py).
No model call, no python-hcl2 dependency -- .tf detection is filename-only,
and every content-sniffed kind (CloudFormation/Kubernetes/IAM policy) uses
only pyyaml/json, both base dependencies.
"""
from __future__ import annotations

from pathlib import Path

from foundry.cloud.detect import detect_cloud_kind


def _write(tmp_path: Path, name: str, content: str) -> Path:
    path = tmp_path / name
    path.write_text(content)
    return path


def test_tf_extension_is_terraform_by_filename_alone(tmp_path):
    path = _write(tmp_path, "main.tf", "resource \"aws_s3_bucket\" \"x\" {}")
    assert detect_cloud_kind(path) == "terraform"


def test_cloudformation_yaml_detected_by_resources_type_marker(tmp_path):
    content = """
Resources:
  MyBucket:
    Type: AWS::S3::Bucket
"""
    path = _write(tmp_path, "template.yaml", content)
    assert detect_cloud_kind(path) == "cloudformation"


def test_cloudformation_detected_by_format_version(tmp_path):
    content = "AWSTemplateFormatVersion: '2010-09-09'\nResources: {}\n"
    path = _write(tmp_path, "template.yaml", content)
    assert detect_cloud_kind(path) == "cloudformation"


def test_kubernetes_yaml_detected_by_apiversion_and_kind(tmp_path):
    content = "apiVersion: apps/v1\nkind: Deployment\nmetadata:\n  name: x\n"
    path = _write(tmp_path, "deploy.yaml", content)
    assert detect_cloud_kind(path) == "kubernetes"


def test_iam_policy_json_detected_bare_document(tmp_path):
    content = '{"Version": "2012-10-17", "Statement": [{"Effect": "Allow", "Action": "s3:*"}]}'
    path = _write(tmp_path, "policy.json", content)
    assert detect_cloud_kind(path) == "iam-policy"


def test_iam_policy_json_detected_wrapped_document(tmp_path):
    content = '{"PolicyName": "x", "PolicyDocument": {"Version": "2012-10-17", "Statement": [{"Effect": "Allow", "Action": "s3:*"}]}}'
    path = _write(tmp_path, "policy.json", content)
    assert detect_cloud_kind(path) == "iam-policy"


def test_unrelated_json_is_not_detected(tmp_path):
    path = _write(tmp_path, "package.json", '{"name": "foo", "version": "1.0.0"}')
    assert detect_cloud_kind(path) is None


def test_unrelated_yaml_is_not_detected(tmp_path):
    path = _write(tmp_path, "docker-compose.yaml", "services:\n  web:\n    image: nginx\n")
    assert detect_cloud_kind(path) is None


def test_unsupported_extension_returns_none(tmp_path):
    path = _write(tmp_path, "README.md", "# hello")
    assert detect_cloud_kind(path) is None


def test_malformed_json_fails_closed(tmp_path):
    path = _write(tmp_path, "broken.json", "{not valid json")
    assert detect_cloud_kind(path) is None


def test_malformed_yaml_fails_closed(tmp_path):
    path = _write(tmp_path, "broken.yaml", "kind: [unterminated")
    assert detect_cloud_kind(path) is None
