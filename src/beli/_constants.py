"""Hosts, headers and other values observed in the Beli app's traffic."""

from __future__ import annotations

HOST_API = "https://backoffice-service-t57o3dxfca-nn.a.run.app"
"""Main API host. Almost every endpoint lives here."""

HOST_ONBOARD = "https://backoffice-service-onboarding-t57o3dxfca-nn.a.run.app"
"""Login, token refresh and the logged-in user."""

HOST_RECS = "https://backoffice-service-recs-t57o3dxfca-nn.a.run.app"
"""Recommendation service."""

FALLBACK_HOSTS: dict[str, str] = {"api": HOST_API, "onboard": HOST_ONBOARD, "recs": HOST_RECS}
"""Service name to base URL, used until (and unless) discovery says otherwise."""

HOSTS_PATH = "/api/api-hosts/"
"""Where the app asks which hosts to use. Answered by the main API host."""

DISCOVERED_HOSTS: dict[str, str] = {"apiHost": "api", "recsHost": "recs"}
"""Field in the ``HOSTS_PATH`` response to the service it names.

The response has no field for the onboarding host, so that one is always the
hard-coded value. Its other fields (``priorityHost``, ``profileHost``,
``photoHost``, ...) are for services this package does not call.
"""

ORIGIN = "capacitor://localhost"
"""The app is a Capacitor webview. The API answers 403 without an Origin header."""

DEFAULT_USER_AGENT = (
    "Mozilla/5.0 (iPhone; CPU iPhone OS 18_7 like Mac OS X) "
    "AppleWebKit/605.1.15 (KHTML, like Gecko) Mobile/15E148"
)
"""The API also answers 403 to clients that don't send a browser-like User-Agent."""

GUIDE_FLAGS: dict[str, str] = {
    "supports_no_guide_category": "true",
    "supports_no_guide_city": "true",
    "supports_collab_guides": "true",
}
"""Without these flags the guide endpoints return empty lists."""

NOTES_FIELD = "NOTES"
"""EAV field name holding the written review text for a place."""

CATEGORY_NAMES: dict[str, str] = {
    "RES": "Restaurants",
    "BAR": "Bars",
    "DES": "Dessert",
    "BAK": "Bakeries",
    "COF": "Coffee & Tea",
}
"""Known category codes. The account's own list comes from ``Beli.categories()``."""
