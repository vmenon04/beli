"""Exceptions raised by the client."""

from __future__ import annotations

import httpx
from pydantic import ValidationError

from ._version import __version__

ISSUES_URL = "https://github.com/vmenon04/beli/issues"


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


class UnexpectedResponseError(BeliError):
    """The API answered, but not in a form this version of the package can read.

    Beli's API is private and changes without notice, so this usually means a
    field was renamed, removed or changed type. ``problem`` says what did not
    fit, by field name and error type only: neither it nor the message quotes
    the response. The original exception is chained as ``__cause__``.
    """

    def __init__(self, method: str, path: str, problem: str) -> None:
        self.method = method
        self.path = path
        self.problem = problem
        super().__init__(
            f"{method} {path} answered in a form beli {__version__} does not understand "
            f"({problem}). Beli's API has probably changed: upgrade beli, and if that "
            f"does not help, report it at {ISSUES_URL}"
        )


def describe_parse_failure(exc: Exception) -> str:
    """What went wrong while reading a response, without quoting any of it."""
    if isinstance(exc, ValidationError):
        errors = exc.errors(include_input=False, include_url=False, include_context=False)
        where = [f"{'.'.join(str(p) for p in e['loc'])} ({e['type']})" for e in errors[:20]]
        more = f" and {len(errors) - 20} more" if len(errors) > 20 else ""
        return f"{exc.title} does not validate: {', '.join(where)}{more}"
    return type(exc).__name__


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
