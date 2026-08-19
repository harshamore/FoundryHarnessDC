"""Phase 6 proofs: CloudResourceStore (src/foundry/cloud/store.py) --
write/read round-tripping, and Constitution XI's "delete-then-insert
scoped to one file, inside one transaction" behavior, same as
IndexStore.write_index already proves for the code index.
"""
from __future__ import annotations

from pathlib import Path

import pytest

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
