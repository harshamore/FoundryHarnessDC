"""Optional Galileo AI tracing -- automatic-only scope: a `GalileoCallback`
attached to every `create_deep_agent(...).invoke()` call, capturing the
LLM-call / tool-call / subagent-delegation hierarchy DeepAgents already
produces through LangChain's own callback system. No changes to any
Substrate or role store -- this is purely additive at the agent-invocation
edges, deliberately, so it can never affect anything the constitution
mapping actually enforces (see docs/OBSERVABILITY.md).

Strictly opt-in and fails soft: `build_galileo_callback()` returns `None`
whenever `GALILEO_API_KEY` isn't set, and never raises if Galileo itself is
unreachable or misconfigured. This is a deliberate asymmetry with the rest
of the build -- a broken OpenAI key is allowed to raise (it's the actual
work failing), but tracing is peripheral instrumentation, not core harness
function, so a misconfigured or unreachable Galileo account degrades to
"no tracing" rather than aborting a detection run. `pytest tests/` and the
local quickstart keep needing zero external services either way, matching
every other optional piece of this build.
"""
from __future__ import annotations

import os
from typing import Any

DEFAULT_PROJECT = "foundry-harness"
DEFAULT_LOG_STREAM = "colab"


def build_galileo_callback(project: str = DEFAULT_PROJECT, log_stream: str = DEFAULT_LOG_STREAM) -> Any | None:
    """A configured `GalileoCallback` ready to pass to `galileo_run_config()`,
    or `None` if tracing isn't configured or isn't reachable.

    Constructing a `GalileoLogger` makes a real network call (it gets-or-
    creates `project`/`log_stream` by name against the Galileo backend), so
    this is intentionally guarded: no `GALILEO_API_KEY` means no import and
    no network attempt at all, and any failure once a key IS set (bad key,
    unreachable console, package not installed) is caught and reported,
    not raised.
    """
    if not os.environ.get("GALILEO_API_KEY"):
        return None

    try:
        from galileo import GalileoLogger
        from galileo.handlers.langchain import GalileoCallback
    except ImportError:
        print(
            "GALILEO_API_KEY is set but the `galileo` package isn't installed "
            "(pip install -e '.[observability]') -- continuing without tracing."
        )
        return None

    try:
        logger = GalileoLogger(project=project, log_stream=log_stream)
        callback = GalileoCallback(galileo_logger=logger)
        # GalileoCallback buries the logger inside a private `_handler`
        # attribute -- attach our own public reference so console_url()
        # below doesn't have to reach into another library's internals.
        callback.galileo_logger = logger
        return callback
    except Exception as e:  # noqa: BLE001 -- any Galileo-side failure must not break a detection run
        print(f"Galileo tracing unavailable ({type(e).__name__}: {e}) -- continuing without it.")
        return None


def galileo_run_config(callback: Any | None, run_name: str | None = None) -> dict | None:
    """The `config=` argument for one `agent.invoke()` call: includes the
    Galileo callback (each invocation becomes its own trace -- `GalileoCallback`
    defaults to `start_new_trace=True`) and an optional `run_name` so the
    role shows up legibly in the Galileo console instead of anonymously.
    Returns `None` when tracing isn't configured, which LangChain treats
    identically to not passing `config=` at all."""
    if callback is None:
        return None
    config: dict = {"callbacks": [callback]}
    if run_name:
        config["run_name"] = run_name
    return config


def console_url(callback: Any | None) -> str | None:
    """A direct link to this run's project/log stream in the Galileo
    console, or `None` if tracing isn't configured. Built from the
    underlying `GalileoLogger`'s own `project_id`/`log_stream_id` (set
    during construction), not fabricated -- matches the URL shape Galileo's
    own SDK logs internally."""
    if callback is None:
        return None
    logger = getattr(callback, "galileo_logger", None)
    project_id = getattr(logger, "project_id", None)
    log_stream_id = getattr(logger, "log_stream_id", None)
    if not (project_id and log_stream_id):
        return None
    return f"https://app.galileo.ai/project/{project_id}/log-streams/{log_stream_id}"
