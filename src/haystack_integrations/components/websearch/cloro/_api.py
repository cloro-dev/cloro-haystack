# SPDX-FileCopyrightText: 2026-present cloro <support@cloro.dev>
#
# SPDX-License-Identifier: MIT

from typing import Any, TypeGuard

import httpx
from haystack import ComponentError
from haystack.utils import Secret

CLORO_API_BASE = "https://api.cloro.dev"


class CloroError(ComponentError):
    """Raised when the cloro API returns an error or a response that cannot be read."""


def _headers(api_key: Secret) -> dict[str, str]:
    return {"Authorization": f"Bearer {api_key.resolve_value()}", "Content-Type": "application/json"}


def _result(response: httpx.Response, path: str) -> dict[str, Any]:
    try:
        data = response.json()
    except ValueError:
        data = None
    if response.is_error or not isinstance(data, dict) or not data.get("success"):
        error = data.get("error") if isinstance(data, dict) else None
        code = error.get("code") if isinstance(error, dict) else None
        message = error.get("message") if isinstance(error, dict) else None
        msg = f"cloro {path} returned HTTP {response.status_code}: {code or 'no error code'} {message or ''}".strip()
        raise CloroError(msg)
    result = data.get("result")
    if not isinstance(result, dict):
        msg = f"cloro {path} returned no result."
        raise CloroError(msg)
    return result


def post(path: str, payload: dict[str, Any], api_key: Secret, timeout: float) -> dict[str, Any]:
    """Send a POST request to the cloro API and return the `result` object."""
    try:
        response = httpx.post(f"{CLORO_API_BASE}{path}", json=payload, headers=_headers(api_key), timeout=timeout)
    except httpx.TimeoutException as error:
        msg = f"Request to cloro {path} timed out."
        raise TimeoutError(msg) from error
    except httpx.HTTPError as error:
        msg = f"Request to cloro {path} failed: {error}"
        raise CloroError(msg) from error
    return _result(response, path)


async def post_async(path: str, payload: dict[str, Any], api_key: Secret, timeout: float) -> dict[str, Any]:
    """Send a POST request to the cloro API without blocking and return the `result` object."""
    try:
        async with httpx.AsyncClient() as client:
            response = await client.post(
                f"{CLORO_API_BASE}{path}", json=payload, headers=_headers(api_key), timeout=timeout
            )
    except httpx.TimeoutException as error:
        msg = f"Request to cloro {path} timed out."
        raise TimeoutError(msg) from error
    except httpx.HTTPError as error:
        msg = f"Request to cloro {path} failed: {error}"
        raise CloroError(msg) from error
    return _result(response, path)


def is_direct_link(url: Any) -> TypeGuard[str]:
    """Return True for an http(s) link that is not a Google redirect (/goto) or a Google search page (/search)."""
    return (
        isinstance(url, str)
        and url.startswith(("http://", "https://"))
        and "google.com/goto" not in url
        and "google.com/search" not in url
    )
