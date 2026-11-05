"""Mock protocol tests are NOT evidence of live Meta connectivity."""
from copy import deepcopy
import inspect
import json
from types import SimpleNamespace
from unittest.mock import Mock

import httpx
import pytest
from openai import (AuthenticationError, PermissionDeniedError, APIConnectionError,
                    APITimeoutError, RateLimitError, APIStatusError)
from openai.types.chat import ChatCompletion

from quartetiq import muse
from quartetiq.dashboard import load_demo
from pathlib import Path


@pytest.fixture
def results():
    return load_demo(Path(__file__).resolve().parents[1] / "demo")[1]


def completion(content=None, calls=None, reason=None):
    return ChatCompletion(id="mock", created=0, model=muse.MODEL, object="chat.completion",
                          choices=[{"index": 0, "finish_reason": reason or ("tool_calls" if calls else "stop"),
                                    "message": {"role": "assistant", "content": content, "tool_calls": calls}}])


def call(name="get_practice_priorities", args="{}", id="call_1"):
    return {"id": id, "type": "function", "function": {"name": name, "arguments": args}}


def fake_client(*responses):
    return SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=Mock(side_effect=responses))))


def test_schemas_match_actual_signatures():
    from jsonschema import Draft202012Validator
    schemas = muse.tool_definitions()
    assert len(schemas) == 5
    for tool in schemas:
        function = tool["function"]
        schema = function["parameters"]
        Draft202012Validator.check_schema(schema)
        signature = inspect.signature(muse.ALLOWED_TOOLS[function["name"]])
        assert set(schema["properties"]) == set(signature.parameters) - {"results"}
        assert schema["additionalProperties"] is False
        Draft202012Validator(schema).validate({})


@pytest.mark.parametrize("name", list(muse.ALLOWED_TOOLS))
def test_dispatch_and_json_results(results, name):
    args = {"measure": 1} if name == "get_measure_analysis" else {}
    before = deepcopy(results)
    data = json.loads(muse.execute_tool(name, json.dumps(args), results, "dataset"))
    assert data == {"ok": True, "dataset_id": "dataset", "function": name,
                    "data": muse.ALLOWED_TOOLS[name](results, **args)}
    assert results == before


@pytest.mark.parametrize("name,args", [("eval", "{}"), ("get_performance_summary", "bad JSON"),
    ("compare_takes", "[]"), ("compare_takes", '{"results": []}'), ("compare_takes", '{"threshold_cents": true}'),
    ("compare_takes", '{"threshold_cents": 0}'), ("compare_takes", '{"threshold_cents": NaN}'),
    ("compare_takes", '{"threshold_cents": 1e999}'), ("compare_takes", '{"threshold_cents": 1, "threshold_cents": 2}'),
    ("get_measure_analysis", '{"measure": "1"}'), ("get_measure_analysis", '{"measure": true}'),
    ("get_persistent_errors", '{"measure": 1}'), ("compare_takes", "x" * 4097)])
def test_invalid_calls_are_safe(results, name, args):
    response = json.loads(muse.execute_tool(name, args, results, "dataset"))
    assert response["ok"] is False
    assert "data" not in response


def test_missing_credentials_and_precedence(monkeypatch):
    monkeypatch.delenv("MODEL_API_KEY", raising=False)
    assert muse.get_api_key(environ={}) is None
    assert muse.get_api_key({"MODEL_API_KEY": " secret "}, environ={}) == "secret"
    assert muse.get_api_key({"MODEL_API_KEY": "secret"}, environ={"MODEL_API_KEY": "env"}) == "env"
    with pytest.raises(muse.CoachError, match="requires MODEL_API_KEY"):
        muse.create_client()
    monkeypatch.setenv("MODEL_API_KEY", "test-only-key")
    factory = Mock()
    monkeypatch.setattr(muse, "OpenAI", factory)
    muse.create_client()
    assert factory.call_args.kwargs == {"base_url": muse.BASE_URL, "api_key": "test-only-key", "timeout": 45., "max_retries": 1}


@pytest.mark.parametrize("error_type", [AuthenticationError, PermissionDeniedError, APIConnectionError,
                                        APITimeoutError, RateLimitError, APIStatusError, RuntimeError])
def test_api_errors_never_leak_credentials(error_type):
    request = httpx.Request("POST", muse.BASE_URL + "/chat/completions")
    if error_type in (APIConnectionError, APITimeoutError):
        error = error_type(request=request)
    elif error_type is RuntimeError:
        error = RuntimeError("secret-key-in-provider-message")
    else:
        error = error_type("secret-key-in-provider-message", response=httpx.Response(401, request=request), body={"key": "secret"})
    with pytest.raises(muse.CoachError) as exc:
        muse.test_connectivity(fake_client(error))
    assert "secret" not in str(exc.value)
    assert exc.value.__suppress_context__


def test_connectivity_is_not_tool_proof():
    assert muse.test_connectivity(fake_client(completion("ready"))) == {
        "connected": True, "model": muse.MODEL, "tool_call_tested": False}


def test_multiple_calls_and_matching_results(results):
    client = fake_client(completion(calls=[call(), call("get_measure_analysis", '{"measure":1}', "call_2")]),
                         completion("Practice measure 1, G4, about 30 cents sharp in the latest take."))
    reply = muse.answer_question(client, results, "What next?")
    assert reply["tools_used"] == ["get_practice_priorities", "get_measure_analysis"]
    second = client.chat.completions.create.call_args_list[1].kwargs
    assert second["model"] == muse.MODEL
    assert second["tool_choice"] == "auto"
    messages = second["messages"]
    assert messages[-3]["role"] == "assistant"
    assert messages[-3]["tool_calls"][0]["id"] == "call_1"
    assert [m["tool_call_id"] for m in messages[-2:]] == ["call_1", "call_2"]
    assert json.loads(messages[-1]["content"])["data"][0]["measure"] == 1


def test_bad_tool_can_recover(results):
    client = fake_client(completion(calls=[call("bad")]), completion(calls=[call()]), completion("Measured answer"))
    reply = muse.answer_question(client, results, "What next?")
    assert reply["tools_used"] == ["get_practice_priorities"]
    tool = client.chat.completions.create.call_args_list[1].kwargs["messages"][-1]
    assert json.loads(tool["content"])["ok"] is False


def test_no_ungrounded_answer_or_infinite_loop(results):
    for response in (completion("Invented unsupported answer"), completion(calls=[call()])):
        client = fake_client(*[response for _ in range(3)])
        with pytest.raises(muse.CoachError):
            muse.answer_question(client, results, "What next?", max_rounds=2)
        assert client.chat.completions.create.call_count == 3


def test_history_atomicity_and_dataset_reset(results):
    first = muse.answer_question(fake_client(completion(calls=[call()]), completion("First answer")), results, "First question")
    history = deepcopy(first["conversation"])
    client = fake_client(completion(calls=[call("get_performance_summary")]), completion("Second answer"))
    second = muse.answer_question(client, results, "Follow-up", history)
    assert len(second["conversation"]["turns"]) == 2
    assert history == first["conversation"]
    assert any(m.get("content") == "First answer" for m in client.chat.completions.create.call_args_list[0].kwargs["messages"])
    changed = deepcopy(results)
    changed[0]["notes"][0]["cents_deviation"] = 25
    reset = muse.answer_question(fake_client(completion(calls=[call()]), completion("New dataset")), changed, "Now?", history)
    assert len(reset["conversation"]["turns"]) == 1
    assert reset["conversation"]["dataset_id"] != history["dataset_id"]
    with pytest.raises(muse.CoachError):
        muse.answer_question(fake_client(RuntimeError("secret")), results, "Retry", history)
    assert history == first["conversation"]


@pytest.mark.parametrize("response", [completion("truncated", reason="length"), completion(None),
                                      completion(calls=[call(), call()])])
def test_incomplete_protocol_fails_safely(results, response):
    with pytest.raises(muse.CoachError):
        muse.answer_question(fake_client(response), results, "Question", max_rounds=1)
