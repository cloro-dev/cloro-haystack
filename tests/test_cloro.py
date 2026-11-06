"""Offline tests for cloro-haystack.

All HTTP goes through an httpx.MockTransport, so no test calls the cloro API.
The fixtures are shortened copies of real cloro API responses.
"""

import asyncio
import copy
import json
from pathlib import Path

import httpx
import pytest
from haystack import Document, Pipeline
from haystack.components.builders import AnswerBuilder
from haystack.utils import Secret

from haystack_integrations.components.websearch.cloro import CloroAIAnswer, CloroError, CloroWebSearch, _api
from haystack_integrations.components.websearch.cloro._api import is_direct_link

FIXTURES = Path(__file__).parent / "fixtures"


def _load(name):
    return json.loads((FIXTURES / name).read_text())


@pytest.fixture(autouse=True)
def _env(monkeypatch):
    monkeypatch.setenv("CLORO_API_KEY", "test-key")


@pytest.fixture
def api(monkeypatch):
    """Route every cloro request to a handler that returns `api.response`."""
    state = {"calls": [], "response": httpx.Response(200, json={"success": True, "result": {}})}

    def handler(request):
        state["calls"].append(request)
        response = state["response"]
        if isinstance(response, Exception):
            raise response
        return response

    transport = httpx.MockTransport(handler)
    real_async_client = httpx.AsyncClient
    monkeypatch.setattr(_api.httpx, "post", lambda url, **kw: httpx.Client(transport=transport).post(url, **kw))
    monkeypatch.setattr(_api.httpx, "AsyncClient", lambda **kw: real_async_client(transport=transport, **kw))

    class Api:
        @property
        def calls(self):
            return state["calls"]

        def respond(self, response):
            state["response"] = response

    return Api()


def _body(request):
    return json.loads(request.content)


# CloroWebSearch


def test_websearch_request(api):
    api.respond(httpx.Response(200, json=_load("google_aioverview.json")))
    CloroWebSearch().run(query="rank tracker")
    request = api.calls[0]
    assert str(request.url) == "https://api.cloro.dev/v1/monitor/google"
    assert request.headers["Authorization"] == "Bearer test-key"
    assert _body(request) == {"query": "rank tracker", "country": "US"}


def test_websearch_documents_and_links(api):
    api.respond(httpx.Response(200, json=_load("google_aioverview.json")))
    result = CloroWebSearch().run(query="rank tracker")
    assert len(result["documents"]) == 4
    assert result["links"] == [d.meta["link"] for d in result["documents"]]
    first = result["documents"][0]
    assert first.meta == {
        "title": "The 12 best rank tracker tools",
        "link": "https://zapier.com/blog/best-rank-tracker/",
        "position": 1,
    }
    assert first.content.startswith("Nov 27, 2024")
    assert all("google.com/goto" not in link for link in result["links"])


def test_websearch_ai_overview_first(api):
    payload = _load("google_aioverview.json")
    api.respond(httpx.Response(200, json=payload))
    result = CloroWebSearch(include_ai_overview=True).run(query="rank tracker")
    assert _body(api.calls[0])["include"] == {"aioverview": True}
    overview = result["documents"][0]
    assert overview.content == payload["result"]["aioverview"]["text"]
    assert overview.meta["source"] == "google_ai_overview"
    assert overview.meta["links"] == [s["url"] for s in payload["result"]["aioverview"]["sources"]]
    assert len(result["documents"]) == 5
    assert len(result["links"]) == 4


def test_websearch_ai_overview_ignored_when_not_requested(api):
    api.respond(httpx.Response(200, json=_load("google_aioverview.json")))
    result = CloroWebSearch().run(query="q")
    assert all(d.meta.get("source") != "google_ai_overview" for d in result["documents"])


def test_websearch_top_k_domains_and_params(api):
    api.respond(httpx.Response(200, json=_load("google_aioverview.json")))
    search = CloroWebSearch(
        top_k=2, country="DE", allowed_domains=["a.com", "b.org"], search_params={"device": "mobile", "pages": 2}
    )
    result = search.run(query="q")
    assert _body(api.calls[0]) == {
        "query": "q site:a.com OR site:b.org",
        "country": "DE",
        "device": "mobile",
        "pages": 2,
    }
    assert len(result["documents"]) == 2
    assert len(result["links"]) == 2


def test_websearch_run_async(api):
    api.respond(httpx.Response(200, json=_load("google_aioverview.json")))
    result = asyncio.run(CloroWebSearch().run_async(query="q"))
    assert len(result["documents"]) == 4


# CloroAIAnswer


@pytest.mark.parametrize("engine", ["chatgpt", "aimode", "gemini"])
def test_ai_answer_request(api, engine):
    api.respond(httpx.Response(200, json=_load("aimode.json")))
    CloroAIAnswer(engine=engine).run(query="rank tracker")
    request = api.calls[0]
    assert str(request.url) == f"https://api.cloro.dev/v1/monitor/{engine}"
    assert _body(request) == {"prompt": "rank tracker", "country": "US", "include": {"markdown": True}}


def test_ai_answer_rejects_other_engines():
    with pytest.raises(ValueError, match="engine"):
        CloroAIAnswer(engine="other")  # type: ignore[arg-type]


def test_ai_answer_output(api):
    payload = _load("aimode.json")
    api.respond(httpx.Response(200, json=payload))
    result = CloroAIAnswer().run(query="rank tracker")
    assert result["replies"] == [payload["result"]["markdown"]]
    sources = payload["result"]["sources"]
    assert result["links"] == [s["url"] for s in sources]
    assert result["documents"][0].meta == {"title": sources[0]["label"], "link": sources[0]["url"], "position": 1}
    assert result["documents"][0].content == sources[0]["description"]


def test_ai_answer_chatgpt_without_markdown_or_description(api):
    payload = _load("chatgpt.json")
    api.respond(httpx.Response(200, json=payload))
    result = CloroAIAnswer(engine="chatgpt").run(query="q")
    assert result["replies"] == [payload["result"]["text"]]
    assert result["documents"][0].content == payload["result"]["sources"][0]["label"]


def test_ai_answer_run_async(api):
    api.respond(httpx.Response(200, json=_load("aimode.json")))
    result = asyncio.run(CloroAIAnswer().run_async(query="q"))
    assert len(result["replies"]) == 1


def test_ai_answer_connects_to_answer_builder(api):
    api.respond(httpx.Response(200, json=_load("aimode.json")))
    pipe = Pipeline()
    pipe.add_component("ai", CloroAIAnswer())
    pipe.add_component("answer", AnswerBuilder())
    pipe.connect("ai.replies", "answer.replies")
    pipe.connect("ai.documents", "answer.documents")
    result = pipe.run({"ai": {"query": "rank tracker"}, "answer": {"query": "rank tracker"}})
    answer = result["answer"]["answers"][0]
    assert answer.data
    assert all(isinstance(d, Document) for d in answer.documents)


# Errors


@pytest.mark.parametrize("component", [CloroWebSearch(), CloroAIAnswer()])
@pytest.mark.parametrize(
    ("response", "match"),
    [
        (httpx.Response(401, json=_load("error_401.json")), "INVALID_API_KEY_FORMAT"),
        (
            httpx.Response(403, json={"success": False, "error": {"code": "INSUFFICIENT_CREDITS"}}),
            "INSUFFICIENT_CREDITS",
        ),
        (httpx.Response(502, text="Bad gateway"), "HTTP 502"),
        (httpx.Response(200, json={"success": True, "result": None}), "no result"),
        (httpx.ConnectError("down"), "failed"),
    ],
)
def test_errors_raise_cloro_error(api, component, response, match):
    api.respond(response)
    with pytest.raises(CloroError, match=match):
        component.run(query="q")


def test_timeout_raises_timeout_error(api):
    api.respond(httpx.ReadTimeout("slow"))
    with pytest.raises(TimeoutError):
        CloroWebSearch().run(query="q")


def test_error_message_has_no_key(api):
    api.respond(httpx.Response(401, json=_load("error_401.json")))
    with pytest.raises(CloroError) as info:
        CloroWebSearch().run(query="q")
    assert "test-key" not in str(info.value)


# Serialization


@pytest.mark.parametrize(
    "component",
    [
        CloroWebSearch(top_k=3, country="GB", include_ai_overview=True, search_params={"device": "mobile"}),
        CloroAIAnswer(engine="gemini", country="FR"),
    ],
)
def test_to_dict_from_dict_round_trip(component):
    data = component.to_dict()
    assert data["init_parameters"]["api_key"] == {"type": "env_var", "env_vars": ["CLORO_API_KEY"], "strict": True}
    assert "test-key" not in json.dumps(data)
    restored = type(component).from_dict(copy.deepcopy(data))
    assert restored.to_dict() == data


def test_token_secret_is_not_serializable():
    with pytest.raises(ValueError):
        CloroWebSearch(api_key=Secret.from_token("test-key")).to_dict()


def test_google_search_and_shopping_links_are_not_sources():
    assert is_direct_link("https://aws.amazon.com/what-is/retrieval-augmented-generation/")
    assert not is_direct_link("https://www.google.com/search?q=product&ibp=oshop")
    assert not is_direct_link("https://www.google.com/goto?url=x")
    assert not is_direct_link("")
