# Integration: spec-kit workflow and human-in-the-loop

## Why this matters

Cisco's Foundry Security Spec is explicitly a **seed**, not a
specification: "Do not implement directly from this file" (spec.md, top
banner). It is designed to be consumed by [GitHub's
spec-kit](https://github.com/github/spec-kit): you run it through a
clarification step that resolves ~30 organization-specific open
questions, and *your* spec comes out the other side. This scaffold is
architecture only — it exists so the roles and data shapes are visible
while that clarification work happens, not as a shortcut around it.

## Where this repo sits in the spec-kit workflow right now

The upstream README defines eight steps. Status of each in this repo:

| Step | What it is | Status here |
|---|---|---|
| 0. Read the constitution | Read `.specify/memory/constitution.md` end to end | Done — see `docs/ARCHITECTURE.md` and `guardrails/constitution.py` for the 11 principles in code form |
| 1. Install spec-kit | `.specify/` directory + `/speckit.*` commands in your agent | **Not done.** Requires installing the actual [spec-kit](https://github.com/github/spec-kit) tool into this project |
| 2. Install the constitution | Copy `constitution.md` to `.specify/memory/constitution.md`, run `/speckit.constitution` | File is in place; the `/speckit.constitution` registration step has not been run (depends on Step 1) |
| 3. Seed the specification | Copy `spec.md` to `specs/001-foundry/spec.md` | Done |
| 4. Clarify (`/speckit.clarify`) | Walk through every `[NEEDS CLARIFICATION: ...]` marker | **Not started.** ~30 open questions remain — see spec.md §15 for the full index |
| 5. Specify (`/speckit.specify`) | Harden the clarified seed into a `DRAFT` spec | Blocked on Step 4 |
| 6. Iterate clarify/specify to convergence | Repeat until no markers remain | Blocked on Step 4-5 |
| 7. Plan, task, implement | `/speckit.plan` → `/speckit.tasks` → `/speckit.implement` | Blocked on Step 6. This scaffold is a preview of shape, not a substitute for this step |

**Practical implication:** every `raise NotImplementedError` in
`src/foundry_harness/agents/*.py` should stay a stub until the
clarification questions that determine its real behavior are answered —
e.g. `Indexer` can't be implemented without answering "which languages"
(spec.md §5.2), `Detector.explore()` can't be implemented without
answering "is a testbed ever available" (§11.12), `Reporter.publish()`
can't be implemented without answering "which issue tracker" (§11.1) and
"which severity scheme" (§11.9/FR-077).

### High-priority clarification groups (from the upstream README)

1. **Identity & scope** — system name, does "authorized eval with source
   access" hold, merge/split/omit any of the eight core roles. Answer
   first; everything else depends on these.
2. **Integration choices** — VCS/issue tracker, LLM provider, datastore,
   deployment target, isolation runtime, agent harness, auth model.
3. **Policy choices** — severity scheme, weakness taxonomy, whether
   `needs-review` surfaces to humans, label naming, compliance mapping.
4. **Extension scope** — five yes/no questions for the roles in
   `agents/extensions/`. Upstream recommendation: **no to all five for
   the first build.**

## Human-in-the-loop as final arbiter

This is not a bolt-on policy — it's structural in the spec, enforced at
several independent layers:

- **Constitution X — "The Operator Outranks Every Agent."** Operator
  instructions are authoritative; peer-agent messages and prior-agent
  notes are hints only. An agent does not abandon its task because a
  peer suggested otherwise, and does not treat a prior agent's "this is
  fully covered" note as fact. See `guardrails/constitution.py`.
- **NFR-009 (Operator override).** Every automated decision — verdict,
  `exploited`, coverage-complete, auto-stop — is overridable by the
  operator, and the override is recorded, never silently applied.
- **FR-018.** The Orchestrator's conversational facet
  (`agents/orchestrator.py::OrchestratorConversationalFacet`) MUST NOT
  modify verdicts, set `exploited`, or mark coverage complete on its own
  initiative — only on explicit operator instruction.
- **Constitution "Scope of authority" (Governance section).** The
  constitution constrains the *system's design*. It does not constrain
  the *operator's runtime decisions*: an operator may override any
  automated verdict, stop a run early, or disable a role. The system
  records the override; it does not refuse it.
- **FR-102 / FR-102a-d (Inter-agent communication).** Peer messages are
  delivered as advisory and must be treated as hints, not commands —
  this is what stops the "agent consensus" failure mode Constitution X
  names directly: agents talking each other into believing an evaluation
  is done. Agent → operator messages are one-way and never block on a
  reply, so the fleet keeps moving while surfacing what needs a human.
- **FR-016 (Steering).** The operator can interrupt a running agent
  disruptively or non-disruptively at any time.
- **Extension role `Remediator` (§6.4)** never auto-applies a patch —
  output is always a proposal for human review, by explicit spec
  language, not by our inference.

In short: nothing in this architecture is designed to let the system
decide, on its own, that a vulnerability is real, that it's fixed, or
that the evaluation is finished. Those are recorded conclusions the
system reaches and a human can always override — never irreversible
actions the system takes unilaterally.

## Working with the upstream spec repository

While researching this scaffold, a local security hook (DefenseClaw)
flagged the upstream repository's `AGENTS.md` file as a match for a known
prompt-injection signature (`COG-AGENTS-MD`). We did not open that file's
contents, and it is deliberately **not** copied into this repo — only
`spec.md` and `constitution.md` were pulled in, and both were reviewed
before use.

This is a general caution worth keeping as this project evolves: when
pulling any third-party spec, rule corpus (e.g. CodeGuard content), or
`AGENTS.md`/`CLAUDE.md`-style file into a repo that coding agents will
read, review it first. Per Constitution IX and NFR-010, this harness's
own sandbox is designed to enforce boundaries by infrastructure, not by
trusting prompt content — the same caution applies to us as the harness's
builders, not just to the agents it will eventually run.
