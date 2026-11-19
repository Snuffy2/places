"""Shared client and formatting helpers for the Places integration."""

from __future__ import annotations

import re
from typing import Any

from aioplaces import PlacesClient
from homeassistant.const import __version__ as ha_version
from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .const import (
    DOMAIN,
    OSM_CACHE_MAX_AGE_HOURS,
    OSM_CACHE_MAX_SIZE,
    OSM_THROTTLE_INTERVAL_SECONDS,
    PLACES_CLIENT,
    VERSION,
)


def is_float(value: Any) -> bool:
    """Return whether a value can be safely converted to ``float``.

    Args:
        value (Any):
            Candidate value to validate.

    Returns:
        bool:
            ``True`` when ``float(value)`` succeeds and ``value`` is not ``None``.
    """
    if value is None:
        return False
    try:
        float(value)
    except ValueError, TypeError:
        return False
    else:
        return True


def clear_since_from_state(orig_state: str) -> str:
    """Remove the Places ``(since HH:MM)`` or ``(since MM/DD)`` suffix.

    Args:
        orig_state (str):
            Sensor state that may include a trailing ``since`` suffix.

    Returns:
        str:
            State string without the generated suffix.
    """
    return re.sub(r" \(since \d\d[:/]\d\d\)", "", orig_state)


def safe_truncate(val: object | None, max_len: int) -> str:
    """Convert a value to text and cap it to a maximum length.

    Args:
        val (object | None):
            Value to stringify. ``None`` is treated as an empty string.
        max_len (int):
            Maximum number of characters to return.

    Returns:
        str:
            String representation truncated to ``max_len`` characters.
    """
    s = str(val) if val is not None else ""
    return s[:max_len] if len(s) > max_len else s


def _ensure_places_client(hass: HomeAssistant) -> PlacesClient:
    """Return the client shared by all Places entries on this HA instance.

    Args:
        hass (HomeAssistant): Home Assistant instance that owns the session.

    Returns:
        PlacesClient: Client with shared caching and request spacing.
    """
    domain_data = hass.data.setdefault(DOMAIN, {})
    client = domain_data.get(PLACES_CLIENT)
    if client is None:
        client = PlacesClient(
            async_get_clientsession(hass),
            base_url="https://nominatim.openstreetmap.org",
            user_agent=(
                f"Mozilla/5.0 (Home Assistant/{ha_version}) "
                f"{DOMAIN}/{VERSION} (+https://github.com/custom-components/places)"
            ),
            cache_ttl=OSM_CACHE_MAX_AGE_HOURS * 3600,
            cache_maxsize=OSM_CACHE_MAX_SIZE,
            min_request_interval=OSM_THROTTLE_INTERVAL_SECONDS,
        )
        domain_data[PLACES_CLIENT] = client
    return client
