"""Clean, UI-facing events translated from LangGraph's raw
`agent.astream_events(...)` stream (Phase 3) -- "which agent is active,
which tool it just called" sourced from the same real execution DeepAgents
/LangGraph already produces, not a separate instrumentation layer bolted
on afterward. This is the same underlying event stream Galileo's callback
already taps (`src/foundry/observability/galileo.py`); this is a second,
independent consumer of it, not a replacement.

Verified directly against a real DeepAgents graph (a scripted fake model
driving the real `detector-directed` subagent) before being relied on
here: `on_chain_start` events name real subagents (e.g.
"detector-directed") interleaved with framework-internal chain names
("LangGraph", "model", "tools", "PatchToolCallsMiddleware.before_agent")
that show up in every run and aren't a role transition; `on_tool_start`/
`on_tool_end` carry the tool name and args/result directly.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

# Framework-internal chain names present in every run -- not a real
# subagent, filtered out of "agent_start" events so only genuine role
# transitions surface.
_NOISE_CHAIN_NAMES = {"LangGraph", "PatchToolCallsMiddleware.before_agent", "model", "tools"}


@dataclass(frozen=True)
class AssessmentEvent:
    seq: int
    timestamp: str
    kind: str  # "agent_start" | "tool_call" | "tool_result"
    role: str
    detail: str


def _tool_result_text(output: Any) -> str:
    """`on_tool_end`'s output is a `ToolMessage` for an ordinary tool, but
    a `Command` for DeepAgents' own `task` tool (it updates graph state,
    not just returns a message) -- extract the human-readable result
    either way rather than assuming one shape."""
    content = getattr(output, "content", None)
    if content is not None:
        return str(content)
    update = getattr(output, "update", None)
    if isinstance(update, dict):
        messages = update.get("messages") or []
        if messages and hasattr(messages[-1], "content"):
            return str(messages[-1].content)
    return str(output)


class StreamEventTranslator:
    """Stateful across one `agent.astream_events(...)` iteration: which
    subagent is "current" is a stack, pushed on a real subagent's
    `on_chain_start` and popped on its matching `on_chain_end` -- so a
    tool result the main agent receives *back* from a subagent (e.g. the
    `task` tool's own `on_tool_end`, which fires after the subagent's
    chain has already ended) is correctly attributed to the main agent,
    not left attributed to whichever subagent most recently ran. Also
    correctly handles nested delegation, if a future role ever does that,
    not just the one level this build currently has.

    One instance per subagent invocation -- `foundry.orchestration.
    detection`/`assessment` create a fresh one per `.astream_events()`
    call, never share one across concurrent workers.
    """

    def __init__(self, role: str) -> None:
        self._role_stack: list[str] = [role]
        self._seq = 0

    @property
    def _current_role(self) -> str:
        return self._role_stack[-1]

    def translate(self, event: dict) -> AssessmentEvent | None:
        """One raw stream event -> one clean `AssessmentEvent`, or `None`
        if this event isn't UI-relevant (most aren't -- token-level
        chunks, framework-internal chain starts/ends, and a chain-end's
        role-pop is a bookkeeping signal, not a UI event of its own)."""
        kind = event.get("event")
        name = event.get("name", "")
        data = event.get("data", {})

        if kind == "on_chain_start" and name not in _NOISE_CHAIN_NAMES:
            self._role_stack.append(name)
            return self._emit("agent_start", name, f"{name} started")

        if kind == "on_chain_end" and name not in _NOISE_CHAIN_NAMES:
            if len(self._role_stack) > 1 and self._role_stack[-1] == name:
                self._role_stack.pop()
            return None

        if kind == "on_tool_start":
            return self._emit("tool_call", self._current_role, f"{name}({data.get('input')})")

        if kind == "on_tool_end":
            result = _tool_result_text(data.get("output"))
            return self._emit("tool_result", self._current_role, f"{name} -> {result}")

        return None

    def _emit(self, kind: str, role: str, detail: str) -> AssessmentEvent:
        self._seq += 1
        return AssessmentEvent(
            seq=self._seq, timestamp=datetime.now(timezone.utc).isoformat(), kind=kind, role=role, detail=detail
        )
