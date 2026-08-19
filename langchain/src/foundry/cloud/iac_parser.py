"""Deterministic IaC parsing: Terraform (HCL2), CloudFormation, and
Kubernetes manifests, each into the same `CloudParseResult` shape
`foundry.cloud.models` defines. No model call anywhere in this file --
same FR-020 spirit the code parser follows (`foundry.indexer.parser`),
applied to infrastructure instead of source.

**Known, documented limitation, not a silent gap**: Terraform's
`jsonencode(...)` expression (the idiomatic way to write an inline IAM
policy) is not evaluated here -- `python-hcl2` leaves function-call
expressions as opaque, unparsed strings, and actually evaluating HCL's
expression language is out of scope for this parser. A `policy`
attribute is only turned into `Grant`s when it's a literal JSON string
(`policy = "{...}"` or a heredoc containing raw JSON) -- `jsonencode()`
policies parse as a resource with no grants extracted, not an error and
not a fabricated grant. Standalone IAM policy JSON files (see
`foundry.cloud.iam_parser`) don't have this limitation.

`hcl2` (the `[cloud]` extra) is imported lazily, inside `parse_terraform`
itself, not at this module's top level -- `foundry.orchestration.
assessment` (a core module, always imported) imports from this file
unconditionally, so a top-level `import hcl2` here would break the
*entire* harness for anyone who installed without `[cloud]`, the same
reason `foundry.observability.galileo.build_galileo_callback` imports
`galileo` lazily instead of at its module's top level.
"""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

import yaml

from foundry.cloud.iam_parser import statements_to_grants
from foundry.cloud.models import CloudParseResult, CloudResource, Grant

# Matches a Terraform reference inside interpolation syntax, e.g.
# "${aws_iam_role.lambda_exec.arn}" -> ("aws_iam_role", "lambda_exec").
# Deliberately stops at the second segment (the resource address) even
# though the full expression may continue (`.arn`, `[0]`, ...) -- only
# *which resource* is referenced matters for the reference graph, not
# which of its attributes.
_TF_REFERENCE_RE = re.compile(r"\$\{\s*([a-zA-Z_][\w]*)\.([a-zA-Z_][\w-]*)")

# Terraform resource types whose `policy`-shaped attribute is IAM policy
# JSON, not arbitrary config -- the only place this parser looks for
# literal-JSON grants.
_IAM_POLICY_RESOURCE_TYPES = {
    "aws_iam_role_policy",
    "aws_iam_policy",
    "aws_iam_user_policy",
    "aws_iam_group_policy",
}


def _walk_strings(value: Any):
    if isinstance(value, str):
        yield value
    elif isinstance(value, dict):
        for v in value.values():
            yield from _walk_strings(v)
    elif isinstance(value, list):
        for v in value:
            yield from _walk_strings(v)


def _extract_tf_references(attributes: dict) -> set[str]:
    refs: set[str] = set()
    for s in _walk_strings(attributes):
        for match in _TF_REFERENCE_RE.finditer(s):
            refs.add(f"{match.group(1)}.{match.group(2)}")
    return refs


def _literal_json_policy(attributes: dict) -> dict | None:
    policy = attributes.get("policy")
    if not isinstance(policy, str):
        return None
    try:
        parsed = json.loads(policy)
    except json.JSONDecodeError:
        return None
    return parsed if isinstance(parsed, dict) else None


def parse_terraform(path: Path, normalized_path: str) -> CloudParseResult:
    try:
        import hcl2
    except ImportError as e:
        raise ImportError(
            "Parsing Terraform (.tf) files requires the 'cloud' extra: pip install -e '.[cloud]'"
        ) from e

    with path.open("r", encoding="utf-8") as f:
        data = hcl2.load(f)

    resources: list[CloudResource] = []
    references: list[tuple[str, str]] = []
    grants: list[Grant] = []

    for block in data.get("resource", []):
        for resource_type, named in block.items():
            for resource_name, attributes in named.items():
                resource = CloudResource(
                    file=normalized_path,
                    resource_type=resource_type,
                    resource_name=resource_name,
                    provider="terraform",
                    attributes=attributes,
                )
                resources.append(resource)
                for target in _extract_tf_references(attributes):
                    references.append((resource.address, target))

                if resource_type in _IAM_POLICY_RESOURCE_TYPES:
                    policy_doc = _literal_json_policy(attributes)
                    if policy_doc:
                        grants.extend(statements_to_grants(policy_doc, principal=resource.address, source_file=normalized_path))

    return CloudParseResult(resources=resources, references=references, grants=grants)


def _walk_cfn_refs(value: Any) -> set[str]:
    refs: set[str] = set()
    if isinstance(value, dict):
        if "Ref" in value and isinstance(value["Ref"], str):
            refs.add(value["Ref"])
        get_att = value.get("Fn::GetAtt")
        if isinstance(get_att, list) and get_att and isinstance(get_att[0], str):
            refs.add(get_att[0])
        elif isinstance(get_att, str):
            refs.add(get_att.split(".", 1)[0])
        for v in value.values():
            refs |= _walk_cfn_refs(v)
    elif isinstance(value, list):
        for v in value:
            refs |= _walk_cfn_refs(v)
    return refs


class _CloudFormationLoader(yaml.SafeLoader):
    """A `yaml.SafeLoader` subclass, not a monkeypatch of `yaml.SafeLoader`
    itself -- `foundry.cloud.iac_parser.parse_kubernetes` and
    `foundry.cloud.detect` both also call plain `yaml.safe_load(_all)`
    elsewhere in this same process, and CloudFormation's short-form
    intrinsic tags (`!Ref`, `!GetAtt`, `!Sub`, ...) are not a Kubernetes
    concept -- scoping this to a dedicated subclass, used only here,
    keeps that path untouched."""


def _cfn_tag_constructor(loader: yaml.SafeLoader, tag_suffix: str, node: yaml.Node):
    """Rewrites `!Xxx ...` into the long-form intrinsic-function dict
    shape (`{"Fn::Xxx": ...}`, or bare `{"Ref": ...}` for `!Ref`) that
    `_walk_cfn_refs`/`_cfn_policy_documents` already understand --
    real CloudFormation templates overwhelmingly use the short form, and
    plain `yaml.safe_load` has no constructor for it at all (raises
    `ConstructorError` on the first `!GetAtt`/`!Ref`/etc. it sees,
    verified directly, not assumed)."""
    if isinstance(node, yaml.ScalarNode):
        value: object = loader.construct_scalar(node)
        if tag_suffix == "GetAtt" and isinstance(value, str):
            value = value.split(".", 1)
    elif isinstance(node, yaml.SequenceNode):
        value = loader.construct_sequence(node)
    elif isinstance(node, yaml.MappingNode):
        value = loader.construct_mapping(node)
    else:
        value = None
    key = "Ref" if tag_suffix == "Ref" else f"Fn::{tag_suffix}"
    return {key: value}


_CloudFormationLoader.add_multi_constructor("!", _cfn_tag_constructor)


def _cfn_policy_documents(properties: dict) -> list[dict]:
    docs: list[dict] = []
    single = properties.get("PolicyDocument")
    if isinstance(single, dict):
        docs.append(single)
    for policy in properties.get("Policies", []) or []:
        if isinstance(policy, dict) and isinstance(policy.get("PolicyDocument"), dict):
            docs.append(policy["PolicyDocument"])
    return docs


def parse_cloudformation(text: str, normalized_path: str) -> CloudParseResult:
    if normalized_path.endswith(".json"):
        template = json.loads(text)
    else:
        template = yaml.load(text, Loader=_CloudFormationLoader)

    cfn_resources = template.get("Resources") or {}

    # CloudFormation's `Ref`/`Fn::GetAtt` targets are bare logical IDs --
    # they carry no type information of their own (unlike Terraform's
    # `type.name` reference syntax). Resolving a reference's real address
    # needs the *target's* type, not the referencing resource's, so this
    # map is built first, in its own pass, before any reference is
    # recorded below.
    logical_id_to_type = {
        logical_id: definition.get("Type", "Unknown")
        for logical_id, definition in cfn_resources.items()
        if isinstance(definition, dict)
    }

    resources: list[CloudResource] = []
    references: list[tuple[str, str]] = []
    grants: list[Grant] = []

    for logical_id, definition in cfn_resources.items():
        if not isinstance(definition, dict):
            continue
        resource_type = definition.get("Type", "Unknown")
        properties = definition.get("Properties") or {}
        resource = CloudResource(
            file=normalized_path,
            resource_type=resource_type,
            resource_name=logical_id,
            provider="cloudformation",
            attributes=properties,
        )
        resources.append(resource)
        for target_logical_id in _walk_cfn_refs(properties):
            target_type = logical_id_to_type.get(target_logical_id)
            if target_type is None:
                # Points outside this template's own Resources section
                # (a pseudo-parameter, an imported value, a typo) --
                # skipped rather than recorded with a fabricated type.
                continue
            references.append((resource.address, f"{target_type}.{target_logical_id}"))

        if resource_type in ("AWS::IAM::Policy", "AWS::IAM::Role", "AWS::IAM::ManagedPolicy"):
            for doc in _cfn_policy_documents(properties):
                grants.extend(statements_to_grants(doc, principal=resource.address, source_file=normalized_path))

    return CloudParseResult(resources=resources, references=references, grants=grants)


# Well-known fields that reference another Kubernetes object by name --
# Kubernetes manifests don't have Terraform-style interpolation syntax to
# generically scan, so reference extraction here is a fixed, documented
# set of fields rather than a full expression walk. Each maps to the
# *target's own kind* -- unlike serviceAccountName (always a
# ServiceAccount), roleRef's target kind varies (Role or ClusterRole) and
# is given by roleRef.kind itself, not assumed.
_K8S_SERVICE_ACCOUNT_REFERENCE_PATHS = (
    ("spec", "serviceAccountName"),
    ("spec", "template", "spec", "serviceAccountName"),
)


def _get_nested(doc: dict, path: tuple[str, ...]) -> str | None:
    current: Any = doc
    for key in path:
        if not isinstance(current, dict) or key not in current:
            return None
        current = current[key]
    return current if isinstance(current, str) else None


def parse_kubernetes(text: str, normalized_path: str) -> CloudParseResult:
    resources: list[CloudResource] = []
    references: list[tuple[str, str]] = []

    for doc in yaml.safe_load_all(text):
        if not isinstance(doc, dict) or not doc.get("kind"):
            continue
        kind = doc["kind"]
        name = (doc.get("metadata") or {}).get("name", "unnamed")
        resource = CloudResource(
            file=normalized_path,
            resource_type=kind,
            resource_name=name,
            provider="kubernetes",
            attributes=doc,
        )
        resources.append(resource)

        for path in _K8S_SERVICE_ACCOUNT_REFERENCE_PATHS:
            target = _get_nested(doc, path)
            if target:
                references.append((resource.address, f"ServiceAccount.{target}"))

        role_ref = doc.get("roleRef")
        if isinstance(role_ref, dict) and isinstance(role_ref.get("name"), str):
            role_ref_kind = role_ref.get("kind", "Role")
            references.append((resource.address, f"{role_ref_kind}.{role_ref['name']}"))

        for subject in (doc.get("subjects") or []):
            if isinstance(subject, dict) and isinstance(subject.get("name"), str):
                kind_ref = subject.get("kind", "ServiceAccount")
                references.append((resource.address, f"{kind_ref}.{subject['name']}"))

    return CloudParseResult(resources=resources, references=references)


def parse_iac_file(path: Path, normalized_path: str, kind: str) -> CloudParseResult:
    if kind == "terraform":
        return parse_terraform(path, normalized_path)
    text = path.read_text(encoding="utf-8")
    if kind == "cloudformation":
        return parse_cloudformation(text, normalized_path)
    if kind == "kubernetes":
        return parse_kubernetes(text, normalized_path)
    raise ValueError(f"parse_iac_file doesn't handle kind={kind!r} -- use foundry.cloud.iam_parser for iam-policy files")
