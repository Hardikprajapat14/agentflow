import httpx
import pytest

from app.config import Settings
from app.services import llm as llm_mod
from app.services.llm import LLMClient, LLMError


def make(**kw):
    return LLMClient(Settings(llm_api_key="k", llm_base_url="http://provider.test/v1", llm_max_retries=3, **kw))


def reply(content=None, tool_args=None):
    msg = {"role": "assistant", "content": content}
    if tool_args is not None:
        msg["tool_calls"] = [{"function": {"name": "t", "arguments": tool_args}}]
    return httpx.Response(200, json={"choices": [{"message": msg}]})


@pytest.fixture(autouse=True)
def no_sleep(monkeypatch):
    monkeypatch.setattr(llm_mod.time, "sleep", lambda *_: None)


def test_json_mode_request_shape_and_parsing(monkeypatch):
    seen = {}

    def post(url, json, headers, timeout):
        seen.update(url=url, json=json, headers=headers)
        return reply('```json\n{"ok": true}\n```')

    monkeypatch.setattr(httpx, "post", post)
    assert make().json([{"role": "user", "content": "return JSON"}]) == {"ok": True}
    assert seen["url"] == "http://provider.test/v1/chat/completions"
    assert seen["json"]["response_format"] == {"type": "json_object"}
    assert seen["headers"]["Authorization"] == "Bearer k"


def test_retries_on_rate_limit_then_succeeds(monkeypatch):
    calls = iter([httpx.Response(429, text="slow down", headers={"retry-after": "1"}), reply("hello")])
    monkeypatch.setattr(httpx, "post", lambda *a, **k: next(calls))
    assert make().chat([{"role": "user", "content": "hi"}])["content"] == "hello"


def test_fallback_model_used_when_primary_rate_limited(monkeypatch):
    models = []

    def post(url, json, headers, timeout):
        models.append(json["model"])
        return httpx.Response(429, text="limit") if json["model"] == "primary" else reply("from fallback")

    monkeypatch.setattr(httpx, "post", post)
    out = make(llm_model="primary", llm_fallback_model="backup").chat([{"role": "user", "content": "x"}])
    assert out["content"] == "from fallback" and models[-1] == "backup"


def test_client_errors_are_not_retried(monkeypatch):
    n = {"c": 0}

    def post(*a, **k):
        n["c"] += 1
        return httpx.Response(401, text="bad key")

    monkeypatch.setattr(httpx, "post", post)
    with pytest.raises(LLMError) as e:
        make().chat([{"role": "user", "content": "x"}])
    assert n["c"] == 1 and e.value.status == 401


def test_function_calling_returns_arguments(monkeypatch):
    seen = {}

    def post(url, json, headers, timeout):
        seen.update(json)
        return reply(None, tool_args='{"query": "discount policy", "top_k": 3}')

    monkeypatch.setattr(httpx, "post", post)
    args = make().call_tool([{"role": "user", "content": "x"}], "rag_search", "d", {"type": "object", "properties": {}})
    assert args == {"query": "discount policy", "top_k": 3}
    assert seen["tool_choice"]["function"]["name"] == "rag_search"


def test_missing_key_gives_actionable_error():
    with pytest.raises(LLMError, match="LLM_API_KEY"):
        LLMClient(Settings(llm_api_key="")).chat([{"role": "user", "content": "x"}])
