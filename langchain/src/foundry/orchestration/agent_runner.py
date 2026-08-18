"""One subagent, wrapped in its own throwaway single-subagent main agent,
run once -- the shared primitive both `detection.py` (concurrent Detector
workers) and `assessment.py` (the sequential Cartographer/Triager/Reporter
steps) build on. Real `create_deep_agent(...)`, real invocation either
way; the only choice this makes is `.ainvoke()` vs `.astream_events()`,
and that choice never changes what gets written to the database or what
text comes back, only whether live events are emitted along the way
(Phase 3).
"""
from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, replace
from typing import Any

from deepagents import create_deep_agent

from foundry.agents._middleware import minimal_filesystem_middleware
from foundry.observability.galileo import galileo_run_config
from foundry.orchestration.events import AssessmentEvent, StreamEventTranslator


@dataclass(frozen=True)
class RoleResult:
    run_name: str
    response_text: str


async def run_single_subagent(
    *,
    model: str | Any,
    subagent: dict,
    main_system_prompt: str,
    user_message: str,
    galileo_callback,
    run_name: str,
    on_event: Callable[[AssessmentEvent], None] | None = None,
) -> RoleResult:
    """`model` is typed `str | Any` (not `str | BaseChatModel`) so tests
    can pass a scripted fake chat model instance without importing
    langchain_core here just for a type hint.

    `on_event`, if given (Phase 3), switches from `.ainvoke()` to
    `.astream_events()` -- same real execution either way, the only
    difference is whether anyone's watching it happen. `None` (the
    default) is the exact behavior Phase 2's tests already proved.

    Every event this call emits is tagged with `run_name`, overriding
    whatever role `StreamEventTranslator` itself tracked -- concurrent
    callers using the *same* subagent type (e.g. several directed-
    detection workers, each with a different `run_name` but an identical
    literal subagent `name`) can't be told apart by the raw LangGraph
    stream's own node names once that subagent's chain starts; only this
    call's own `run_name` can. This whole invocation -- main agent, its
    one delegation, the subagent's own turn -- is one logical unit from
    the caller's perspective regardless of DeepAgents' internal
    main-agent/subagent split, so collapsing every event onto one role is
    the accurate view, not a simplification that loses information a
    consumer actually needed."""
    agent = create_deep_agent(
        model=model,
        subagents=[subagent],
        middleware=[minimal_filesystem_middleware()],
        system_prompt=main_system_prompt,
    )
    config = galileo_run_config(galileo_callback, run_name=run_name)
    input_ = {"messages": [{"role": "user", "content": user_message}]}

    if on_event is None:
        response = await agent.ainvoke(input_, config=config)
        return RoleResult(run_name=run_name, response_text=response["messages"][-1].content)

    translator = StreamEventTranslator(role=run_name)
    final_output: dict | None = None
    async for raw_event in agent.astream_events(input_, config=config, version="v2"):
        translated = translator.translate(raw_event)
        if translated is not None:
            on_event(translated if translated.role == run_name else replace(translated, role=run_name))
        if raw_event.get("event") == "on_chain_end" and raw_event.get("name") == "LangGraph":
            final_output = raw_event["data"].get("output")
    response_text = final_output["messages"][-1].content if final_output else ""
    return RoleResult(run_name=run_name, response_text=response_text)
