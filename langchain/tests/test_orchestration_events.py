"""Phase 3 proofs: StreamEventTranslator (src/foundry/orchestration/events.py)
-- turning LangGraph's raw astream_events() stream into clean, UI-facing
events. Pure, synchronous, no agent/model/network involved -- exercised
against synthetic event dicts shaped exactly like the real ones captured
from a live DeepAgents graph run (see
tests/test_orchestration_detection.py for the real-graph proof that these
shapes are accurate, not assumed).
"""
from __future__ import annotations

from langchain_core.messages import ToolMessage
from langgraph.types import Command

from foundry.orchestration.events import StreamEventTranslator


def test_chain_start_for_a_real_subagent_emits_agent_start():
    t = StreamEventTranslator(role="main")
    event = t.translate({"event": "on_chain_start", "name": "detector-directed", "data": {}})
    assert event is not None
    assert event.kind == "agent_start"
    assert event.role == "detector-directed"
    assert "detector-directed" in event.detail


def test_chain_start_for_framework_internal_names_is_filtered_out():
    t = StreamEventTranslator(role="main")
    for noise_name in ("LangGraph", "PatchToolCallsMiddleware.before_agent", "model", "tools"):
        assert t.translate({"event": "on_chain_start", "name": noise_name, "data": {}}) is None


def test_tool_start_emits_tool_call_with_current_role():
    t = StreamEventTranslator(role="main")
    t.translate({"event": "on_chain_start", "name": "detector-directed", "data": {}})
    event = t.translate({"event": "on_tool_start", "name": "claim_directed_task", "data": {"input": {}}})
    assert event.kind == "tool_call"
    assert event.role == "detector-directed"
    assert "claim_directed_task" in event.detail


def test_tool_end_with_tool_message_output_extracts_content():
    t = StreamEventTranslator(role="main")
    output = ToolMessage(content="task_id=1 area=foo goal=bar", tool_call_id="claim_1")
    event = t.translate({"event": "on_tool_end", "name": "claim_directed_task", "data": {"output": output}})
    assert event.kind == "tool_result"
    assert "task_id=1 area=foo goal=bar" in event.detail


def test_tool_end_with_command_output_extracts_nested_message_content():
    """DeepAgents' own `task` tool returns a Command (updates graph state),
    not a plain ToolMessage -- verified live in
    tests/test_orchestration_detection.py's underlying graph runs."""
    t = StreamEventTranslator(role="main")
    output = Command(update={"messages": [ToolMessage(content="All directed tasks processed.", tool_call_id="task_1")]})
    event = t.translate({"event": "on_tool_end", "name": "task", "data": {"output": output}})
    assert event.kind == "tool_result"
    assert "All directed tasks processed." in event.detail


def test_tool_end_with_unrecognized_output_shape_falls_back_to_str():
    t = StreamEventTranslator(role="main")
    event = t.translate({"event": "on_tool_end", "name": "mystery_tool", "data": {"output": 42}})
    assert event.kind == "tool_result"
    assert "42" in event.detail


def test_role_reverts_to_caller_once_subagent_chain_ends():
    """A tool result the main agent receives back *from* a subagent (the
    `task` tool's own on_tool_end, which fires after the subagent's chain
    has already ended) must be attributed to the main agent, not left
    attributed to whichever subagent most recently ran."""
    t = StreamEventTranslator(role="main")
    t.translate({"event": "on_tool_start", "name": "task", "data": {"input": {}}})
    t.translate({"event": "on_chain_start", "name": "detector-directed", "data": {}})
    inner = t.translate({"event": "on_tool_start", "name": "claim_directed_task", "data": {"input": {}}})
    assert inner.role == "detector-directed"
    assert t.translate({"event": "on_chain_end", "name": "detector-directed", "data": {}}) is None
    back_in_main = t.translate({"event": "on_tool_end", "name": "task", "data": {"output": 42}})
    assert back_in_main.role == "main"


def test_chain_end_for_a_name_not_on_top_of_stack_is_a_no_op():
    """A chain-end whose name doesn't match the current top of the role
    stack (e.g. a framework-internal chain, or an out-of-order/unrelated
    end) must not pop the wrong role off."""
    t = StreamEventTranslator(role="main")
    t.translate({"event": "on_chain_start", "name": "detector-directed", "data": {}})
    t.translate({"event": "on_chain_end", "name": "some-other-chain", "data": {}})
    event = t.translate({"event": "on_tool_start", "name": "claim_directed_task", "data": {"input": {}}})
    assert event.role == "detector-directed"  # unaffected by the mismatched chain-end


def test_current_role_updates_across_agent_transitions():
    t = StreamEventTranslator(role="main")
    e1 = t.translate({"event": "on_tool_start", "name": "task", "data": {"input": {}}})
    assert e1.role == "main"
    t.translate({"event": "on_chain_start", "name": "triager", "data": {}})
    e2 = t.translate({"event": "on_tool_start", "name": "assign_verdict", "data": {"input": {}}})
    assert e2.role == "triager"


def test_irrelevant_event_kinds_return_none():
    t = StreamEventTranslator(role="main")
    for kind in ("on_chat_model_start", "on_chat_model_end", "on_chain_stream", "on_chain_end"):
        assert t.translate({"event": kind, "name": "whatever", "data": {}}) is None


def test_seq_only_increments_for_emitted_events():
    t = StreamEventTranslator(role="main")
    e1 = t.translate({"event": "on_chain_start", "name": "detector-directed", "data": {}})
    t.translate({"event": "on_chain_stream", "name": "LangGraph", "data": {}})  # not emitted
    e2 = t.translate({"event": "on_tool_start", "name": "claim_directed_task", "data": {"input": {}}})
    assert e1.seq == 1
    assert e2.seq == 2


def test_full_realistic_sequence_tracks_role_correctly_throughout():
    """The exact event kind/name sequence captured live from a real
    scripted-fake-model-driven DeepAgents run
    (tests/test_orchestration_detection.py's underlying mechanism),
    condensed to the UI-relevant subset."""
    raw_events = [
        {"event": "on_chain_start", "name": "LangGraph", "data": {}},
        {"event": "on_tool_start", "name": "task", "data": {"input": {"subagent_type": "detector-directed"}}},
        {"event": "on_chain_start", "name": "detector-directed", "data": {}},
        {"event": "on_tool_start", "name": "claim_directed_task", "data": {"input": {}}},
        {
            "event": "on_tool_end",
            "name": "claim_directed_task",
            "data": {"output": ToolMessage(content="task_id=1 area=foo goal=bar", tool_call_id="c1")},
        },
        {"event": "on_tool_start", "name": "complete_directed_task", "data": {"input": {"task_id": 1}}},
        {
            "event": "on_tool_end",
            "name": "complete_directed_task",
            "data": {"output": ToolMessage(content="Task 1 completed.", tool_call_id="c2")},
        },
        {"event": "on_chain_end", "name": "detector-directed", "data": {}},  # subagent's own chain ends
        {
            "event": "on_tool_end",
            "name": "task",
            "data": {"output": Command(update={"messages": [ToolMessage(content="Done.", tool_call_id="task_1")]})},
        },
    ]
    t = StreamEventTranslator(role="main")
    emitted = [t.translate(e) for e in raw_events]
    emitted = [e for e in emitted if e is not None]

    kinds = [(e.kind, e.role) for e in emitted]
    assert kinds == [
        ("tool_call", "main"),  # task tool called from the main agent
        ("agent_start", "detector-directed"),  # subagent starts
        ("tool_call", "detector-directed"),
        ("tool_result", "detector-directed"),
        ("tool_call", "detector-directed"),
        ("tool_result", "detector-directed"),
        ("tool_result", "main"),  # task tool's own result, back in the main agent
    ]
    assert [e.seq for e in emitted] == list(range(1, len(emitted) + 1))
