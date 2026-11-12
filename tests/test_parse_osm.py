"""Tests for mapping normalized place data onto Home Assistant attributes."""

from collections.abc import Mapping
from typing import Protocol

import pytest

from custom_components.places.const import (
    ATTR_ATTRIBUTION,
    ATTR_CITY,
    ATTR_CITY_CLEAN,
    ATTR_COUNTRY,
    ATTR_COUNTRY_CODE,
    ATTR_COUNTY,
    ATTR_DEVICETRACKER_ZONE_NAME,
    ATTR_FORMATTED_ADDRESS,
    ATTR_INITIAL_UPDATE,
    ATTR_LAST_PLACE_NAME,
    ATTR_OSM_DICT,
    ATTR_OSM_ID,
    ATTR_OSM_TYPE,
    ATTR_PLACE_CATEGORY,
    ATTR_PLACE_NAME,
    ATTR_PLACE_NAME_NO_DUPE,
    ATTR_PLACE_NEIGHBOURHOOD,
    ATTR_PLACE_TYPE,
    ATTR_POSTAL_CODE,
    ATTR_POSTAL_TOWN,
    ATTR_REGION,
    ATTR_ROUTE_NUMBER,
    ATTR_STATE_ABBR,
    ATTR_STREET,
    ATTR_STREET_NUMBER,
    CONF_LANGUAGE,
)
from custom_components.places.parse_osm import OSMParser
from tests.conftest import MockSensor, mock_sensor

type Attrs = Mapping[str, object]


class OSMParserFactory(Protocol):
    """Factory for a parser and its Home Assistant sensor double."""

    def __call__(self, attrs: Attrs | None = None) -> tuple[OSMParser, MockSensor]:
        """Create a parser backed by the supplied attributes.

        Args:
            attrs (Attrs | None): Initial attributes for the parser's sensor.

        Returns:
            tuple[OSMParser, MockSensor]: Parser and corresponding sensor double.
        """


@pytest.fixture
def osm_parser() -> OSMParserFactory:
    """Create parsers backed by isolated mock sensors.

    Returns:
        OSMParserFactory: Factory for independent parser and sensor pairs.
    """

    def create(attrs: Attrs | None = None) -> tuple[OSMParser, MockSensor]:
        """Create a parser and sensor initialized with optional attributes.

        Args:
            attrs (Attrs | None): Initial attributes for the sensor.

        Returns:
            tuple[OSMParser, MockSensor]: Parser and corresponding sensor double.
        """
        sensor = mock_sensor(attrs=attrs)
        return OSMParser(sensor), sensor

    return create


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("language", "expected_name"),
    [("fr,en", "Parc Central"), ("de", "Central Park")],
)
async def test_parse_osm_dict_maps_place_fields_and_language(
    osm_parser: OSMParserFactory, language: str, expected_name: str
) -> None:
    """Map normalized place fields and honor HA language preferences.

    Args:
        osm_parser (OSMParserFactory): Factory for an isolated parser and sensor.
        language (str): Configured ordered language preference.
        expected_name (str): Name selected from the place's localized names.
    """
    parser, sensor = osm_parser(
        {
            CONF_LANGUAGE: language,
            ATTR_OSM_DICT: {
                "osm_id": 42,
                "osm_type": "way",
                "type": "road",
                "category": "highway",
                "licence": "OpenStreetMap contributors",
                "display_name": "Central Park, New York, United States",
                "namedetails": {
                    "name": "Central Park",
                    "name:en": "Central Park",
                    "name:fr": "Parc Central",
                    "ref": "M10",
                },
                "address": {
                    "road": "Broadway",
                    "highway": "Broadway",
                    "house_number": "10",
                    "city": "City of New York",
                    "suburb": "Manhattan",
                    "quarter": "Upper East Side",
                    "state": "New York",
                    "ISO3166-2-lvl4": "US-NY",
                    "county": "New York County",
                    "country": "United States",
                    "postcode": "10001",
                    "country_code": "us",
                },
            },
        }
    )

    await parser.parse_osm_dict()

    assert sensor.attrs[ATTR_PLACE_NAME] == expected_name
    assert sensor.attrs[ATTR_PLACE_NAME_NO_DUPE] == expected_name
    assert sensor.attrs[ATTR_ATTRIBUTION] == "OpenStreetMap contributors"
    assert sensor.attrs[ATTR_OSM_ID] == "42"
    assert sensor.attrs[ATTR_OSM_TYPE] == "way"
    assert sensor.attrs[ATTR_PLACE_TYPE] == "road"
    assert sensor.attrs[ATTR_PLACE_CATEGORY] == "highway"
    assert sensor.attrs[ATTR_STREET_NUMBER] == "10"
    assert sensor.attrs[ATTR_STREET] == "Broadway"
    assert sensor.attrs[ATTR_CITY] == "City of New York"
    assert sensor.attrs[ATTR_CITY_CLEAN] == "New York City"
    assert sensor.attrs[ATTR_POSTAL_TOWN] == "Manhattan"
    assert sensor.attrs[ATTR_PLACE_NEIGHBOURHOOD] == "Upper East Side"
    assert sensor.attrs[ATTR_REGION] == "New York"
    assert sensor.attrs[ATTR_STATE_ABBR] == "NY"
    assert sensor.attrs[ATTR_COUNTY] == "New York County"
    assert sensor.attrs[ATTR_COUNTRY] == "United States"
    assert sensor.attrs[ATTR_POSTAL_CODE] == "10001"
    assert sensor.attrs[ATTR_COUNTRY_CODE] == "US"
    assert sensor.attrs[ATTR_FORMATTED_ADDRESS] == "Central Park, New York, United States"
    assert sensor.attrs[ATTR_ROUTE_NUMBER] == "M10"


@pytest.mark.asyncio
async def test_parse_osm_dict_does_not_repeat_street_as_place_name(
    osm_parser: OSMParserFactory,
) -> None:
    """Keep a place name out of the no-duplicate field when it equals its street.

    Args:
        osm_parser (OSMParserFactory): Factory for an isolated parser and sensor.
    """
    parser, sensor = osm_parser(
        {
            ATTR_OSM_DICT: {
                "type": "road",
                "address": {"road": "Main Street"},
                "namedetails": {"name": "Main Street"},
            }
        }
    )

    await parser.parse_osm_dict()

    assert sensor.attrs[ATTR_PLACE_NAME] == "Main Street"
    assert sensor.attrs[ATTR_STREET] == "Main Street"
    assert ATTR_PLACE_NAME_NO_DUPE not in sensor.attrs


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("attrs", "previous_name", "expected_name"),
    [
        (
            {ATTR_INITIAL_UPDATE: True, ATTR_LAST_PLACE_NAME: "Persisted"},
            "Before restore",
            "Before restore",
        ),
        (
            {ATTR_LAST_PLACE_NAME: "Central Park", ATTR_PLACE_NAME: "Central Park"},
            "Home",
            "Home",
        ),
        (
            {ATTR_LAST_PLACE_NAME: "Home", ATTR_DEVICETRACKER_ZONE_NAME: "Home"},
            "Park",
            "Park",
        ),
        (
            {ATTR_LAST_PLACE_NAME: "Previous", ATTR_PLACE_NAME: "Current"},
            "Older",
            "Previous",
        ),
    ],
    ids=("restored-initial-update", "same-place", "same-zone", "place-changed"),
)
async def test_finalize_last_place_name_preserves_expected_previous_place(
    osm_parser: OSMParserFactory,
    attrs: Mapping[str, object],
    previous_name: str,
    expected_name: str,
) -> None:
    """Preserve the appropriate previous-place value across finalization branches.

    Args:
        osm_parser (OSMParserFactory): Factory for an isolated parser and sensor.
        attrs (Mapping[str, object]): Initial sensor attributes for this branch.
        previous_name (str): Previously stored place name supplied by the updater.
        expected_name (str): Previous place name expected after finalization.
    """
    parser, sensor = osm_parser(attrs)

    await parser.finalize_last_place_name(previous_name)

    assert sensor.attrs[ATTR_LAST_PLACE_NAME] == expected_name


@pytest.mark.asyncio
async def test_parse_osm_dict_ignores_missing_response(osm_parser: OSMParserFactory) -> None:
    """Leave HA attributes unchanged when no reverse-lookup mapping is available.

    Args:
        osm_parser (OSMParserFactory): Factory for an isolated parser and sensor.
    """
    parser, sensor = osm_parser({ATTR_PLACE_NAME: "Existing"})

    await parser.parse_osm_dict()

    assert sensor.attrs == {ATTR_PLACE_NAME: "Existing"}
