# SPDX-FileCopyrightText: 2026-present cloro <support@cloro.dev>
#
# SPDX-License-Identifier: MIT

from typing import Any, Literal

from haystack import Document, component, default_from_dict, default_to_dict, logging
from haystack.utils import Secret, deserialize_secrets_inplace

from haystack_integrations.components.websearch.cloro._api import is_direct_link, post, post_async

logger = logging.getLogger(__name__)

Engine = Literal["chatgpt", "aimode", "gemini"]


@component
class CloroAIAnswer:
    """
    Gets the answer that an AI search engine gives to a query, with the sources it cites.

    The component sends the query to ChatGPT, Google AI Mode or Gemini through the
    [cloro](https://cloro.dev/?utm_source=cloro-haystack&utm_medium=byok) API.
    `replies` has the answer as Markdown. `documents` has one
    Document for each cited source, with `title`, `link` and `position` in its meta.
    The output names match `AnswerBuilder`, so you can connect the component to it directly.

    ### Usage example

    ```python
    from haystack_integrations.components.websearch.cloro import CloroAIAnswer

    ai_answer = CloroAIAnswer(engine="aimode")
    result = ai_answer.run(query="What is retrieval-augmented generation?")
    print(result["replies"][0])
    print(result["links"])
    ```
    """

    def __init__(
        self,
        api_key: Secret = Secret.from_env_var("CLORO_API_KEY"),
        engine: Engine = "aimode",
        country: str = "US",
        search_params: dict[str, Any] | None = None,
        timeout: float = 180.0,
    ) -> None:
        """
        Initialize the CloroAIAnswer component.

        :param api_key:
            cloro API key. Defaults to the `CLORO_API_KEY` environment variable.
        :param engine:
            The AI search engine: `"chatgpt"`, `"aimode"` (Google AI Mode) or `"gemini"`.
        :param country:
            ISO 3166-1 alpha-2 country code for the engine location.
        :param search_params:
            Other fields for the `POST /v1/monitor/<engine>` request body. See the cloro API reference.
        :param timeout:
            Request timeout in seconds. An answer can take 15 to 60 seconds.
        """
        if engine not in ("chatgpt", "aimode", "gemini"):
            msg = f"engine must be 'chatgpt', 'aimode' or 'gemini', not {engine!r}"
            raise ValueError(msg)
        self.api_key = api_key
        self.engine = engine
        self.country = country
        self.search_params = search_params
        self.timeout = timeout

    def to_dict(self) -> dict[str, Any]:
        """
        Serialize the component to a dictionary.

        :returns: Dictionary with serialized data.
        """
        return default_to_dict(
            self,
            api_key=self.api_key.to_dict(),
            engine=self.engine,
            country=self.country,
            search_params=self.search_params,
            timeout=self.timeout,
        )

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "CloroAIAnswer":
        """
        Deserialize the component from a dictionary.

        :param data: Dictionary to deserialize from.
        :returns: Deserialized component.
        """
        deserialize_secrets_inplace(data["init_parameters"], keys=["api_key"])
        return default_from_dict(cls, data)

    @component.output_types(replies=list[str], documents=list[Document], links=list[str])
    def run(self, query: str) -> dict[str, Any]:
        """
        Get the AI search engine answer for a query.

        :param query: The prompt to send to the engine.
        :returns: A dictionary with:
            - `replies`: A list with the answer as Markdown.
            - `documents`: One Document for each cited source.
            - `links`: The URLs of the cited sources.
        :raises TimeoutError: If the request times out.
        :raises CloroError: If the cloro API returns an error.
        """
        result = post(self._path(), self._payload(query), self.api_key, self.timeout)
        return self._parse(result)

    @component.output_types(replies=list[str], documents=list[Document], links=list[str])
    async def run_async(self, query: str) -> dict[str, Any]:
        """
        Get the AI search engine answer for a query without blocking.

        This is the asynchronous version of `run`, with the same parameters and return values.

        :param query: The prompt to send to the engine.
        :returns: A dictionary with:
            - `replies`: A list with the answer as Markdown.
            - `documents`: One Document for each cited source.
            - `links`: The URLs of the cited sources.
        :raises TimeoutError: If the request times out.
        :raises CloroError: If the cloro API returns an error.
        """
        result = await post_async(self._path(), self._payload(query), self.api_key, self.timeout)
        return self._parse(result)

    def _path(self) -> str:
        return f"/v1/monitor/{self.engine}"

    def _payload(self, query: str) -> dict[str, Any]:
        payload: dict[str, Any] = {"prompt": query, "country": self.country, **(self.search_params or {})}
        include = dict(payload.get("include") or {})
        include["markdown"] = True
        payload["include"] = include
        return payload

    def _parse(self, result: dict[str, Any]) -> dict[str, Any]:
        answer = result.get("markdown") or result.get("text") or ""
        documents: list[Document] = []
        links: list[str] = []
        for source in result.get("sources") or []:
            url = source.get("url") if isinstance(source, dict) else None
            if not is_direct_link(url) or url in links:
                continue
            links.append(url)
            documents.append(
                Document(
                    content=source.get("description") or source.get("label") or "",
                    meta={"title": source.get("label") or "", "link": url, "position": source.get("position")},
                )
            )
        logger.debug("cloro {engine} returned {count} sources", engine=self.engine, count=len(documents))
        return {"replies": [answer] if answer else [], "documents": documents, "links": links}
