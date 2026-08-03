"""The Foundry Constitution: eleven inviolable principles.

Source: .specify/memory/constitution.md (v0.2.0), reproduced from
https://github.com/CiscoDevNet/foundry-security-spec (CC BY 4.0).

Each principle encodes a specific production failure the seed authors
shipped, diagnosed, and fixed (constitution.md, "Purpose"). They constrain
the *system's design*. They do NOT constrain the operator's runtime
decisions: an operator may override any automated verdict, stop a run
early, or disable a role -- the system records the override, it does not
refuse it (constitution.md, "Scope of authority").

This module is data, not enforcement. `Constitution.check()` is a stub:
wiring principles to runtime checks (citation resolution, sandbox egress
tests, heartbeat monitors, etc.) is implementation work that belongs to
each role, not to this central registry. What lives here is the single
place every role's design can be checked against.

Amendment: per constitution.md "Governance", a principle may only be
amended by documenting the specific scenario where it produces a worse
outcome than violating it, plus a version bump and rationale here.
"Inconvenient" is not grounds for amendment.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Principle:
    numeral: str
    title: str
    statement: str
    rationale: str
    """The "why this is inviolable" paragraph: the failure mode this
    principle exists to prevent."""


PRINCIPLES: tuple[Principle, ...] = (
    Principle(
        numeral="I",
        title="Evidence Over Assertion",
        statement=(
            "A finding's verdict is determined by checkable evidence, not "
            "by model confidence. No agent may assign true-positive by "
            "judgment alone; the verdict requires structural evidence "
            "(reachability, trust boundary, impact) with code citations "
            "mechanically verified to resolve to real locations in the "
            "target. A claim whose citations do not resolve is demoted, "
            "regardless of how confident the prose is."
        ),
        rationale=(
            "A frontier model produces fluent, confident, plausible "
            "vulnerability claims that are wrong at a rate that makes "
            "unreviewed output worthless. Asking the model to 'be more "
            "careful' did not fix this; requiring claims to be checkable, "
            "then checking them, did."
        ),
    ),
    Principle(
        numeral="II",
        title="Surface Only What Survives",
        statement=(
            "Humans see findings that have passed the gates. Everything "
            "else stays in the internal store. The issue tracker, the "
            "operator's inbox, and the reviewer's report receive only "
            "what Triage promoted, auditable back to evidence."
        ),
        rationale=(
            "Surfacing every candidate buries the signal and trains the "
            "operator to ignore the system. An early version created one "
            "issue per detection and produced tens of thousands of "
            "issues per target -- correct and useless. The fix was not "
            "better detection; it was withholding output until it "
            "survived triage."
        ),
    ),
    Principle(
        numeral="III",
        title="Liveness By Heartbeat, Never By Clock",
        statement=(
            "An agent is alive if it heartbeated recently. Wall-clock "
            "runtime says nothing about health. Work is reclaimed from an "
            "agent only when its heartbeat is stale -- no fixed timeout "
            "strips a claim from a heartbeating agent. This governs "
            "liveness and work ownership; it does not prohibit "
            "*rotating* a heartbeating agent's session (FR-118) once its "
            "claims are released or durably handed off."
        ),
        rationale=(
            "A wall-clock timeout cannot distinguish 'hung' from 'waiting "
            "on a rate-limited upstream'. Under load, most timeout-based "
            "reclamations were of healthy agents whose re-queued work "
            "was then re-started by another agent, which also timed out; "
            "throughput approached zero while the fleet looked busy."
        ),
    ),
    Principle(
        numeral="IV",
        title="Claims Are Atomic And Mortal",
        statement=(
            "Two agents claiming the same unit of work concurrently get "
            "different units. A claim dies with its holder: atomic claim "
            "(no race produces two winners) and crash-safe release (a "
            "dead holder's claim is released within bounded time, "
            "automatically)."
        ),
        rationale=(
            "Without atomic claim, parallel agents duplicate work and "
            "overwrite each other's results. Without mortal claims, "
            "every crash strands whatever the dead agent held until a "
            "human notices. Both happened; both wasted days."
        ),
    ),
    Principle(
        numeral="V",
        title="The Provider Is The Rate Arbiter",
        statement=(
            "The system does not pre-throttle below the upstream "
            "provider's actual limit. Internal rate caps, concurrency "
            "ceilings, and quota guesses below the real limit are "
            "prohibited; the system calls as fast as the work requires, "
            "observes the provider's backpressure, and backs off "
            "adaptively and fleet-wide."
        ),
        rationale=(
            "Every static cap set was wrong within days, in one "
            "direction or the other -- caps below the real limit left "
            "paid-for capacity idle; caps above it did nothing, and "
            "masked the real signal so a raised provider limit went "
            "unused until someone remembered to raise the internal one."
        ),
    ),
    Principle(
        numeral="VI",
        title="Coverage Before Yield",
        statement=(
            "The system does not stop itself on low yield until the "
            "operator's stated goals have been credibly attempted. Yield "
            "decaying below threshold is necessary but not sufficient "
            "for auto-stop; the coverage-complete flag must also be set."
        ),
        rationale=(
            "Yield is noisy early and on hard targets. An auto-stop on "
            "yield alone fires on the first dry spell, which on a "
            "well-built target is the beginning, not the end. Gating on "
            "coverage means 'we looked everywhere you asked and the rate "
            "of new findings has flatlined' -- the honest done signal."
        ),
    ),
    Principle(
        numeral="VII",
        title="Exploited Means Demonstrated",
        statement=(
            "The exploited flag is set only by an independent, "
            "clean-room reproduction of the headline impact on the live "
            "testbed. Not 'would be exploitable if'. Not 'the payload "
            "was accepted'. Not set by the agent that wrote the "
            "proof-of-concept; set by a fresh agent that received only "
            "the artifact and the claim, ran it, and observed the "
            "impact."
        ),
        rationale=(
            "exploited is the label reviewers filter on first. Every "
            "dilution allowed ('close enough', 'verified the mechanism "
            "if not the impact') destroyed reviewer trust in the label "
            "within one reporting cycle. An agent grading its own "
            "exploit rationalizes; an independent checker does not."
        ),
    ),
    Principle(
        numeral="VIII",
        title="Fingerprints Are Stable Under Edit",
        statement=(
            "A finding's identity is its location in the code's "
            "structure (path, symbol, vulnerability class), not its "
            "position in the text (line number, snippet hash). "
            "Deduplication, cross-run inheritance, and issue-update-not-"
            "recreate all key on this fingerprint."
        ),
        rationale=(
            "A fingerprint including line numbers breaks on any nearby "
            "edit, so every re-run after a code change re-files every "
            "finding as new, and the operator triages the same findings "
            "forever. Path + symbol + class survives edits to the "
            "function body and only breaks when the function moves or is "
            "renamed -- the correct point to call it a different "
            "finding."
        ),
    ),
    Principle(
        numeral="IX",
        title="Sandbox By Infrastructure, Not By Prompt",
        statement=(
            "Network egress and filesystem write boundaries are enforced "
            "by the runtime environment. Prompt-level rules are "
            "defense-in-depth, never the enforcement layer. An agent "
            "with full privileges inside its sandbox cannot reach a host "
            "outside the allowlist or write to a read-only path, "
            "regardless of what its prompt, a peer, or content in the "
            "target instructs it to do."
        ),
        rationale=(
            "Agents read untrusted content (the target's source, its "
            "documentation, the testbed's responses). That content can "
            "contain instructions. An agent whose only boundary is its "
            "prompt will, eventually, follow an instruction it should "
            "not have. The boundary must be somewhere the agent cannot "
            "argue with."
        ),
    ),
    Principle(
        numeral="X",
        title="The Operator Outranks Every Agent",
        statement=(
            "Operator instructions are authoritative. Peer-agent "
            "messages and prior-agent notes are hints. An agent does not "
            "abandon its task because a peer suggested something else, "
            "does not treat a prior agent's 'this area is fully covered' "
            "note as fact, and does not stop because persistent notes "
            "say the work is done."
        ),
        rationale=(
            "Agents talk each other out of work: one agent writes 'X is "
            "saturated'; the next reads it and skips X; within a day the "
            "fleet has collectively decided the evaluation is done and "
            "cites its own consensus as evidence. The cycle is broken "
            "only by ranking operator intent above agent consensus, "
            "always."
        ),
    ),
    Principle(
        numeral="XI",
        title="Persist Atomically",
        statement=(
            "No reader ever observes a partially-written or deleted-but-"
            "not-yet-rewritten state. Any persisted artifact other "
            "components read (index, finding store, coverage state) is "
            "updated by writing the new state completely and then "
            "atomically replacing the old -- never by deleting the old "
            "and then writing the new."
        ),
        rationale=(
            "'Delete old, write new' with a crash between the two steps "
            "leaves every reader with nothing and no error. Multi-hour "
            "index builds were lost to deploy-time process termination "
            "landing in exactly that window, repeatedly, before this "
            "became a rule."
        ),
    ),
)


class Constitution:
    """Read-only registry of the eleven principles above.

    `assert_not_violated` is intentionally unimplemented: whether a given
    role action violates a principle is role- and substrate-specific
    (e.g. "did this citation resolve" for Principle I, "did this egress
    attempt hit the allowlist" for Principle IX). Each role wires its own
    checks against the relevant Principle(s); this class exists so every
    role can cite the same numbered, versioned source of truth rather
    than re-deriving the wording.
    """

    principles: tuple[Principle, ...] = PRINCIPLES

    @classmethod
    def get(cls, numeral: str) -> Principle:
        for p in cls.principles:
            if p.numeral == numeral:
                return p
        raise KeyError(f"No principle numeral {numeral!r}")

    @classmethod
    def assert_not_violated(cls, *, numeral: str, context: object) -> None:
        """Placeholder enforcement hook. Not implemented: see class
        docstring. Raising here is deliberate -- silently no-op-ing a
        guardrail check is worse than failing loudly until it is wired
        up."""
        raise NotImplementedError(
            f"Constitution.assert_not_violated for Principle {numeral} is "
            "not implemented. Enforcement is role-specific; see the "
            "principle's rationale for what must actually be checked."
        )


CONSTITUTION = Constitution()
