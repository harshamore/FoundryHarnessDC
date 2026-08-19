"""Phase 6 proofs: CloudResourceStore (src/foundry/cloud/store.py) --
write/read round-tripping, and Constitution XI's "delete-then-insert
scoped to one file, inside one transaction" behavior, same as
IndexStore.write_index already proves for the code index.
"""
from __future__ import annotations

from pathlib import Path

import pytest

from foundry.cloud.exposure import ExposureFact
from foundry.cloud.graph import ReachabilityEdge
from foundry.cloud.models import CloudParseResult, CloudResource, Grant
from foundry.cloud.store import CloudResourceStore
from foundry.substrate.db import connect


@pytest.fixture
def store(tmp_path) -> CloudResourceStore:
    conn = connect(tmp_path / "cloud_store_test.sqlite3")
    return CloudResourceStore(conn)


def _sample_result(file: str) -> CloudParseResult:
    role = CloudResource(file=file, resource_type="aws_iam_role", resource_name="exec", provider="terraform", attributes={"name": "exec"})
    lambda_fn = CloudResource(
        file=file, resource_type="aws_lambda_function", resource_name="handler", provider="terraform", attributes={"role": "x"}
    )
    return CloudParseResult(
        resources=[role, lambda_fn],
        references=[(lambda_fn.address, role.address)],
        grants=[Grant(file=file, principal=role.address, effect="Allow", actions=["s3:*"], resources=["arn:aws:s3:::x"])],
    )


def test_write_and_list_resources_round_trips(store):
    store.write_resources("main.tf", _sample_result("main.tf"))
    resources = store.list_resources()
    assert {r.address for r in resources} == {"aws_iam_role.exec", "aws_lambda_function.handler"}


def test_list_resources_filters_by_file(store):
    store.write_resources("a.tf", _sample_result("a.tf"))
    store.write_resources("b.tf", _sample_result("b.tf"))
    assert len(store.list_resources(file="a.tf")) == 2
    assert len(store.list_resources()) == 4


def test_get_resource_by_address(store):
    store.write_resources("main.tf", _sample_result("main.tf"))
    resource = store.get_resource("aws_iam_role.exec")
    assert resource is not None
    assert resource.attributes == {"name": "exec"}


def test_get_resource_unknown_address_returns_none(store):
    assert store.get_resource("aws_iam_role.does_not_exist") is None


def test_list_references(store):
    store.write_resources("main.tf", _sample_result("main.tf"))
    refs = store.list_references(from_address="aws_lambda_function.handler")
    assert refs == [("aws_lambda_function.handler", "aws_iam_role.exec")]


def test_list_grants_by_principal(store):
    store.write_resources("main.tf", _sample_result("main.tf"))
    grants = store.list_grants(principal="aws_iam_role.exec")
    assert len(grants) == 1
    assert grants[0].actions == ["s3:*"]
    assert grants[0].resources == ["arn:aws:s3:::x"]


def test_rewriting_a_file_replaces_its_rows_not_accumulates(store):
    store.write_resources("main.tf", _sample_result("main.tf"))
    store.write_resources("main.tf", _sample_result("main.tf"))
    assert len(store.list_resources(file="main.tf")) == 2
    assert len(store.list_grants(principal="aws_iam_role.exec")) == 1


def test_writing_a_second_file_does_not_touch_the_first(store):
    store.write_resources("a.tf", _sample_result("a.tf"))
    store.write_resources("b.tf", _sample_result("b.tf"))
    store.write_resources("a.tf", CloudParseResult())  # a.tf now has nothing
    assert store.list_resources(file="a.tf") == []
    assert len(store.list_resources(file="b.tf")) == 2


# ---------------------------------------------------------------------------
# Phase 7: exposure/reachability persistence
# ---------------------------------------------------------------------------


def test_write_and_get_exposure_round_trips(store):
    store.write_exposure([ExposureFact(address="aws_s3_bucket.x", is_exposed=True, reason="public ACL")])
    fact = store.get_exposure("aws_s3_bucket.x")
    assert fact is not None
    assert fact.is_exposed is True
    assert fact.reason == "public ACL"


def test_get_exposure_for_unknown_address_returns_none(store):
    assert store.get_exposure("aws_s3_bucket.does_not_exist") is None


def test_write_exposure_replaces_the_whole_table(store):
    store.write_exposure([ExposureFact(address="a", is_exposed=True, reason="r1")])
    store.write_exposure([ExposureFact(address="b", is_exposed=False, reason="r2")])
    assert store.get_exposure("a") is None
    assert store.get_exposure("b") is not None


def test_write_and_list_reachability_round_trips(store):
    edge = ReachabilityEdge(
        from_address="aws_lambda_function.x", principal="aws_iam_role.y",
        actions=["s3:*"], resource_pattern="arn:aws:s3:::prod-*", matched_resource="aws_s3_bucket.z",
    )
    store.write_reachability([edge])
    edges = store.list_reachability(from_address="aws_lambda_function.x")
    assert len(edges) == 1
    assert edges[0].matched_resource == "aws_s3_bucket.z"
    assert edges[0].actions == ["s3:*"]


def test_write_reachability_replaces_the_whole_table(store):
    edge_a = ReachabilityEdge(from_address="a", principal="p", actions=[], resource_pattern="x", matched_resource=None)
    edge_b = ReachabilityEdge(from_address="b", principal="p", actions=[], resource_pattern="x", matched_resource=None)
    store.write_reachability([edge_a])
    store.write_reachability([edge_b])
    assert store.list_reachability(from_address="a") == []
    assert len(store.list_reachability(from_address="b")) == 1
