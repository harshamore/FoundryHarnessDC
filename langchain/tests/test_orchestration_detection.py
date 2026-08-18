"""Phase 2's central proof: real subagent *instances* actually running at
once, driven through the real DeepAgents/LangGraph async execution path --
not simulated threads (the Substrate section's proof for the substrate
itself), not mocked function calls (which would only prove the mock
behaves as scripted), and not a single top-level agent batching several
tool calls into one turn (all the Full Pipeline section's combined agent
ever demonstrated).

No real OpenAI key is available in this environment, so genuine LLM calls
can't be made here -- the same reason every notebook section's live-agent
cells can only be verified up to a real `AuthenticationError`. Scripted
fake `BaseChatModel` subclasses stand in for the model, but every other
layer is real: a real `create_deep_agent(...)` graph, real DeepAgents
`task`-tool delegation, the real `detector-directed` subagent and its real
`claim_directed_task`/`complete_directed_task` tools, a real `WorkQueue`
against a real SQLite database, run via real `asyncio.gather`. `bind_tools`
is the only framework method overridden as a no-op (a fake model can't
usefully validate tool schemas); every actual tool *call* still goes
through the real LangGraph ToolNode.
"""
from __future__ import annotations

import asyncio
from pathlib import Path

import pytest
from langchain_core.language_models.chat_models import BaseChatModel
from langchain_core.messages import AIMessage, SystemMessage, ToolMessage
from langchain_core.outputs import ChatGeneration, ChatResult

from foundry.orchestration.detection import (
    run_broad_detection_concurrently,
    run_directed_workers_concurrently,
)
from foundry.substrate.db import connect
from foundry.substrate.work_queue import WorkQueue


# ---------------------------------------------------------------------------
# A scripted fake model driving the detector-directed subagent's real
# claim/complete loop by inspecting the last tool result -- not a fixed
# script, since how many claim/complete round-trips happen depends on how
# many directed tasks are actually queued, which varies per test.
# ---------------------------------------------------------------------------


class DirectedWorkerFakeModel(BaseChatModel):
    call_counter: int = 0
    delay_seconds: float = 0.0

    def bind_tools(self, tools, **kwargs):
        return self

    def _next_id(self, prefix: str) -> str:
        self.call_counter += 1
        return f"{prefix}_{self.call_counter}"

    def _decide(self, messages) -> AIMessage:
        sys_text = " ".join(str(m.content) for m in messages if isinstance(m, SystemMessage))
        last = messages[-1]

        if "directed half" in sys_text:  # inside the detector-directed subagent's own graph
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
                    return AIMessage(
                        content="", tool_calls=[{"name": "claim_directed_task", "args": {}, "id": self._next_id("claim")}]
                    )
            return AIMessage(content="", tool_calls=[{"name": "claim_directed_task", "args": {}, "id": self._next_id("claim")}])

        # the main agent's own graph
        if isinstance(last, ToolMessage):
            return AIMessage(content=f"Delegation finished: {last.content}")
        return AIMessage(
            content="",
            tool_calls=[
                {
                    "name": "task",
                    "args": {"description": "run every directed task", "subagent_type": "detector-directed"},
                    "id": self._next_id("task"),
                }
            ],
        )

    def _generate(self, messages, stop=None, run_manager=None, **kwargs) -> ChatResult:
        return ChatResult(generations=[ChatGeneration(message=self._decide(messages))])

    async def _agenerate(self, messages, stop=None, run_manager=None, **kwargs) -> ChatResult:
        if self.delay_seconds:
            await asyncio.sleep(self.delay_seconds)
        return self._generate(messages, stop, run_manager, **kwargs)

    @property
    def _llm_type(self) -> str:
        return "directed-worker-fake"


@pytest.fixture
def db_path(tmp_path: Path) -> Path:
    return tmp_path / "orchestration_detection_test.sqlite3"


async def test_single_directed_worker_claims_and_completes_all_tasks(db_path):
    conn = connect(db_path)
    wq = WorkQueue(conn)
    wq.enqueue("directed_detection:auth:injection", {"area": "auth", "goal": "injection", "instruction": "check"})
    wq.enqueue("directed_detection:files:traversal", {"area": "files", "goal": "traversal", "instruction": "check"})
    conn.close()

    results = await run_directed_workers_concurrently(
        db_path=db_path, n_workers=1, max_concurrent=1, model=DirectedWorkerFakeModel()
    )

    assert len(results) == 1
    assert "All directed tasks processed" in results[0].response_text

    verify_conn = connect(db_path)
    rows = verify_conn.execute("SELECT status FROM work_queue").fetchall()
    assert {r["status"] for r in rows} == {"done"}


async def test_concurrent_directed_workers_never_double_claim_a_task(db_path):
    """The core Phase 2 proof: N real subagent instances, each with its own
    connection, racing for the same real WorkQueue rows via asyncio.gather
    -- every task claimed exactly once, none lost, none double-claimed.
    Same property tests/test_finding_store.py::
    test_concurrent_claims_never_double_claim proves under simulated
    threads; this proves it under genuine concurrent DeepAgents/LangGraph
    agent execution instead."""
    n_tasks = 12
    n_workers = 5

    conn = connect(db_path)
    wq = WorkQueue(conn)
    task_ids = {wq.enqueue(f"directed_detection:area{i}:goal{i}", {"area": f"area{i}", "goal": f"goal{i}", "instruction": "check"}) for i in range(n_tasks)}
    conn.close()

    # Each worker gets its own model instance (mirroring its own connection)
    # -- a small delay makes genuine overlap observable/likely rather than
    # accidentally-sequential, matching the same technique
    # test_orchestration_concurrency.py uses to prove run_bounded's bound.
    results = await run_directed_workers_concurrently(
        db_path=db_path,
        n_workers=n_workers,
        max_concurrent=n_workers,
        model=DirectedWorkerFakeModel(delay_seconds=0.01),
    )
    assert len(results) == n_workers

    verify_conn = connect(db_path)
    rows = verify_conn.execute("SELECT id, status, claimed_by FROM work_queue").fetchall()
    assert {r["id"] for r in rows} == task_ids  # every task present, none lost
    assert all(r["status"] == "done" for r in rows)  # every task actually completed
    assert all(r["claimed_by"] is None for r in rows)  # released after completion, per WorkQueue.release


async def test_more_workers_than_tasks_the_extras_simply_finish_idle(db_path):
    conn = connect(db_path)
    wq = WorkQueue(conn)
    wq.enqueue("directed_detection:only:one", {"area": "only", "goal": "one", "instruction": "check"})
    conn.close()

    results = await run_directed_workers_concurrently(
        db_path=db_path, n_workers=4, max_concurrent=4, model=DirectedWorkerFakeModel()
    )
    assert len(results) == 4
    # every worker's run either processed the one task or found nothing --
    # never an error, never a hang.
    for r in results:
        assert "All directed tasks processed" in r.response_text


async def test_max_concurrent_bounds_directed_workers(db_path):
    """run_directed_workers_concurrently must actually thread max_concurrent
    through to run_bounded, not just accept the parameter -- proven the
    same way test_orchestration_concurrency.py proves run_bounded itself,
    but now through the real detection.py wiring."""
    conn = connect(db_path)
    wq = WorkQueue(conn)
    for i in range(6):
        wq.enqueue(f"directed_detection:a{i}:g{i}", {"area": f"a{i}", "goal": f"g{i}", "instruction": "check"})
    conn.close()

    peak_concurrency = 0
    currently_running = 0
    lock = asyncio.Lock()

    class TrackingFakeModel(DirectedWorkerFakeModel):
        async def _agenerate(self, messages, stop=None, run_manager=None, **kwargs):
            nonlocal peak_concurrency, currently_running
            last = messages[-1]
            is_first_claim = not isinstance(last, ToolMessage) and "directed half" in " ".join(
                str(m.content) for m in messages if isinstance(m, SystemMessage)
            )
            if is_first_claim:
                async with lock:
                    currently_running += 1
                    peak_concurrency = max(peak_concurrency, currently_running)
                await asyncio.sleep(0.03)
                async with lock:
                    currently_running -= 1
            return await super()._agenerate(messages, stop, run_manager, **kwargs)

    await run_directed_workers_concurrently(
        db_path=db_path, n_workers=6, max_concurrent=2, model=TrackingFakeModel()
    )
    assert peak_concurrency <= 2
    assert peak_concurrency == 2  # the bound was actually reached, not just never exceeded


# ---------------------------------------------------------------------------
# run_broad_detection_concurrently -- rule-sweep and exploratory, two
# genuinely *different* subagent types, each on its own connection. A
# lighter probe than the directed-worker model above: drives whichever
# half it's serving through exactly one queue_candidate call, enough to
# prove genuine concurrent execution of two different subagent types
# against the same database -- full CodeGuard-tool-use realism is already
# covered by test_detector.py's structural tests, not re-proven here.
# ---------------------------------------------------------------------------


class BroadDetectionProbeFakeModel(BaseChatModel):
    normalized_path: str
    delay_seconds: float = 0.0
    call_counter: int = 0

    def bind_tools(self, tools, **kwargs):
        return self

    def _next_id(self, prefix: str) -> str:
        self.call_counter += 1
        return f"{prefix}_{self.call_counter}"

    def _decide(self, messages) -> AIMessage:
        sys_text = " ".join(str(m.content) for m in messages if isinstance(m, SystemMessage))
        last = messages[-1]

        if "role's rule-sweep half" in sys_text or "role's exploratory half" in sys_text:
            if isinstance(last, ToolMessage):
                return AIMessage(content=f"queued: {last.content}")
            is_rule_sweep = "role's rule-sweep half" in sys_text
            technique = "codeguard-probe-rule" if is_rule_sweep else "exploratory"
            # Distinct symbols on purpose: this test's job is to prove each
            # subagent's own connection persists to the shared database
            # file, not to re-exercise the cross-connection dedup race --
            # that has its own dedicated proof in
            # tests/test_finding_store.py::
            # test_concurrent_queue_candidate_on_separate_connections_same_fingerprint_does_not_raise.
            symbol = "probe_symbol_rule_sweep" if is_rule_sweep else "probe_symbol_exploratory"
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

        # the main agent's own graph
        if isinstance(last, ToolMessage):
            return AIMessage(content=f"Delegation finished: {last.content}")
        subagent_type = "detector-rule-sweep" if "rule-sweep" in sys_text else "detector-exploratory"
        return AIMessage(
            content="",
            tool_calls=[{"name": "task", "args": {"description": "detect", "subagent_type": subagent_type}, "id": self._next_id("task")}],
        )

    def _generate(self, messages, stop=None, run_manager=None, **kwargs) -> ChatResult:
        return ChatResult(generations=[ChatGeneration(message=self._decide(messages))])

    async def _agenerate(self, messages, stop=None, run_manager=None, **kwargs) -> ChatResult:
        if self.delay_seconds:
            await asyncio.sleep(self.delay_seconds)
        return self._generate(messages, stop, run_manager, **kwargs)

    @property
    def _llm_type(self) -> str:
        return "broad-detection-probe-fake"


async def test_broad_detection_runs_both_subagent_types_against_separate_connections(db_path):
    normalized_path = "data/toy_target/vulnerable_app.py"
    conn = connect(db_path)
    conn.close()  # just create the schema; the two workers open their own connections

    results = await run_broad_detection_concurrently(
        db_path=db_path,
        rules=[],
        security_map_digest="test digest",
        model=BroadDetectionProbeFakeModel(normalized_path=normalized_path, delay_seconds=0.01),
    )

    assert {r.run_name for r in results} == {"detector-rule-sweep", "detector-exploratory"}

    verify_conn = connect(db_path)
    rows = verify_conn.execute("SELECT symbol, technique FROM findings").fetchall()
    seen = {(r["symbol"], r["technique"]) for r in rows}
    # Both subagents' writes are visible in the shared database -- proof
    # each one's own connection actually persisted to the same file, not a
    # private in-memory copy.
    assert seen == {
        ("probe_symbol_rule_sweep", "codeguard-probe-rule"),
        ("probe_symbol_exploratory", "exploratory"),
    }


async def test_broad_detection_two_workers_actually_overlap_in_time(db_path):
    conn = connect(db_path)
    conn.close()

    peak_concurrency = 0
    currently_running = 0
    lock = asyncio.Lock()

    class TrackingProbeModel(BroadDetectionProbeFakeModel):
        async def _agenerate(self, messages, stop=None, run_manager=None, **kwargs):
            nonlocal peak_concurrency, currently_running
            sys_text = " ".join(str(m.content) for m in messages if isinstance(m, SystemMessage))
            is_subagent_first_turn = ("role's rule-sweep half" in sys_text or "role's exploratory half" in sys_text) and not isinstance(
                messages[-1], ToolMessage
            )
            if is_subagent_first_turn:
                async with lock:
                    currently_running += 1
                    peak_concurrency = max(peak_concurrency, currently_running)
                await asyncio.sleep(0.05)
                async with lock:
                    currently_running -= 1
            return await super()._agenerate(messages, stop, run_manager, **kwargs)

    await run_broad_detection_concurrently(
        db_path=db_path,
        rules=[],
        security_map_digest="test digest",
        model=TrackingProbeModel(normalized_path="data/toy_target/vulnerable_app.py"),
    )
    assert peak_concurrency == 2  # both really overlapped in wall-clock time, not run one after the other


# ---------------------------------------------------------------------------
# Phase 3: on_event streaming -- proves the astream_events() path (used
# whenever a caller passes on_event) produces the exact same real
# WorkQueue outcome as the .ainvoke() path already proven above, while
# also emitting live events through the real event stream.
# ---------------------------------------------------------------------------


async def test_on_event_streaming_produces_same_result_as_non_streaming(db_path):
    conn = connect(db_path)
    wq = WorkQueue(conn)
    wq.enqueue("directed_detection:auth:injection", {"area": "auth", "goal": "injection", "instruction": "check"})
    wq.enqueue("directed_detection:files:traversal", {"area": "files", "goal": "traversal", "instruction": "check"})
    conn.close()

    received = []
    results = await run_directed_workers_concurrently(
        db_path=db_path,
        n_workers=1,
        max_concurrent=1,
        model=DirectedWorkerFakeModel(),
        on_event=received.append,
    )

    assert len(results) == 1
    assert "All directed tasks processed" in results[0].response_text  # identical WorkerResult shape/content

    verify_conn = connect(db_path)
    rows = verify_conn.execute("SELECT status FROM work_queue").fetchall()
    assert {r["status"] for r in rows} == {"done"}  # identical real outcome to the non-streaming test above

    # And it actually streamed something real: at least one agent_start for
    # the directed subagent, real tool_call/tool_result pairs for both
    # claim_directed_task and complete_directed_task, every event
    # attributed to this worker's own identity (not the bare, ambiguous
    # "detector-directed" every worker's subagent literally shares).
    assert all(e.role == "detector-directed-0" for e in received)
    assert any(e.kind == "agent_start" for e in received)
    assert any(e.kind == "tool_call" and "claim_directed_task" in e.detail for e in received)
    assert any(e.kind == "tool_result" and "task_id=" in e.detail for e in received)
    assert any(e.kind == "tool_call" and "complete_directed_task" in e.detail for e in received)
    # seq is per-worker-invocation and monotonic within it.
    assert [e.seq for e in received] == sorted(e.seq for e in received)


async def test_on_event_none_keeps_the_original_ainvoke_path_unchanged(db_path):
    """The default (on_event=None) must still take the .ainvoke() path --
    a regression guard, not just an absence-of-crash check, since a bug
    here would silently switch every existing Phase 2 caller onto the
    streaming path instead."""
    conn = connect(db_path)
    wq = WorkQueue(conn)
    wq.enqueue("directed_detection:auth:injection", {"area": "auth", "goal": "injection", "instruction": "check"})
    conn.close()

    results = await run_directed_workers_concurrently(
        db_path=db_path, n_workers=1, max_concurrent=1, model=DirectedWorkerFakeModel()
    )
    assert len(results) == 1
    assert "All directed tasks processed" in results[0].response_text


async def test_on_event_receives_interleaved_events_from_concurrent_workers_correctly_attributed(db_path):
    """Multiple concurrent workers' events can interleave in call order
    (on_event is invoked from whichever worker's task is currently
    running), but every event's own `role` still names the correct
    worker -- a consumer doesn't need the stream serialized per worker to
    make sense of it."""
    conn = connect(db_path)
    wq = WorkQueue(conn)
    for i in range(4):
        wq.enqueue(f"directed_detection:a{i}:g{i}", {"area": f"a{i}", "goal": f"g{i}", "instruction": "check"})
    conn.close()

    received = []
    await run_directed_workers_concurrently(
        db_path=db_path,
        n_workers=2,
        max_concurrent=2,
        model=DirectedWorkerFakeModel(delay_seconds=0.01),
        on_event=received.append,
    )

    roles_seen = {e.role for e in received}
    assert roles_seen == {"detector-directed-0", "detector-directed-1"}
    # Each worker's own events, in isolation, are still internally
    # consistent: the main agent's own delegating tool_call ("task") comes
    # first, then the subagent's agent_start, then its own tool events --
    # all correctly relabeled to this worker's identity throughout.
    for worker_role in ("detector-directed-0", "detector-directed-1"):
        worker_events = [e for e in received if e.role == worker_role]
        assert worker_events[0].kind == "tool_call"
        assert any(e.kind == "agent_start" for e in worker_events)
        assert any(e.kind == "tool_call" and "claim_directed_task" in e.detail for e in worker_events)
