"""LangChain tool wrappers around CloudResourceStore -- read-only, same
pattern as `foundry.indexer.tools`. Not yet bound to any subagent (Phase
6 is ingestion only); Phase 8's exploitability-mapper subagent is the
first real caller.
"""
from __future__ import annotations

from langchain_core.tools import BaseTool, tool

from foundry.cloud.store import CloudResourceStore


def build_cloud_tools(store: CloudResourceStore) -> list[BaseTool]:
    @tool
    def list_cloud_resources(file: str | None = None) -> str:
        """List every parsed IaC/IAM resource (Terraform/CloudFormation/
        Kubernetes/standalone IAM policy), optionally narrowed to one
        file. Returns each resource's address (`type.name`) and provider."""
        resources = store.list_resources(file=file)
        if not resources:
            return f"No cloud resources indexed in {file}." if file else "No cloud resources indexed."
        return "\n".join(f"{r.address} ({r.provider})" for r in resources)

    @tool
    def get_cloud_resource(address: str) -> str:
        """Look up one cloud resource by its address (`type.name`, e.g.
        `aws_lambda_function.process_upload`) and return its parsed
        attributes."""
        resource = store.get_resource(address)
        if resource is None:
            return f"No cloud resource with address '{address}'."
        return f"{resource.address} ({resource.provider}, file={resource.file}): {resource.attributes}"

    @tool
    def get_cloud_references(address: str) -> str:
        """List every resource address this resource references (e.g. an
        attached IAM role, a referenced service account)."""
        refs = store.list_references(from_address=address)
        if not refs:
            return f"'{address}' has no recorded references."
        return ", ".join(to_address for _, to_address in refs)

    @tool
    def get_grants(principal: str) -> str:
        """List every IAM grant attached to `principal` (a resource
        address, e.g. an IAM role or policy) -- effect, actions, and
        resources for each statement."""
        grants = store.list_grants(principal=principal)
        if not grants:
            return f"No grants recorded for '{principal}'."
        lines = [f"{g.effect} {', '.join(g.actions)} on {', '.join(g.resources)}" for g in grants]
        return "\n".join(lines)

    return [list_cloud_resources, get_cloud_resource, get_cloud_references, get_grants]
