"""Exceptions raised by the client."""

from __future__ import annotations

import httpx


class BeliError(Exception):
    """Base class for every error this package raises."""


class AuthenticationError(BeliError):
    """Login failed, or no usable credentials are left."""


class APIError(BeliError):
    """The API answered with an error status."""

    def __init__(self, response: httpx.Response) -> None:
        self.response = response
        self.status_code = response.status_code
        body = response.text.strip()
        self.body = body
        snippet = body[:200] + ("..." if len(body) > 200 else "")
        super().__init__(
            f"{response.request.method} {response.request.url.path} "
            f"returned HTTP {self.status_code}: {snippet}"
        )


class BadRequestError(APIError):
    """HTTP 400. Usually a missing query parameter."""


class PermissionDeniedError(APIError):
    """HTTP 403. Often a missing Origin or User-Agent header, or a private profile."""


class NotFoundError(APIError):
    """HTTP 404."""


class RateLimitError(APIError):
    """HTTP 429 after all retries were used up."""


class ServerError(APIError):
    """HTTP 5xx after all retries were used up."""


def error_for(response: httpx.Response) -> APIError:
    status = response.status_code
    if status == 400:
        return BadRequestError(response)
    if status == 403:
        return PermissionDeniedError(response)
    if status == 404:
        return NotFoundError(response)
    if status == 429:
        return RateLimitError(response)
    if status >= 500:
        return ServerError(response)
    return APIError(response)
