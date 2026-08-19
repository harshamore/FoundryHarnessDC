"""LangChain tool wrappers around CloudResourceStore -- read-only, same
pattern as `foundry.indexer.tools`. First real caller is Phase 8's
exploitability-mapper subagent (`foundry.agents.exploitability_mapper`),
alongside `foundry.cloud.exploitability_tools`'s finding-list and
write tool.
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

    @tool
    def get_exposure(address: str) -> str:
        """Phase 7's deterministic exposure fact for a resource: is it
        network-reachable, and why/why not. Always available once an
        assessment has run -- every parsed resource gets a fact, even a
        "not exposed" one with an honest reason."""
        fact = store.get_exposure(address)
        if fact is None:
            return f"No exposure fact recorded for '{address}' (it may not be a known resource)."
        return f"{address}: {'exposed' if fact.is_exposed else 'not exposed'} -- {fact.reason}"

    @tool
    def get_reachability(address: str) -> str:
        """Phase 7's deterministic reachability edges *from* this
        resource: what its attached identity's grants let it reach, and
        which known cloud resource (if any) each grant's resource
        pattern was confidently matched against. An empty result is
        honest -- it means no attached identity's grants were found, not
        that reachability wasn't checked."""
        edges = store.list_reachability(from_address=address)
        if not edges:
            return f"'{address}' has no recorded reachability edges."
        lines = [
            f"via {e.principal}: {', '.join(e.actions)} on {e.resource_pattern}"
            + (f" (matches known resource {e.matched_resource})" if e.matched_resource else " (no known resource matched)")
            for e in edges
        ]
        return "\n".join(lines)

    return [
        list_cloud_resources,
        get_cloud_resource,
        get_cloud_references,
        get_grants,
        get_exposure,
        get_reachability,
    ]
