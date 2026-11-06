# SPDX-FileCopyrightText: 2026-present cloro <support@cloro.dev>
#
# SPDX-License-Identifier: MIT

from typing import Any

from haystack import Document, component, default_from_dict, default_to_dict, logging
from haystack.utils import Secret, deserialize_secrets_inplace

from haystack_integrations.components.websearch.cloro._api import is_direct_link, post, post_async

logger = logging.getLogger(__name__)

GOOGLE_PATH = "/v1/monitor/google"


@component
class CloroWebSearch:
    """
    Searches Google with the cloro API and returns the results as Documents.

    cloro: https://cloro.dev/?utm_source=cloro-haystack&utm_medium=byok

    Each organic result becomes a Document. Its content is the Google snippet. Its meta has
    `title`, `link` and `position`. With `include_ai_overview=True`, the Google AI Overview
    (when Google shows one) is the first Document.

    ### Usage example

    ```python
    from haystack_integrations.components.websearch.cloro import CloroWebSearch

    websearch = CloroWebSearch(top_k=5, include_ai_overview=True)
    result = websearch.run(query="What is retrieval-augmented generation?")
    documents = result["documents"]
    links = result["links"]
    ```
    """

    def __init__(
        self,
        api_key: Secret = Secret.from_env_var("CLORO_API_KEY"),
        top_k: int | None = 10,
        country: str = "US",
        allowed_domains: list[str] | None = None,
        include_ai_overview: bool = False,
        search_params: dict[str, Any] | None = None,
        timeout: float = 60.0,
    ) -> None:
        """
        Initialize the CloroWebSearch component.

        :param api_key:
            cloro API key. Defaults to the `CLORO_API_KEY` environment variable.
        :param top_k:
            Maximum number of organic results to return. One request returns one page of Google
            results (about 10). Set `search_params={"pages": 2}` or more to get more results.
        :param country:
            ISO 3166-1 alpha-2 country code for the Google location.
        :param allowed_domains:
            Domains to limit the search to. They are added to the query as `site:` filters.
        :param include_ai_overview:
            If True, request the Google AI Overview and return it as the first Document.
        :param search_params:
            Other fields for the `POST /v1/monitor/google` request body, for example `device`,
            `location`, `hl` or `pages`. See the cloro API reference.
        :param timeout:
            Request timeout in seconds.
        """
        self.api_key = api_key
        self.top_k = top_k
        self.country = country
        self.allowed_domains = allowed_domains
        self.include_ai_overview = include_ai_overview
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
            top_k=self.top_k,
            country=self.country,
            allowed_domains=self.allowed_domains,
            include_ai_overview=self.include_ai_overview,
            search_params=self.search_params,
            timeout=self.timeout,
        )

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "CloroWebSearch":
        """
        Deserialize the component from a dictionary.

        :param data: Dictionary to deserialize from.
        :returns: Deserialized component.
        """
        deserialize_secrets_inplace(data["init_parameters"], keys=["api_key"])
        return default_from_dict(cls, data)

    @component.output_types(documents=list[Document], links=list[str])
    def run(self, query: str) -> dict[str, Any]:
        """
        Search Google with cloro.

        :param query: Search query.
        :returns: A dictionary with:
            - `documents`: The AI Overview (if requested and present), then the organic results.
            - `links`: The links of the organic results.
        :raises TimeoutError: If the request times out.
        :raises CloroError: If the cloro API returns an error.
        """
        result = post(GOOGLE_PATH, self._payload(query), self.api_key, self.timeout)
        return self._parse(result)

    @component.output_types(documents=list[Document], links=list[str])
    async def run_async(self, query: str) -> dict[str, Any]:
        """
        Search Google with cloro without blocking.

        This is the asynchronous version of `run`, with the same parameters and return values.

        :param query: Search query.
        :returns: A dictionary with:
            - `documents`: The AI Overview (if requested and present), then the organic results.
            - `links`: The links of the organic results.
        :raises TimeoutError: If the request times out.
        :raises CloroError: If the cloro API returns an error.
        """
        result = await post_async(GOOGLE_PATH, self._payload(query), self.api_key, self.timeout)
        return self._parse(result)

    def _payload(self, query: str) -> dict[str, Any]:
        if self.allowed_domains:
            query = f"{query} " + " OR ".join(f"site:{domain}" for domain in self.allowed_domains)
        payload: dict[str, Any] = {"query": query, "country": self.country, **(self.search_params or {})}
        if self.include_ai_overview:
            include = dict(payload.get("include") or {})
            include["aioverview"] = True
            payload["include"] = include
        return payload

    def _parse(self, result: dict[str, Any]) -> dict[str, Any]:
        organic = [
            item
            for item in result.get("organicResults") or []
            if isinstance(item, dict) and is_direct_link(item.get("link"))
        ][: self.top_k]
        documents = [
            Document(
                content=item.get("snippet") or "",
                meta={"title": item.get("title") or "", "link": item["link"], "position": item.get("position")},
            )
            for item in organic
        ]
        links = [item["link"] for item in organic]

        overview = result.get("aioverview")
        if self.include_ai_overview and isinstance(overview, dict) and overview.get("text"):
            sources = [s["url"] for s in overview.get("sources") or [] if is_direct_link(s.get("url"))]
            documents.insert(
                0,
                Document(
                    content=overview["text"],
                    meta={"title": "Google AI Overview", "source": "google_ai_overview", "links": sources},
                ),
            )

        logger.debug("cloro returned {count} documents", count=len(documents))
        return {"documents": documents, "links": links}
