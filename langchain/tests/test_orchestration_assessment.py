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
from langchain_core.callbacks.base import BaseCallbackHandler
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
        run_exploitability_agent=False,
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

    # Phase 5: the CISO report is always written as the assessment's final
    # step, alongside the plain rollup -- the fake model here doesn't
    # recognize the executive-summary prompt, so it lands as the
    # deterministic fallback (see test_executive_summary.py for the
    # real-model path), but the file itself, and the report's own
    # structure, are real.
    ciso_report_path = config.reports_dir / "ciso_report.md"
    assert ciso_report_path.exists()
    ciso_report = ciso_report_path.read_text()
    assert "# CISO Security Assessment Report" in ciso_report
    assert "## Executive Summary" in ciso_report


class _FakeGalileoLogger:
    project_id = "proj-123"
    log_stream_id = "stream-456"


class _FakeGalileoCallback(BaseCallbackHandler):
    """A real (no-op) LangChain callback handler -- `agent.ainvoke`'s own
    callback manager expects real handler attributes (`run_inline`, etc.),
    not just anything with a `galileo_logger` -- so a bare object isn't
    enough here the way it is in test_observability.py's unit-level
    console_url() tests."""

    galileo_logger = _FakeGalileoLogger()


async def test_run_assessment_surfaces_the_galileo_console_url_when_tracing_is_configured(tmp_path, target):
    """API/UI diagnostic: previously nothing surfaced whether Galileo
    tracing actually activated for a run -- a user who configured it had
    no way to confirm besides trusting silence, indistinguishable from it
    silently failing (see build_galileo_callback's own fails-soft
    contract). AssessmentResult.galileo_console_url closes that gap."""
    normalized_path = target.files[0].normalized_path
    config = AssessmentConfig(
        target=target,
        db_path=tmp_path / "assessment_galileo.sqlite3",
        reports_dir=tmp_path / "reports_galileo",
        operator_goals=["sql-injection"],
        rules_dir=REPO_ROOT / "data" / "codeguard" / "rules",
        model=CombinedDetectorFakeModel(normalized_path=normalized_path),
        max_directed_workers=1,
        max_concurrent=1,
        max_cycles=1,
        budget_caps=BudgetCaps(yield_threshold=0.0),
        run_cartographer_agent=False,
        run_triager_agent=False,
        run_reporter_agent=False,
        run_exploitability_agent=False,
        galileo_callback=_FakeGalileoCallback(),
    )
    result = await run_assessment(config)
    assert result.galileo_console_url == "https://app.galileo.ai/project/proj-123/log-streams/stream-456"


async def test_run_assessment_leaves_galileo_console_url_none_when_tracing_not_configured(tmp_path, target):
    normalized_path = target.files[0].normalized_path
    config = AssessmentConfig(
        target=target,
        db_path=tmp_path / "assessment_no_galileo.sqlite3",
        reports_dir=tmp_path / "reports_no_galileo",
        operator_goals=["sql-injection"],
        rules_dir=REPO_ROOT / "data" / "codeguard" / "rules",
        model=CombinedDetectorFakeModel(normalized_path=normalized_path),
        max_directed_workers=1,
        max_concurrent=1,
        max_cycles=1,
        budget_caps=BudgetCaps(yield_threshold=0.0),
        run_cartographer_agent=False,
        run_triager_agent=False,
        run_reporter_agent=False,
        run_exploitability_agent=False,
    )
    result = await run_assessment(config)
    assert result.galileo_console_url is None


async def test_run_assessment_indexes_cloud_files_alongside_code(tmp_path):
    """Phase 6: parallel to the existing code-indexing proof above --
    uploading code and IaC/IAM together results in both a populated
    IndexStore *and* a populated CloudResourceStore from one run,
    without needing any subagent (this is deterministic ingestion, no
    LLM involved, so every real agent role is switched off here)."""
    pytest.importorskip("hcl2")
    from foundry.cloud.store import CloudResourceStore

    fixture_root = REPO_ROOT / "data" / "cloud_toy_target"
    files = {"lambda/handler.py": (fixture_root / "lambda" / "handler.py").read_bytes()}
    for name in ("main.tf", "iam_policy.json", "k8s-deployment.yaml"):
        files[name] = (fixture_root / name).read_bytes()
    cloud_target = from_upload(files)

    config = AssessmentConfig(
        target=cloud_target,
        db_path=tmp_path / "assessment_cloud.sqlite3",
        reports_dir=tmp_path / "reports_cloud",
        operator_goals=["sql-injection"],
        rules_dir=REPO_ROOT / "data" / "codeguard" / "rules",
        model=CombinedDetectorFakeModel(normalized_path="lambda/handler.py"),
        max_directed_workers=1,
        max_concurrent=1,
        max_cycles=1,
        budget_caps=BudgetCaps(yield_threshold=0.0),
        run_cartographer_agent=False,
        run_triager_agent=False,
        run_reporter_agent=False,
        run_exploitability_agent=False,
    )
    await run_assessment(config)

    conn = connect(config.db_path)
    assert "get_user_by_name" in IndexStore(conn).list_functions()

    cloud_store = CloudResourceStore(conn)
    addresses = {r.address for r in cloud_store.list_resources()}
    assert "aws_lambda_function.process_upload" in addresses
    assert "Deployment.process-upload" in addresses
    assert "iam-policy.prod-admin-policy" in addresses
    assert cloud_store.list_grants(principal="iam-policy.prod-admin-policy")

    # Phase 7: exposure and reachability are computed and persisted as
    # part of the same run, no subagent needed -- the Lambda has a public
    # Function URL (exposed) and reaches the S3 bucket via its
    # over-permissioned inline policy (the "exploitable" story Phase 8
    # will classify against).
    exposure = cloud_store.get_exposure("aws_lambda_function.process_upload")
    assert exposure is not None
    assert exposure.is_exposed is True

    reachability = cloud_store.list_reachability(from_address="aws_lambda_function.process_upload")
    assert any(e.matched_resource == "aws_s3_bucket.uploads" for e in reachability)


class DetectorAndExploitabilityFakeModel(CombinedDetectorFakeModel):
    """Extends the Detector-only fake model to also drive the
    exploitability-mapper's real tool-calling loop -- broad detection
    always runs regardless of run_*_agent flags, so any fake model given
    to run_assessment must still handle it even when this test's only
    real interest is the exploitability-mapper's own wiring."""

    classified: int = 0

    def _decide(self, messages):
        sys_text = " ".join(str(m.content) for m in messages if isinstance(m, SystemMessage))
        last = messages[-1]

        if "Exploitability Mapper role" in sys_text:
            if isinstance(last, ToolMessage):
                text = str(last.content)
                if text.startswith("fingerprint="):
                    if self.classified == 0:
                        fp = text.split("fingerprint=")[1].split(" ")[0]
                        self.classified += 1
                        return AIMessage(
                            content="",
                            tool_calls=[{
                                "name": "classify_exploitability",
                                "args": {
                                    "finding_fingerprint": fp,
                                    "classification": "not_correlated",
                                    "reasoning": "no matching cloud resource found",
                                    "correlated_resource": None,
                                },
                                "id": self._next_id("classify"),
                            }],
                        )
                    return AIMessage(content="Done.")
                if "Recorded" in text or "rejected" in text:
                    return AIMessage(content="Done.")
                return AIMessage(content="Nothing to classify.")
            return AIMessage(content="", tool_calls=[{"name": "list_confirmed_findings", "args": {}, "id": self._next_id("list")}])

        if "exploitability-mapper" in sys_text:
            if isinstance(last, ToolMessage):
                return AIMessage(content=f"Delegation finished: {last.content}")
            return AIMessage(
                content="",
                tool_calls=[{"name": "task", "args": {"description": "classify", "subagent_type": "exploitability-mapper"}, "id": self._next_id("task")}],
            )

        return super()._decide(messages)


async def test_run_assessment_wires_the_exploitability_mapper_when_enabled(tmp_path):
    """Phase 8: proves run_assessment's own wiring (config flag ->
    subagent construction -> real invocation -> build_ciso_report
    receiving the store), not the subagent's tool-calling logic itself
    (already proven in isolation, with a real confirmed finding, in
    test_cloud_exploitability.py::test_real_agent_run_classifies_both_
    findings_correctly). Triager stays off here (no automated test in
    this codebase drives Triager's own real agent execution yet), so
    there are zero confirmed findings -- this specifically proves the
    'nothing to classify' path completes cleanly through the real graph,
    not just via a mocked run_assessment."""
    pytest.importorskip("hcl2")
    from foundry.cloud.store import CloudResourceStore

    fixture_root = REPO_ROOT / "data" / "cloud_toy_target"
    files = {"lambda/handler.py": (fixture_root / "lambda" / "handler.py").read_bytes()}
    for name in ("main.tf", "iam_policy.json", "k8s-deployment.yaml"):
        files[name] = (fixture_root / name).read_bytes()
    cloud_target = from_upload(files)

    config = AssessmentConfig(
        target=cloud_target,
        db_path=tmp_path / "assessment_exploitability.sqlite3",
        reports_dir=tmp_path / "reports_exploitability",
        operator_goals=["sql-injection"],
        rules_dir=REPO_ROOT / "data" / "codeguard" / "rules",
        model=DetectorAndExploitabilityFakeModel(normalized_path="lambda/handler.py"),
        max_directed_workers=1,
        max_concurrent=1,
        max_cycles=1,
        budget_caps=BudgetCaps(yield_threshold=0.0),
        run_cartographer_agent=False,
        run_triager_agent=False,
        run_reporter_agent=False,
        run_exploitability_agent=True,
    )
    await run_assessment(config)

    # No crash, and the CISO report was still produced with the
    # exploitability section present (even though empty -- zero
    # confirmed findings means zero classifications, not a missing
    # section, since exploitability_store was genuinely passed through).
    ciso_report = (config.reports_dir / "ciso_report.md").read_text()
    assert "## Exploitability" in ciso_report
    assert "0 exploitable, 0 contained, 0 not correlated, 0 unclassified" in ciso_report


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
        run_exploitability_agent=False,
    )

    result = await run_assessment(config)

    assert result.coverage_complete is False
    assert result.cycles_run <= config.max_cycles
    assert result.stop_reason != ""


async def test_run_assessment_streams_live_events_when_on_event_is_given(tmp_path, target):
    """Phase 3: passing on_event switches the whole assessment onto the
    streaming path (every real subagent call it makes, broad detection and
    the directed loop alike), without changing the real outcome -- same
    checklist-closing behavior test_run_assessment_closes_the_checklist_
    via_the_directed_loop already proved for the non-streaming path."""
    normalized_path = target.files[0].normalized_path
    received = []
    config = AssessmentConfig(
        target=target,
        db_path=tmp_path / "assessment_streamed.sqlite3",
        reports_dir=tmp_path / "reports_streamed",
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
        run_exploitability_agent=False,
        on_event=received.append,
    )

    result = await run_assessment(config)

    assert result.coverage_complete is True  # identical real outcome to the non-streaming test
    assert len(received) > 0
    roles_seen = {e.role for e in received}
    assert "detector-rule-sweep" in roles_seen
    assert "detector-exploratory" in roles_seen
    assert any(role.startswith("detector-directed") for role in roles_seen)
    assert all(e.seq >= 1 for e in received)
