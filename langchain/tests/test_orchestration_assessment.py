"""Phase 2 proofs: run_assessment (src/foundry/orchestration/assessment.py)
-- the actual "index -> map -> detect -> triage -> check coverage ->
detect the gaps -> repeat -> report" sequence, run end to end. Indexing
and the loop's stop/continue decisions are real and deterministic
(no LLM); the concurrent Detector steps run through real DeepAgents graphs
driven by scripted fake models (same technique as
tests/test_orchestration_detection.py, reused here rather than duplicated).
Cartographer/Triager/Reporter agent calls are switched off for these tests
(`run_*_agent=False`) -- CoverageStore.evidence_for() counts a queued
candidate or a coverage-log sweep as evidence regardless of verdict, so
the loop's own termination logic is fully exercisable without them; those
three roles' own real-agent behavior is already covered by their own
modules' tests (test_cartographer.py, test_triager.py, test_reporter.py).
"""
from __future__ import annotations

from pathlib import Path

import pytest
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessage, SystemMessage, ToolMessage
from langchain_core.outputs import ChatGeneration, ChatResult

from foundry.indexer.store import IndexStore
from foundry.orchestration.assessment import AssessmentConfig, run_assessment
from foundry.substrate.budget import BudgetCaps
from foundry.substrate.db import connect
from foundry.target.repo import from_upload

REPO_ROOT = Path(__file__).resolve().parent.parent
TOY_TARGET = REPO_ROOT / "data" / "toy_target" / "vulnerable_app.py"


class CombinedDetectorFakeModel(BaseChatModel):
    """Drives all three Detector halves' real claim/tool-call loops --
    same decision shapes as DirectedWorkerFakeModel/
    BroadDetectionProbeFakeModel in test_orchestration_detection.py,
    combined into one model since run_assessment exercises all three
    within a single run. The directed half always completes what it
    claims (with a note, no candidate) -- proving FR-069's "coverage
    measures attempt, not outcome": the checklist closes via the
    coverage-log sweep alone, the same as a real directed pass that
    checks an area and genuinely finds nothing."""

    call_counter: int = 0
    normalized_path: str = ""

    def bind_tools(self, tools, **kwargs):
        return self

    def _next_id(self, prefix: str) -> str:
        self.call_counter += 1
        return f"{prefix}_{self.call_counter}"

    def _decide(self, messages) -> AIMessage:
        sys_text = " ".join(str(m.content) for m in messages if isinstance(m, SystemMessage))
        last = messages[-1]

        if "role's directed half" in sys_text:
            if isinstance(last, ToolMessage):
                text = str(last.content)
                if text.startswith("No directed tasks available"):
                    return AIMessage(content="All directed tasks processed.")
                if text.startswith("task_id="):
                    task_id = int(text.split("task_id=")[1].split(" ")[0])
                    return AIMessage(
                        content="",
                        tool_calls=[
                            {
                                "name": "complete_directed_task",
                                "args": {"task_id": task_id, "note": "checked, nothing found"},
                                "id": self._next_id("complete"),
                            }
                        ],
                    )
                if "completed" in text.lower():
                    return AIMessage(content="", tool_calls=[{"name": "claim_directed_task", "args": {}, "id": self._next_id("claim")}])
            return AIMessage(content="", tool_calls=[{"name": "claim_directed_task", "args": {}, "id": self._next_id("claim")}])

        if "role's rule-sweep half" in sys_text or "role's exploratory half" in sys_text:
            if isinstance(last, ToolMessage):
                return AIMessage(content=f"queued: {last.content}")
            # Queues something, but never a symbol/class matching any real
            # checklist item -- broad detection alone must never be enough
            # to close the checklist in these tests; only the directed loop
            # (via record_sweep) can.
            is_rule_sweep = "role's rule-sweep half" in sys_text
            symbol = "probe_rule_sweep_symbol" if is_rule_sweep else "probe_exploratory_symbol"
            technique = "codeguard-probe" if is_rule_sweep else "exploratory"
            return AIMessage(
                content="",
                tool_calls=[
                    {
                        "name": "queue_candidate",
                        "args": {
                            "normalized_path": self.normalized_path,
                            "symbol": symbol,
                            "vulnerability_class": "probe-class",
                            "description": "probe finding",
                            "technique": technique,
                        },
                        "id": self._next_id("queue"),
                    }
                ],
            )

        # the main agent's own graph (delegating to whichever Detector half)
        if isinstance(last, ToolMessage):
            return AIMessage(content=f"Delegation finished: {last.content}")
        if "rule-sweep" in sys_text:
            subagent_type = "detector-rule-sweep"
        elif "exploratory" in sys_text:
            subagent_type = "detector-exploratory"
        else:
            subagent_type = "detector-directed"
        return AIMessage(
            content="",
            tool_calls=[{"name": "task", "args": {"description": "detect", "subagent_type": subagent_type}, "id": self._next_id("task")}],
        )

    def _generate(self, messages, stop=None, run_manager=None, **kwargs) -> ChatResult:
        return ChatResult(generations=[ChatGeneration(message=self._decide(messages))])

    async def _agenerate(self, messages, stop=None, run_manager=None, **kwargs) -> ChatResult:
        return self._generate(messages, stop, run_manager, **kwargs)

    @property
    def _llm_type(self) -> str:
        return "combined-detector-fake"


class ClaimsButNeverCompletesFakeModel(CombinedDetectorFakeModel):
    """A directed half that claims a task, investigates (in principle),
    then gives up without ever calling complete_directed_task -- no
    coverage-log sweep ever gets recorded, so the checklist can never
    close. Proves the loop's no-progress safety valve, not the happy
    path CombinedDetectorFakeModel proves."""

    def _decide(self, messages) -> AIMessage:
        sys_text = " ".join(str(m.content) for m in messages if isinstance(m, SystemMessage))
        last = messages[-1]
        if "role's directed half" in sys_text and isinstance(last, ToolMessage) and str(last.content).startswith("task_id="):
            return AIMessage(content="Giving up on this task without completing it.")
        return super()._decide(messages)


@pytest.fixture
def target(tmp_path):
    content = TOY_TARGET.read_bytes()
    return from_upload({"vulnerable_app.py": content})


async def test_run_assessment_closes_the_checklist_via_the_directed_loop(tmp_path, target):
    """End-to-end proof, agent roles that don't affect the loop's own
    termination logic switched off: indexing is real, the security map's
    deterministic fallback is real, broad concurrent detection is real
    (driven through actual DeepAgents graphs) but deliberately can't
    satisfy any real checklist item on its own -- only the directed loop's
    coverage-log evidence can, and does, closing coverage completely."""
    normalized_path = target.files[0].normalized_path
    config = AssessmentConfig(
        target=target,
        db_path=tmp_path / "assessment.sqlite3",
        reports_dir=tmp_path / "reports",
        operator_goals=["sql-injection"],
        rules_dir=REPO_ROOT / "data" / "codeguard" / "rules",
        model=CombinedDetectorFakeModel(normalized_path=normalized_path),
        max_directed_workers=3,
        max_concurrent=3,
        max_cycles=5,
        budget_caps=BudgetCaps(yield_threshold=0.0),
        run_cartographer_agent=False,
        run_triager_agent=False,
        run_reporter_agent=False,
    )

    result = await run_assessment(config)

    # Indexing actually happened -- real function names from the real toy target.
    conn = connect(config.db_path)
    indexed = set(IndexStore(conn).list_functions())
    assert "get_user_by_name" in indexed

    # The security map's deterministic fallback is never empty (FR-036a),
    # even with the Cartographer agent switched off.
    assert result.security_map_digest.strip() != ""

    # Broad detection actually ran (both halves).
    assert {r.run_name for r in result.detection_results} >= {"detector-rule-sweep", "detector-exploratory"}
    # At least one directed-detection worker ran too -- proof the loop
    # actually directed at the gaps broad detection left open, not just
    # the two broad halves.
    assert any(r.run_name.startswith("detector-directed") for r in result.detection_results)

    # The whole checklist closed via the directed loop's coverage-log
    # evidence, exactly one cycle needed (every worker loops its own
    # WorkQueue claims to completion, so one round of workers drains
    # everything queued).
    assert result.coverage_complete is True
    assert result.cycles_run == 1


async def test_run_assessment_stops_via_no_progress_guard_when_directed_work_never_completes(tmp_path, target):
    """If directed workers claim tasks but never complete them (no
    coverage-log evidence ever recorded), the checklist can never close --
    the loop must still terminate, via the no-progress safety valve, not
    hang or silently exhaust max_cycles without a clear reason."""
    normalized_path = target.files[0].normalized_path
    config = AssessmentConfig(
        target=target,
        db_path=tmp_path / "assessment_stuck.sqlite3",
        reports_dir=tmp_path / "reports_stuck",
        operator_goals=["sql-injection"],
        rules_dir=REPO_ROOT / "data" / "codeguard" / "rules",
        model=ClaimsButNeverCompletesFakeModel(normalized_path=normalized_path),
        max_directed_workers=2,
        max_concurrent=2,
        max_cycles=4,
        budget_caps=BudgetCaps(yield_threshold=0.0),
        run_cartographer_agent=False,
        run_triager_agent=False,
        run_reporter_agent=False,
    )

    result = await run_assessment(config)

    assert result.coverage_complete is False
    assert result.cycles_run <= config.max_cycles
    assert result.stop_reason != ""
