# Exploitability classification across code, IaC, and IAM (Phases 6-8)

## What this is, and its scope

Application code vulnerability detection has been real since Phase 1. This second initiative answers a different question, per finding: not just "is this a real vulnerability" (already answered by Detector/Triager/the evidence gate) but **"is it actually exploitable in this specific deployment"** -- a SQL injection in a function that's never network-reachable, or reachable but running under an identity with no meaningful permissions, is a real code smell but not a real-world risk *right now*; the same vulnerability in an exposed function running under an over-permissioned role is. Three phases:

- **Phase 6 -- ingestion**: parse Terraform/CloudFormation/Kubernetes/IAM into a queryable store (the infra-domain equivalent of the Indexer).
- **Phase 7 -- exposure & governance analysis**: for each parsed resource, deterministically compute whether it's network-exposed, and what its attached identity's grants actually reach.
- **Phase 8 -- exploitability classification**: correlate confirmed findings to that graph, classifying each as **exploitable** (exposed + real onward impact), **contained** (a real vulnerability, but governance currently blocks it), or **not correlated** (the harness couldn't confidently map the code to any specific infra -- reported honestly, never guessed).

**Scope decision, made explicitly with the user:** this is reasoned, evidence-gated *static* analysis -- correlating already-parsed facts -- not real dynamic exploitation against a live environment. No exploit code is ever written or run.

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

## Phase 6: known, documented limitations (not silent gaps)

- **Terraform's `jsonencode(...)` is not evaluated.** `python-hcl2` leaves function-call expressions as opaque strings; a `policy` attribute only becomes `Grant`s when it's a literal JSON string or heredoc (`policy = <<-POLICY ... POLICY`). A `jsonencode()`-authored inline policy parses as a resource with zero grants extracted -- not an error, not a fabricated grant. Standalone IAM policy JSON files don't have this limitation.
- **`python-hcl2` is pinned `>=4.3,<5`.** Versions 5.x-8.x wrap every scalar value in extra escaped quote characters and add an internal `__is_block__` marker to every block dict -- verified directly against a real parse, not assumed from the package's docs. Every parser in `foundry/cloud/` is written against 4.3.x's plain-dict output.
- **CloudFormation's short-form intrinsic tags** (`!Ref`, `!GetAtt`, `!Sub`, ...) need a dedicated `yaml.SafeLoader` subclass (`_CloudFormationLoader` in `iac_parser.py`) -- plain `yaml.safe_load` has no constructor for them at all and raises `ConstructorError` on the first one it sees. Scoped to a subclass, not a monkeypatch of `yaml.SafeLoader` itself, since Kubernetes parsing and `detect.py`'s own sniffing both also call plain `yaml.safe_load(_all)` in this same process.
- **CloudFormation reference resolution is two-pass.** `Ref`/`Fn::GetAtt` targets are bare logical IDs with no type information of their own -- resolving a reference's real address needs a first pass over the template's own `Resources` section to build a logical-ID-to-type map, *before* any reference is recorded. (An earlier version of this code wrongly prefixed every reference target with the *referencing* resource's own type; caught before shipping by a test using two different resource types referencing each other.)
- **Kubernetes reference extraction is a fixed field list**, not a generic scan (`serviceAccountName`, `roleRef` (using `roleRef.kind` for the target's own kind, not assumed to be a ServiceAccount), `subjects[]`) -- Kubernetes manifests don't have Terraform-style interpolation syntax to walk generically.

## Phase 7: deterministic exposure & governance analysis

Purely about the infra side, independent of any specific code finding -- no LLM, no code correlation.

- `foundry.cloud.exposure.classify_all_exposure`: a pragmatic, growing rule set (like CodeGuard's own rule corpus) classifying each resource as exposed or not, with an honest reason either way. A resource type with no rule reports not-exposed with "no known public-exposure signal for this resource type" -- never guessed. Current rules: security groups with `0.0.0.0/0` ingress, S3 buckets with a disabling `aws_s3_bucket_public_access_block` or a public ACL, Lambda functions with a public Function URL (`authorization_type = "NONE"`), Kubernetes `Service`s of type `LoadBalancer`/`NodePort` or referenced by an `Ingress`.
- `foundry.cloud.graph.compute_reachability`: given the reference graph Phase 6 extracted, walks from a resource to its attached identity, then to that identity's grants -- a real, bounded BFS. Handles the actual shape Terraform/CloudFormation both produce: a grant is usually attached to a *separate* policy resource that itself references the role (`aws_iam_role_policy.x -> aws_iam_role.y`, `principal=aws_iam_role_policy.x`), not to the role's own address -- reaching a role's real grants means checking both the role's address and every resource that references it. Identity/policy-*definition* resource types (`aws_iam_role`, `aws_iam_role_policy`, `iam-policy`, ...) are never themselves treated as a workload to compute reachability *from* -- an earlier version let a policy resource walk its own attached grant as a circular "self-reaches" edge, caught by a test before shipping.
- **ARN construction for `matched_resource` is real but narrow** (`_guess_arn` in `graph.py`, currently S3 buckets only) -- a grant's resource pattern (`arn:aws:s3:::prod-*`) is fnmatch-matched against every known resource's guessed ARN. A resource type with no ARN-construction rule never gets a fabricated match, the same honest-default discipline as exposure classification. Broader provider/resource-type coverage is additive later.
- Both persist into `CloudResourceStore` as whole-graph-replace tables (`cloud_exposure`, `cloud_reachability`) -- recomputed from scratch every run rather than incrementally, since they're cheap pure functions over already-indexed data.

## Phase 8: exploitability classification

The step that actually answers "exploitable, contained, or not correlated" per finding.

- New role `foundry.agents.exploitability_mapper.build_exploitability_mapper_subagent` -- reads confirmed `true-positive` findings, parsed cloud resources, and Phase 7's exposure/reachability facts (via `foundry.cloud.tools.build_cloud_tools`'s `get_exposure`/`get_reachability`, and `foundry.cloud.exploitability_tools.build_exploitability_tools`'s `list_confirmed_findings`/`classify_exploitability`).
- **Correlation is evidence-gated, and allowed to say "unknown."** Mapping a code finding (file + symbol) to the specific cloud resource that runs it is genuinely imprecise -- Terraform/Kubernetes reference a deployment unit (a `source_dir`, a container image), not a source line. `ExploitabilityStore.classify()` (`foundry.cloud.exploitability`) enforces the actual rules structurally, the same "resolver you can't fake" shape `FindingStore.assign_verdict` already established: the finding must be real and `true-positive` (checked directly against the `findings` table -- the same "any store on this connection may read another store's table" precedent `ReporterStore.publish_finding_report` already uses); `exploitable`/`contained` both require a real, already-indexed `correlated_resource` (you can't say a finding is exposed-and-reachable, or contained by governance, without naming *which* resource that applies to); `not_correlated` must *not* name one.
- `ReporterStore.build_ciso_report` gained an optional `exploitability_store` parameter (backward compatible -- omitted, the report is identical to Phase 5's) that adds an "## Exploitability" section grouping published findings by classification, exploitable first with their evidence, contained and not-correlated (and unclassified, if the mapper never reached a finding) shown too, never silently dropped.
- Wired into `run_assessment` (`AssessmentConfig.run_exploitability_agent`, default `True`) right after the detect/triage loop stops and before the final report step.

## Fixture

`data/cloud_toy_target/` (Terraform + a standalone IAM policy + a Kubernetes manifest, plus a self-contained vulnerable Lambda handler) is one coherent scenario spanning all three phases: an S3 bucket exposed via a disabled public-access block, a Lambda with a public Function URL and a SQL-injection vulnerability in its own code, an inline IAM policy granting it broad `s3:*`/`dynamodb:*` on `prod-*` (plus a pattern that genuinely matches the toy bucket, so `matched_resource` has a real positive case to test against) attached via the real Terraform `aws_iam_role_policy` role-reference shape, and a standalone IAM policy file deliberately left unattached to anything -- demonstrating the honest "not correlated" outcome, not a hand-picked happy path only.

## Install

```sh
pip install -e ".[dev,api,cloud]"
```

`python-hcl2` is its own extra, same pattern as `[observability]`/`[api]` -- `foundry.cloud.iac_parser` imports it lazily, inside `parse_terraform` itself, not at module load time, since `foundry.orchestration.assessment` (a core, always-imported module) imports from this file unconditionally; a top-level `import hcl2` there would have broken the *entire* harness for anyone who installed without `[cloud]`. CloudFormation/Kubernetes/IAM parsing, and all of Phase 7/8, need nothing beyond the base install.
