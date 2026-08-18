"""Tests for the optional Galileo AI tracing wrapper
(src/foundry/observability/galileo.py).

No real network calls: GalileoLogger/GalileoCallback are monkeypatched
with fakes when a positive-path test needs them, matching this build's own
"no external calls in tests" discipline. Requires the `galileo` package
(the `observability` extra) to be installed -- skips entirely otherwise,
since this integration is opt-in and `pytest tests/` must still pass with
only `[dev]` installed.
"""
from __future__ import annotations

import pytest

pytest.importorskip("galileo")

from foundry.observability.galileo import build_galileo_callback, console_url, galileo_run_config


class _FakeGalileoLogger:
    def __init__(self, project, log_stream):
        self.project = project
        self.log_stream = log_stream
        self.project_id = "proj-123"
        self.log_stream_id = "stream-456"


class _FakeGalileoCallback:
    def __init__(self, galileo_logger=None):
        self.galileo_logger = galileo_logger


class _FailingGalileoLogger:
    def __init__(self, project, log_stream):
        raise RuntimeError("simulated: bad key or unreachable console")


# ---------------------------------------------------------------------------
# build_galileo_callback
# ---------------------------------------------------------------------------


def test_returns_none_when_api_key_not_set(monkeypatch):
    monkeypatch.delenv("GALILEO_API_KEY", raising=False)
    assert build_galileo_callback() is None


def test_returns_configured_callback_when_key_set(monkeypatch):
    monkeypatch.setenv("GALILEO_API_KEY", "fake-key-for-testing")
    monkeypatch.setattr("galileo.GalileoLogger", _FakeGalileoLogger)
    monkeypatch.setattr("galileo.handlers.langchain.GalileoCallback", _FakeGalileoCallback)

    callback = build_galileo_callback(project="test-project", log_stream="test-stream")

    assert callback is not None
    assert callback.galileo_logger.project == "test-project"
    assert callback.galileo_logger.log_stream == "test-stream"


def test_returns_none_without_raising_when_construction_fails(monkeypatch, capsys):
    monkeypatch.setenv("GALILEO_API_KEY", "fake-key-for-testing")
    monkeypatch.setattr("galileo.GalileoLogger", _FailingGalileoLogger)
    monkeypatch.setattr("galileo.handlers.langchain.GalileoCallback", _FakeGalileoCallback)

    callback = build_galileo_callback()

    assert callback is None
    assert "Galileo tracing unavailable" in capsys.readouterr().out


# ---------------------------------------------------------------------------
# galileo_run_config
# ---------------------------------------------------------------------------


def test_galileo_run_config_none_when_callback_none():
    assert galileo_run_config(None) is None
    assert galileo_run_config(None, run_name="indexer") is None


def test_galileo_run_config_includes_callback_and_run_name():
    fake_callback = object()
    config = galileo_run_config(fake_callback, run_name="indexer")
    assert config == {"callbacks": [fake_callback], "run_name": "indexer"}


def test_galileo_run_config_omits_run_name_when_not_given():
    fake_callback = object()
    config = galileo_run_config(fake_callback)
    assert config == {"callbacks": [fake_callback]}


# ---------------------------------------------------------------------------
# console_url
# ---------------------------------------------------------------------------


def test_console_url_none_when_callback_none():
    assert console_url(None) is None


def test_console_url_builds_expected_link():
    fake_callback = _FakeGalileoCallback(galileo_logger=_FakeGalileoLogger("p", "s"))
    url = console_url(fake_callback)
    assert url == "https://app.galileo.ai/project/proj-123/log-streams/stream-456"


def test_console_url_none_when_ids_missing():
    fake_callback = _FakeGalileoCallback(galileo_logger=None)
    assert console_url(fake_callback) is None
