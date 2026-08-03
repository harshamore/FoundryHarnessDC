# Architecture

This is a **scaffold**: role interfaces, guardrail definitions, and
finding-lifecycle data models, with no detection/triage/validation logic
implemented. It follows Cisco's [Foundry Security
Spec](https://github.com/CiscoDevNet/foundry-security-spec) (`SEED`
v0.1.0), reproduced unmodified in this repo at `specs/001-foundry/spec.md`
and `.specify/memory/constitution.md`.

## Shape

A fleet of role-specialized agents, coordinated through a shared
substrate, supervised by an Orchestrator, operating on a target within a
sandbox. The operator talks to one surface — the Orchestrator — for both
lifecycle control and conversational access.

```
                                   OPERATOR
                                      │
                       ┌──────────────▼──────────────┐
                       │        ORCHESTRATOR         │
                       │  lifecycle: validate ·      │
                       │  spawn · maintain · status  │
                       │  converse: Q&A · steer ·    │
                       │  queue tasks · help reqs    │
                       └──────────────┬──────────────┘
                                      │
                       ══════════ SUBSTRATE ══════════
                        work queue · finding store ·
                        sandbox · budget · dashboard
                       ══════════════╤════════════════
                                     │
       knowledge layer               │   finding pipeline                  oversight
   ┌─────────┬─────────┐             │ ┌────────┬────────┬─────────┐   ┌────────┬─────────┐
   ▼         ▼         │             │ ▼        ▼        ▼         │   ▼        ▼         │
┌───────┐┌─────────┐   │           ┌────────┐┌────────┐┌─────────┐ │┌────────┐┌─────────┐ │
│INDEXER││ CARTO-  │───┘           │DETECTOR││TRIAGER ││VALIDATOR│ ││REPORTER││COVERAGE │ │
│       ││ GRAPHER │               │        ││        ││         │ ││        ││ GUIDE   │ │
└───┬───┘└────┬────┘               └───┬────┘└───┬────┘└────┬────┘ │└───▲────┘└────┬────┘ │
    └─────────┴─── feeds every ────────┘         │          │      │    │          │      │
              role below             candidates  verdicts  exploited    │       done?     │
                                         └───────────┴────────┴─────────┴──────────┴──────┘
```

(Diagram reproduced from spec.md §4.1. Arrows show the *primary* data
flow only — every role reads and writes the substrate, and any role may
queue work for any other.)

## Repo layout

```
src/foundry_harness/
  agents/
    base.py            AgentRole ABC — every role's common shape
    orchestrator.py     §5.1  (two facets: lifecycle + conversational)
    indexer.py          §5.2  (gates the rest of the fleet)
    cartographer.py      §5.3
    detector.py           §5.4  (rule sweep + exploratory hunting)
    triager.py             §5.5  (the evidence-gate enforcer)
    validator.py             §5.6  (independent exploit reproduction)
    coverage_guide.py          §5.7  (half of the "done" signal)
    reporter.py                   §5.8  (only true-positive ever ships)
    extensions/            §6 — Deep-Tester, Variant-Hunter, Attack-Mapper,
                            Remediator, Self-Improver. Build after the
                            core eight are trustworthy, per upstream README.
  guardrails/
    constitution.py    the 11 inviolable principles, as data
  models/
    finding.py          Finding Lifecycle: Verdict, EvidenceGate,
                         Fingerprint, ProvenanceEvent, Finding
  orchestration/
    substrate.py        Protocol contracts (WorkQueue, FindingStore,
                         Sandbox, BudgetGovernor, Dashboard, ...) —
                         behavior only, no concrete backing store
.specify/memory/constitution.md   upstream, unmodified (spec-kit convention)
specs/001-foundry/spec.md         upstream, unmodified (spec-kit convention)
```

## The eight core roles, why this decomposition

Each role exists because the previous role has a distinct failure mode
the next role catches (spec.md §4.2):

- Indexing without cartography gives agents structure with no security
  context.
- Detection without triage produces noise (Constitution II).
- Triage without validation produces plausible-sounding fiction
  (Constitution VII).
- Validation without coverage produces a pile of confirmed bugs with no
  claim to completeness (Constitution VI).
- Reporting without a conversational interface produces a wall of text
  the operator cannot interrogate.

Merging roles was tried repeatedly in the upstream production system; the
merged role's quality consistently drifted toward the weaker of the two.

## Finding Lifecycle (§7)

```
  candidate ──triage──► verdict assigned ──┬─TP─► confirmed ──validate──► confirmed[exploited?] ──report──► published
                                            └─FP/NA/CQ/NR─► recorded (internal only, never published)
```

- **Verdicts** (`Verdict`): `true-positive`, `false-positive`,
  `needs-review`, `not-applicable`, `code-quality`. Exactly one per
  triaged finding; mutable (re-triage replaces, doesn't duplicate).
- **Evidence gate** (`EvidenceGate`, §7.3): a `true-positive` verdict
  requires three cited, mechanically-resolved code locations —
  reachability, trust boundary, impact. This is Constitution I in data
  form.
- **Exploited** (`ExploitationRecord`): set only by the Validator, only
  after independent clean-room reproduction. Never inferred, never
  self-graded (Constitution VII).
- **Fingerprint** (`Fingerprint`): identity keyed on
  `(normalized_path, symbol, vulnerability_class)` — explicitly *not*
  line numbers or snippets, so re-runs after unrelated edits don't re-file
  everything as new (Constitution VIII).

See `src/foundry_harness/models/finding.py` for the full model, including
the `FR-052` / `FR-089` validators that make these invariants structural
rather than aspirational.

## What's deliberately not built yet

Per the upstream spec's own instruction ("do not implement directly from
this file"), this scaffold does not resolve any of the ~30
`[NEEDS CLARIFICATION: ...]` markers in `spec.md` — system name, which
LLM provider, which datastore, which issue tracker, severity scheme,
weakness taxonomy, whether a testbed exists, extension-role scope, and
so on. See `docs/INTEGRATION.md` for how those get resolved before any
role's `run()` stops raising `NotImplementedError`.
