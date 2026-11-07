# cloro-haystack

[Haystack](https://haystack.deepset.ai) components for
[cloro](https://cloro.dev/?utm_source=cloro-haystack&utm_medium=byok).

| Component | cloro endpoint | Output | Credits per run |
|---|---|---|--:|
| `CloroWebSearch` | `POST /v1/monitor/google` | `documents` and `links` from Google organic results. With `include_ai_overview=True`, the Google AI Overview is the first Document. | 5, or 7 with the AI Overview |
| `CloroAIAnswer` | `POST /v1/monitor/chatgpt`, `/aimode`, `/gemini` or `/bing/aimode` | `replies` (the answer as Markdown), `documents` and `links` (the cited sources) | ChatGPT 7, Google AI Mode 6, Gemini 6, Bing AI Mode 6 |

## Installation

```bash
pip install cloro-haystack
```

Get an API key at [dashboard.cloro.dev](https://dashboard.cloro.dev/api-keys?utm_source=cloro-haystack&utm_medium=byok).
The free plan includes 500 credits each month. Set the key as `CLORO_API_KEY`, or pass
`api_key=Secret.from_token(...)`.

## Usage

### CloroWebSearch

```python
from haystack_integrations.components.websearch.cloro import CloroWebSearch

websearch = CloroWebSearch(top_k=5, country="US", include_ai_overview=True)
result = websearch.run(query="What is retrieval-augmented generation?")

for doc in result["documents"]:
    print(doc.meta.get("title"), doc.meta.get("link"))
```

Each organic result is a `Document`. Its `content` is the Google snippet and its `meta` has `title`,
`link` and `position`. The AI Overview Document has `meta["source"] == "google_ai_overview"` and the
URLs it cites in `meta["links"]`. Results with an empty link or a Google redirect link are skipped.

Parameters:

- `api_key`: defaults to the `CLORO_API_KEY` environment variable.
- `top_k`: maximum number of organic results. Defaults to 10. One request returns one page of Google
  results (about 10). Set `search_params={"pages": 2}` for more (2 credits for each extra page).
- `country`: ISO 3166-1 alpha-2 country code. Defaults to `"US"`.
- `allowed_domains`: domains to limit the search to, sent as `site:` filters.
- `include_ai_overview`: request the Google AI Overview. Defaults to `False`.
- `search_params`: other request fields, for example `device`, `location`, `hl` or `pages`.
- `timeout`: request timeout in seconds. Defaults to 60.

### CloroAIAnswer

```python
from haystack_integrations.components.websearch.cloro import CloroAIAnswer

ai_answer = CloroAIAnswer(engine="aimode")  # "chatgpt", "aimode", "gemini" or "bing_aimode"
result = ai_answer.run(query="What is retrieval-augmented generation?")

print(result["replies"][0])
print(result["links"])
```

`replies` has one string: the answer as Markdown. `documents` has one `Document` for each source that
the answer cites, with `title`, `link` and `position` in `meta`. An answer can take 15 to 60 seconds,
so the default `timeout` is 180 seconds.

With `engine="bing_aimode"`, the query can have a maximum of 3,500 characters after URL encoding,
and fewer for non-Latin scripts. To send the query from a US state, set
`search_params={"state": "CA"}` with `country="US"` (2 more credits).

### In a pipeline

The output names of `CloroAIAnswer` match `AnswerBuilder`:

```python
from haystack import Pipeline
from haystack.components.builders import AnswerBuilder
from haystack_integrations.components.websearch.cloro import CloroAIAnswer

pipe = Pipeline()
pipe.add_component("ai", CloroAIAnswer(engine="chatgpt"))
pipe.add_component("answer", AnswerBuilder())
pipe.connect("ai.replies", "answer.replies")
pipe.connect("ai.documents", "answer.documents")

query = "Which vector databases support hybrid search?"
result = pipe.run({"ai": {"query": query}, "answer": {"query": query}})
print(result["answer"]["answers"][0].data)
```

`CloroWebSearch` connects like the other Haystack web search components, for example to a
`ChatPromptBuilder` through `documents`, or to a fetcher through `links`.

Both components have `run_async` for `AsyncPipeline`.

### Errors

A cloro error response raises `CloroError` with the cloro error code, for example
`INVALID_API_KEY_FORMAT` (401), `INSUFFICIENT_CREDITS` (403) or `CONCURRENCY_LIMIT_EXCEEDED` (429).
A timeout raises `TimeoutError`.

## Development

```bash
uv sync
uv run pytest
uv run ruff check . && uv run ruff format --check .
uv run mypy src
uv build
```

The tests use `httpx.MockTransport` and do not call the cloro API.

## License

MIT
