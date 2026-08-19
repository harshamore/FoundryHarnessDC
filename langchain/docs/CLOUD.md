# IaC/IAM ingestion & structural indexing (Phase 6)

## What this is, and its scope

Application code vulnerability detection has been real since Phase 1. Phase 6 adds the first half of a second capability: understanding a target's *infrastructure* -- Terraform, CloudFormation, and Kubernetes manifests, plus IAM policy documents -- well enough to eventually say whether a code vulnerability is actually exploitable given the governance around it (that correlation is Phase 7/8, not built yet -- see `docs/ARCHITECTURE.md`'s phase list). Phase 6 on its own is ingestion: parsing this content into a queryable store, the infra-domain equivalent of what the Indexer already does for code.

**Before this phase, uploading IaC/IAM content was a complete no-op** -- confirmed directly in the code before scoping this work: only 6 file extensions were ever parsed into anything (`LANGUAGE_BY_EXTENSION`, `src/foundry/indexer/parser.py`), everything else landed in `TargetRepo.unsupported_files` and stayed there, and no agent has a tool path to read raw file content either (`minimal_filesystem_middleware` deliberately locks every subagent to Indexer query tools, not the filesystem). Terraform/CloudFormation/Kubernetes/IAM files were listed in the file tree and never analyzed.

## What's parsed, and how

| Format | Parser | Dependency |
|---|---|---|
| Terraform (`.tf`) | `foundry.cloud.iac_parser.parse_terraform` | `python-hcl2` (the `[cloud]` extra) |
| CloudFormation (`.yaml`/`.yml`/`.json`, content-sniffed) | `foundry.cloud.iac_parser.parse_cloudformation` | `pyyaml`/`json` (base deps) |
| Kubernetes manifests (`.yaml`/`.yml`, content-sniffed, multi-document) | `foundry.cloud.iac_parser.parse_kubernetes` | `pyyaml` (base dep) |
| IAM policy documents (`.json`, content-sniffed; bare or the `aws iam get-policy-version`-style wrapper) | `foundry.cloud.iam_parser.parse_iam_policy_file` | `json` (stdlib) |

Every parser produces the same `foundry.cloud.models.CloudParseResult` shape (`resources`, `references`, `grants`) -- the cloud-domain equivalent of `foundry.indexer.parser.IndexResult`'s `(functions, call_edges)`. `CloudResourceStore` (`foundry.cloud.store`) persists it with the exact same delete-then-insert-scoped-to-one-file transaction shape `IndexStore.write_index` already uses (Constitution XI).

**Detection is content-sniffed, not extension-based**, for everything except Terraform: `.yaml`/`.yml`/`.json` are used by CloudFormation, Kubernetes, IAM policies, *and* countless unrelated files (`package.json`, CI pipelines, docker-compose). `foundry.cloud.detect.detect_cloud_kind` reads and classifies content, failing closed (`None`) on anything that doesn't match a known shape or any read/parse error -- an unrecognized `.yaml` file stays in `unsupported_files` exactly as it did before this phase, not misclassified.

## Known, documented limitations (not silent gaps)

- **Terraform's `jsonencode(...)` is not evaluated.** `python-hcl2` leaves function-call expressions as opaque strings; a `policy` attribute only becomes `Grant`s when it's a literal JSON string or heredoc (`policy = <<-POLICY ... POLICY`). A `jsonencode()`-authored inline policy parses as a resource with zero grants extracted -- not an error, not a fabricated grant. Standalone IAM policy JSON files don't have this limitation.
- **`python-hcl2` is pinned `>=4.3,<5`.** Versions 5.x-8.x wrap every scalar value in extra escaped quote characters and add an internal `__is_block__` marker to every block dict -- verified directly against a real parse, not assumed from the package's docs. Every parser in `foundry/cloud/` is written against 4.3.x's plain-dict output.
- **CloudFormation's short-form intrinsic tags** (`!Ref`, `!GetAtt`, `!Sub`, ...) need a dedicated `yaml.SafeLoader` subclass (`_CloudFormationLoader` in `iac_parser.py`) -- plain `yaml.safe_load` has no constructor for them at all and raises `ConstructorError` on the first one it sees. Scoped to a subclass, not a monkeypatch of `yaml.SafeLoader` itself, since Kubernetes parsing and `detect.py`'s own sniffing both also call plain `yaml.safe_load(_all)` in this same process.
- **CloudFormation reference resolution is two-pass.** `Ref`/`Fn::GetAtt` targets are bare logical IDs with no type information of their own -- resolving a reference's real address needs a first pass over the template's own `Resources` section to build a logical-ID-to-type map, *before* any reference is recorded. (An earlier version of this code wrongly prefixed every reference target with the *referencing* resource's own type; caught before shipping by a test using two different resource types referencing each other.)
- **Kubernetes reference extraction is a fixed field list**, not a generic scan (`serviceAccountName`, `roleRef` (using `roleRef.kind` for the target's own kind, not assumed to be a ServiceAccount), `subjects[]`) -- Kubernetes manifests don't have Terraform-style interpolation syntax to walk generically.

## Install

```sh
pip install -e ".[dev,api,cloud]"
```

`python-hcl2` is its own extra, same pattern as `[observability]`/`[api]` -- `foundry.cloud.iac_parser` imports it lazily, inside `parse_terraform` itself, not at module load time, since `foundry.orchestration.assessment` (a core, always-imported module) imports from this file unconditionally; a top-level `import hcl2` there would have broken the *entire* harness for anyone who installed without `[cloud]`. CloudFormation/Kubernetes/IAM parsing need nothing beyond the base install.

## What's next (not built yet)

Phase 7 (deterministic exposure/governance analysis) and Phase 8 (correlating confirmed code findings to this infra graph, classifying each as exploitable/contained/not-correlated) are what actually make this data useful end to end -- see `docs/ARCHITECTURE.md`'s phase list for current status.
