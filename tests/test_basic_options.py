"""Unit tests for the BasicOptionsParser class in the places custom component.

This module tests display formatting, attribute handling, and logic for place and zone information.
"""

from unittest.mock import patch

import pytest

from custom_components.places.basic_options import BasicOptionsParser
from tests.conftest import MockSensor


@pytest.mark.asyncio
async def test_build_display_all_blank():
    """Test that build_display() returns an empty string when all attributes are blank."""
    sensor = MockSensor()
    parser = BasicOptionsParser(sensor, {}, ["driving", "zone_name", "zone", "place"])
    result = await parser.build_display()
    assert result == ""


@pytest.mark.asyncio
async def test_build_display_some_attrs():
    """Test that build_display() includes specified attributes in the output string when present.

    Verifies that the display string contains the values for driving status, zone name, place name, street, and city when these attributes are provided.
    """
    attrs = {
        "driving": "Driving",
        "devicetracker_zone_name": "Home",
        "place_name": "Park",
        "street": "Main St",
        "city": "Springfield",
    }
    sensor = MockSensor(attrs)
    parser = BasicOptionsParser(sensor, attrs, ["driving", "zone_name", "place", "street", "city"])
    result = await parser.build_display()
    # Should include driving, zone_name, place_name, street, city
    assert "Driving" in result
    assert "Home" in result
    assert "Park" in result
    assert "Main St" in result
    assert "Springfield" in result


@pytest.mark.asyncio
async def test_build_display_do_not_reorder():
    """Test that `build_display()` preserves attribute order and formatting when 'do_not_reorder' is specified in options.

    Verifies that only the city and region (as state) are included in the output, maintaining the specified order.
    """
    attrs = {"city": "Springfield", "region": "IL"}
    sensor = MockSensor(attrs)
    parser = BasicOptionsParser(sensor, attrs, ["do_not_reorder", "city", "state"])
    result = await parser.build_display()
    # Should reorder and only include city and region (for state)
    assert result == "Springfield, IL"


@pytest.mark.asyncio
async def test_build_display_in_zone_logic():
    """Test that `build_display()` includes the zone name when the sensor is in a zone.

    Verifies that when the sensor's `in_zone` flag is set and `devicetracker_zone_name` is provided, the resulting display string contains the zone name.
    """
    attrs = {"devicetracker_zone_name": "Work"}
    sensor = MockSensor(attrs, in_zone=True)
    parser = BasicOptionsParser(sensor, attrs, ["zone_name"])
    result = await parser.build_display()
    assert "Work" in result


@pytest.mark.asyncio
async def test_build_formatted_place_not_in_zone_place_name():
    """Test that `build_formatted_place()` returns the `place_name` when the sensor is not in a zone and `place_name` is non-blank and unique."""
    attrs = {"place_name": "Central Park"}
    sensor = MockSensor(attrs, display_options_list=["driving"])
    parser = BasicOptionsParser(sensor, attrs, ["place"])
    # should_use_place_name returns True if place_name not blank and not duplicate
    result = await parser.build_formatted_place()
    assert "Central Park" in result


@pytest.mark.asyncio
async def test_build_formatted_place_not_in_zone_type_category_street():
    """Test that build_formatted_place() constructs a formatted place string using place_type, place_category, street, and city when not in a zone and place_name is blank."""
    attrs = {
        "place_type": "restaurant",
        "place_category": "food",
        "street": "Elm St",
        "city": "Metropolis",
        "place_name": "",
    }
    sensor = MockSensor(attrs)
    parser = BasicOptionsParser(sensor, attrs, ["place"])
    result = await parser.build_formatted_place()
    assert "Restaurant" in result or "Food" in result
    assert "Elm St" in result
    assert "Metropolis" in result


@pytest.mark.asyncio
async def test_build_formatted_place_in_zone():
    """Test that `build_formatted_place()` returns the zone name when the sensor is in a zone."""
    attrs = {"devicetracker_zone_name": "Home"}
    sensor = MockSensor(attrs, in_zone=True)
    parser = BasicOptionsParser(sensor, attrs, ["zone_name"])
    result = await parser.build_formatted_place()
    assert result == "Home"


@pytest.mark.parametrize(
    "attrs,expected",
    [
        ({"place_type": "restaurant", "place_category": "food"}, "Restaurant"),
        ({"place_type": "unclassified", "place_category": "food"}, "Food"),
    ],
)
def test_add_type_or_category(attrs, expected):
    """Test that `add_type_or_category` adds the correct capitalized type or category to the list."""
    sensor = MockSensor(attrs)
    parser = BasicOptionsParser(sensor, attrs, [])
    arr = []
    parser.add_type_or_category(arr, attrs, sensor)
    assert expected in arr


@pytest.mark.parametrize(
    "attrs,expected",
    [
        ({"street": "Main St", "street_number": ""}, "Main St"),
        ({"street": "Main St", "street_number": "123"}, "123 Main St"),
    ],
)
def test_add_street_info(attrs, expected):
    """Test that `add_street_info` appends the correct street info to the list."""
    sensor = MockSensor(attrs)
    parser = BasicOptionsParser(sensor, attrs, [])
    arr = []
    parser.add_street_info(arr, attrs, sensor)
    assert expected in arr


@pytest.mark.parametrize(
    "attrs,expected_city,expected_state",
    [
        ({"city_clean": "Springfield", "state_abbr": "IL"}, "Springfield", "IL"),
        ({"city": "Springfield", "state_abbr": "IL"}, "Springfield", "IL"),
        ({"county": "Clark", "state_abbr": "OH"}, "Clark", "OH"),
    ],
)
def test_add_city_county_state(attrs, expected_city, expected_state):
    """Test that `add_city_county_state` appends the correct city/county and state abbreviation to the list."""
    sensor = MockSensor(attrs)
    parser = BasicOptionsParser(sensor, attrs, [])
    arr = []
    parser.add_city_county_state(arr, attrs, sensor)
    assert expected_city in arr
    assert expected_state in arr


@pytest.mark.parametrize(
    "attrs,duplicate_list,expected",
    [
        ({"place_name": "Park"}, [], True),
        ({"place_name": ""}, [], False),
        ({"place_name": "Dup", "city": "Dup"}, ["city"], False),
    ],
)
def test_should_use_place_name(attrs, duplicate_list, expected):
    """Test that `should_use_place_name` returns the correct boolean based on place_name and duplicates."""
    sensor = MockSensor(attrs)
    parser = BasicOptionsParser(sensor, attrs, [])
    if duplicate_list:
        with patch(
            "custom_components.places.basic_options.PLACE_NAME_DUPLICATE_LIST", duplicate_list
        ):
            assert parser.should_use_place_name(attrs, sensor) is expected
    else:
        assert parser.should_use_place_name(attrs, sensor) is expected
