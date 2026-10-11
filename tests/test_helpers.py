"""Unit tests for helper functions in the places custom component."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
import re
from typing import Protocol
from unittest.mock import MagicMock

import aiohttp
from aioplaces import HTTPError, JSONMapping, PlacesClient
from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession
import pytest

from custom_components.places import helpers
from custom_components.places.const import DOMAIN, PLACES_CLIENT
from custom_components.places.helpers import clear_since_from_state, safe_truncate


@pytest.mark.parametrize(
    ("input_str", "expected"),
    [
        ("Home (since 12:34)", "Home"),
        ("Work (since 01/23)", "Work"),
        ("Elsewhere", "Elsewhere"),
    ],
)
def test_clear_since_from_state_removes_pattern(input_str: str, expected: str) -> None:
    """Test that clear_since_from_state removes '(since ...)' patterns from strings.

    Args:
        input_str (str):
            State string from which a ``(since ...)`` suffix is removed.
        expected (str):
            Expected result for this parametrized case.
    """
    assert clear_since_from_state(input_str) == expected


@pytest.mark.parametrize(
    ("input_str", "max_len", "expected"),
    [
        ("abc", 5, "abc"),  # shorter
        ("abcde", 5, "abcde"),  # exact
        ("abcdef", 4, "abcd"),  # longer
        (None, 3, ""),  # None
    ],
)
def test_safe_truncate(input_str: str | None, max_len: int, expected: str) -> None:
    """Test that safe_truncate returns the correct truncated string for various inputs.

    Args:
        input_str (str | None):
            Text to truncate safely.
        max_len (int):
            Maximum output length enforced by truncation.
        expected (str):
            Expected result for this parametrized case.
    """
    assert safe_truncate(input_str, max_len) == expected


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        (1.23, True),
        ("2.34", True),
        (0, True),
        ("0", True),
        (-5.6, True),
        (123, True),
        (123.45, True),
        ("1.23", True),
        (None, False),
        ("abc", False),
        ({}, False),
        ([], False),
        ("not-a-number", False),
    ],
)
def test_is_float_param(value: object, expected: bool) -> None:
    """is_float returns expected boolean for a variety of inputs.

    Args:
        value (object):
            Candidate input checked for float compatibility.
        expected (bool):
            Expected result for this parametrized case.
    """
    assert helpers.is_float(value) is expected


def test_ensure_places_client_reuses_instance_and_borrows_shared_session(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """All Places entries on one Home Assistant instance use one client.

    Args:
        monkeypatch (pytest.MonkeyPatch): Scoped replacement for the session getter.
    """
    session = MagicMock(spec=aiohttp.ClientSession)
    get_session = MagicMock(return_value=session)
    monkeypatch.setattr(helpers, "async_get_clientsession", get_session)
    hass = MagicMock()
    hass.data = {}

    first_client = helpers._ensure_places_client(hass)
    second_client = helpers._ensure_places_client(hass)

    assert first_client is second_client
    assert hass.data[DOMAIN][PLACES_CLIENT] is first_client
    get_session.assert_called_once_with(hass)


def test_ensure_places_client_preserves_existing_instance(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Do not replace a client already stored by another config entry.

    Args:
        monkeypatch (pytest.MonkeyPatch): Scoped replacement for the session getter.
    """
    get_session = MagicMock()
    monkeypatch.setattr(helpers, "async_get_clientsession", get_session)
    existing_client = MagicMock()
    hass = MagicMock()
    hass.data = {DOMAIN: {PLACES_CLIENT: existing_client}}

    assert helpers._ensure_places_client(hass) is existing_client
    get_session.assert_not_called()


@pytest.mark.asyncio
async def test_ensure_places_client_uses_home_assistant_owned_session(
    hass: HomeAssistant, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Accept and leave open Home Assistant's real shared HTTP session.

    Args:
        hass (HomeAssistant): Runtime that owns the shared HTTP session.
        monkeypatch (pytest.MonkeyPatch): Scoped session-getter replacement.
    """
    session = async_get_clientsession(hass)
    monkeypatch.setattr(
        helpers,
        "async_get_clientsession",
        lambda _hass: session,
    )

    client = helpers._ensure_places_client(hass)

    assert client is hass.data[DOMAIN][PLACES_CLIENT]
    assert not session.closed
    assert async_get_clientsession(hass) is session


class ResponseMock(Protocol):
    """Mutable response registration used to provide successive HTTP replies."""

    side_effect: Callable[..., Awaitable[ResponseMock]] | None


class AioClientMock(Protocol):
    """Small surface of Home Assistant's aiohttp test client mock."""

    call_count: int

    def request(self, method: str, url: re.Pattern[str], **kwargs: object) -> ResponseMock:
        """Register a mock response for a request.

        Args:
            method (str): HTTP method expected by the mock.
            url (re.Pattern[str]): URL pattern expected by the mock.
            **kwargs (object): Response fields used by the aiohttp mock.

        Returns:
            ResponseMock: Mock response registration for this request.
        """


def _make_places_client(hass: HomeAssistant) -> PlacesClient:
    """Build a client on Home Assistant's mocked, owned HTTP session.

    Args:
        hass (HomeAssistant): Runtime supplying the shared HTTP session.

    Returns:
        PlacesClient: Client configured for the local test endpoint.
    """
    return PlacesClient(
        async_get_clientsession(hass),
        base_url="https://example.test/nominatim",
        user_agent="Places test suite",
        min_request_interval=0.001,
    )


def _reverse_url() -> re.Pattern[str]:
    """Match reverse lookups independent of their encoded query ordering.

    Returns:
        re.Pattern[str]: Pattern matching the test reverse endpoint.
    """
    return re.compile(r"https://example\.test/nominatim/reverse\?")


def _sequence_responses(first_response: ResponseMock, responses: list[ResponseMock]) -> None:
    """Return each registered response in order for matching requests.

    Args:
        first_response (ResponseMock): First response registration to update.
        responses (list[ResponseMock]): Responses yielded for successive requests.
    """
    next_response = iter(responses)

    async def respond(*_args: object) -> ResponseMock:
        """Yield the next configured response.

        Args:
            *_args (object): Request arguments provided by the test client.

        Returns:
            ResponseMock: Next response in the configured sequence.
        """
        return next(next_response)

    first_response.side_effect = respond


@pytest.mark.asyncio
async def test_places_client_caches_success_and_force_fetches_fresh_data(
    hass: HomeAssistant, aioclient_mock: AioClientMock
) -> None:
    """Reuse successful lookup data, with one fresh request when cache is bypassed.

    Args:
        hass (HomeAssistant): Runtime providing the shared session.
        aioclient_mock (AioClientMock): HTTP boundary for request counting.
    """
    url = _reverse_url()
    payload: JSONMapping = {"osm_id": 123, "display_name": "Central Park"}
    aioclient_mock.request("get", url, json=payload)
    client = _make_places_client(hass)

    first = await client.reverse(40.7, -73.9)
    cached = await client.reverse(40.7, -73.9)
    fresh = await client.reverse(40.7, -73.9, use_cache=False)

    assert first == payload
    assert cached == payload
    assert cached is not first
    assert fresh == payload
    assert aioclient_mock.call_count == 2


@pytest.mark.asyncio
async def test_places_client_retries_after_valid_no_result(
    hass: HomeAssistant, aioclient_mock: AioClientMock
) -> None:
    """A valid empty response does not suppress retrying the same coordinates.

    Args:
        hass (HomeAssistant): Runtime providing the shared session.
        aioclient_mock (AioClientMock): HTTP boundary with sequential replies.
    """
    url = _reverse_url()
    no_result = aioclient_mock.request("get", url, text="[]")
    recovered_payload: JSONMapping = {"osm_id": 456, "display_name": "Recovery"}
    recovered = aioclient_mock.request("get", url, json=recovered_payload)
    _sequence_responses(no_result, [no_result, recovered])
    client = _make_places_client(hass)

    assert await client.reverse(40.7, -73.9) is None
    assert await client.reverse(40.7, -73.9) == recovered_payload
    assert aioclient_mock.call_count == 2


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [429, 500])
async def test_places_client_retries_after_http_error(
    hass: HomeAssistant, aioclient_mock: AioClientMock, status: int
) -> None:
    """An HTTP failure is surfaced and does not prevent a later successful lookup.

    Args:
        hass (HomeAssistant): Runtime providing the shared session.
        aioclient_mock (AioClientMock): HTTP boundary with sequential replies.
        status (int): Failure status returned for the first request.
    """
    url = _reverse_url()
    failed = aioclient_mock.request("get", url, status=status)
    expected: JSONMapping = {"osm_id": 789, "display_name": "Recovered"}
    recovered = aioclient_mock.request("get", url, json=expected)
    _sequence_responses(failed, [failed, recovered])
    client = _make_places_client(hass)

    with pytest.raises(HTTPError) as error:
        await client.reverse(40.7, -73.9)

    assert error.value.status == status
    assert await client.reverse(40.7, -73.9) == expected
    assert aioclient_mock.call_count == 2
