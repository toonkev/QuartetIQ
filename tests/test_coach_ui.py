"""Mocked Streamlit chat interaction tests; no live provider requests."""
from contextlib import nullcontext
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

from openai.types.chat import ChatCompletion
from streamlit.testing.v1 import AppTest
import streamlit as st

import quartetiq.coach_ui as ui
from quartetiq.dashboard import load_demo
from quartetiq.muse import CoachError

ROOT = Path(__file__).resolve().parents[1]


def fake_client():
    def response(content=None, calls=None):
        return ChatCompletion(id="mock-ui", model="muse-spark-1.3", created=0, object="chat.completion",
            choices=[{"index": 0, "finish_reason": "tool_calls" if calls else "stop",
                      "message": {"role": "assistant", "content": content, "tool_calls": calls}}])
    call = {"id": "ui_call", "type": "function", "function": {"name": "get_practice_priorities", "arguments": "{}"}}
    create = Mock(side_effect=[response(calls=[call]), response("Measure 1 G4 is about 30 cents sharp in take 3. Practise slowly with a drone.")])
    return SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create)))


def test_unconfigured_coach_does_not_break_dashboard(monkeypatch):
    monkeypatch.setattr(ui, "get_api_key", lambda _: None)
    app = AppTest.from_file(str(ROOT / "app.py"), default_timeout=30).run()
    assert not app.exception
    assert [tab.label for tab in app.tabs] == ["Rehearsal dashboard", "AI Coach"]
    assert app.chat_input[0].disabled
    assert any("MODEL_API_KEY" in msg.value for msg in app.info)
    assert len(app.metric) == 4
    assert not app.chat_message


def test_chat_history_and_stale_upload_reset(monkeypatch):
    st.cache_data.clear()
    monkeypatch.setattr(ui, "get_api_key", lambda _: "test-only")
    client = fake_client()
    monkeypatch.setattr(ui, "create_client", lambda _: nullcontext(client))
    app = AppTest.from_file(str(ROOT / "app.py"), default_timeout=30).run()
    app.chat_input[0].set_value("Which measures should I practice next?").run()
    assert not app.exception
    assert len(app.chat_message) == 2
    assert "30 cents" in app.chat_message[1].markdown[0].value
    assert client.chat.completions.create.call_count == 2
    app.run()
    assert len(app.chat_message) == 2
    assert client.chat.completions.create.call_count == 2
    app.radio[0].set_value("Upload my recordings").run()
    app.radio[0].set_value("Try the demo").run()
    assert not app.chat_message  # No earlier dataset conversation restored.
    st.cache_data.clear()


def test_chat_api_error_is_visible_without_fake_answer(monkeypatch):
    monkeypatch.setattr(ui, "get_api_key", lambda _: "test-only")
    monkeypatch.setattr(ui, "create_client", lambda _: nullcontext(object()))
    def fail(*args, **kwargs):
        raise CoachError("Meta authentication failed. Check MODEL_API_KEY and access to Muse Spark 1.3.")
    monkeypatch.setattr(ui, "answer_question", fail)
    app = AppTest.from_file(str(ROOT / "app.py"), default_timeout=30).run()
    app.chat_input[0].set_value("Help me practise").run()
    assert not app.exception
    assert any("authentication failed" in msg.value for msg in app.error)
    assert not app.chat_message


def test_measurement_change_resets_history(monkeypatch):
    import quartetiq.dashboard as dashboard
    st.cache_data.clear()
    manifest, results = load_demo(ROOT / "demo")
    monkeypatch.setattr(dashboard, "load_demo", lambda _: (manifest, results))
    monkeypatch.setattr(ui, "get_api_key", lambda _: "test-only")
    monkeypatch.setattr(ui, "create_client", lambda _: nullcontext(fake_client()))
    app = AppTest.from_file(str(ROOT / "app.py"), default_timeout=30).run()
    app.chat_input[0].set_value("What next?").run()
    assert len(app.chat_message) == 2
    results[0]["notes"][0]["cents_deviation"] = 25
    st.cache_data.clear()
    app.run()
    assert not app.exception
    assert not app.chat_message
    st.cache_data.clear()
