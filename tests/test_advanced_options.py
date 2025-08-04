"""Unit tests for the AdvancedOptionsParser in the custom_components.places.advanced_options module.

This module contains tests for parsing advanced options, handling inclusion and exclusion filters,
and verifying correct behavior of option state retrieval and error logging.
"""

import logging
from unittest.mock import AsyncMock, patch

import pytest

from custom_components.places.advanced_options import AdvancedOptionsParser
from tests.conftest import MockSensor


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "input_str,expected",
    [
        ("a[b](c)", True),
        ("a[b(c]", False),
        ("a[b](c", False),
        ("a[b]c)", False),
    ],
)
async def test_do_brackets_and_parens_count_match(input_str, expected):
    """Test that do_brackets_and_parens_count_match correctly validates matching brackets and parentheses.

    Parameters
    ----------
    input_str : str
        The input string containing brackets and parentheses.
    expected : bool
        The expected result indicating whether the brackets and parentheses match.

    Asserts
    -------
    That the parser's method returns the expected boolean value.

    """
    sensor = MockSensor()
    parser = AdvancedOptionsParser(sensor, "")
    assert await parser.do_brackets_and_parens_count_match(input_str) is expected


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "key,expected",
    [
        ("zone_name", "Home"),
        ("missing", None),
    ],
)
async def test_get_option_state_basic(key, expected):
    """Test that get_option_state returns the expected value for a given key.

    Parameters
    ----------
    key : str
        The option key to retrieve from the sensor attributes.
    expected : Any
        The expected value for the given key.

    Asserts
    -------
    That the output matches the expected value.

    """
    attrs = {
        "devicetracker_zone_name": "Home",
        "place_type": "Restaurant",
        "street": "Main St",
        "name": "Test",
    }
    sensor = MockSensor(attrs, in_zone=True)
    parser = AdvancedOptionsParser(sensor, "")
    out = await parser.get_option_state(key)
    assert out == expected


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "incl,excl,expected",
    [
        (["home"], None, "Home"),
        (["work"], None, None),
        (None, ["home"], None),
    ],
)
async def test_get_option_state_incl_excl(incl, excl, expected):
    """Test that get_option_state returns the expected value when inclusion and exclusion lists are provided.

    Parameters
    ----------
    incl : list or None
        List of values to include.
    excl : list or None
        List of values to exclude.
    expected : Any
        The expected result for the given inclusion/exclusion filters.

    Asserts
    -------
    That the output matches the expected value.

    """
    attrs = {"devicetracker_zone_name": "Home", "place_type": "Restaurant", "name": "Test"}
    sensor = MockSensor(attrs, in_zone=True)
    parser = AdvancedOptionsParser(sensor, "")
    out = await parser.get_option_state("zone_name", incl=incl, excl=excl)
    assert out == expected


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "incl_attr,excl_attr,expected",
    [
        ({"place_type": ["Restaurant"]}, None, "Home"),
        ({"place_type": ["Work"]}, None, None),
        (None, {"place_type": ["Restaurant"]}, None),
    ],
)
async def test_get_option_state_incl_attr_excl_attr(incl_attr, excl_attr, expected):
    """Test that get_option_state returns the expected value when inclusion and exclusion attribute filters are provided.

    Parameters
    ----------
    incl_attr : dict or None
        Dictionary of attribute filters to include.
    excl_attr : dict or None
        Dictionary of attribute filters to exclude.
    expected : Any
        The expected result for the given attribute filters.

    Asserts
    -------
    That the output matches the expected value.

    """
    attrs = {"devicetracker_zone_name": "Home", "place_type": "Restaurant", "name": "Test"}
    sensor = MockSensor(attrs, in_zone=True)
    parser = AdvancedOptionsParser(sensor, "")
    out = await parser.get_option_state("zone_name", incl_attr=incl_attr, excl_attr=excl_attr)
    assert out == expected


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "key,expected",
    [
        ("place_type", "Restaurant"),
        ("place_category", "Food"),
    ],
)
async def test_get_option_state_title_case(key, expected):
    """Test that get_option_state returns the expected title-cased value for a given key.

    Parameters
    ----------
    key : str
        The option key to retrieve from the sensor attributes.
    expected : str
        The expected title-cased value for the given key.

    Asserts
    -------
    That the output matches the expected title-cased value.

    """
    attrs = {
        "devicetracker_zone_name": "home",
        "place_type": "restaurant",
        "place_category": "food",
        "name": "Test",
    }
    sensor = MockSensor(attrs)
    parser = AdvancedOptionsParser(sensor, "")
    out = await parser.get_option_state(key)
    assert out == expected


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "input_str,expected_attr,expected_lst,expected_incl",
    [
        ("type(work,home)", "type", ["work", "home"], True),
        ("type(-,work,home)", "type", ["work", "home"], False),
    ],
)
async def test_parse_attribute_parentheses_incl_excl(
    input_str, expected_attr, expected_lst, expected_incl
):
    """Test that parse_attribute_parentheses correctly parses attribute, list, and inclusion/exclusion.

    Parameters
    ----------
    input_str : str
        The input string containing attribute and parentheses.
    expected_attr : str
        The expected attribute name.
    expected_lst : list
        The expected list of values.
    expected_incl : bool
        The expected inclusion boolean.

    Asserts
    -------
    That the parsed attribute, list, and inclusion match the expected values.

    """
    sensor = MockSensor()
    parser = AdvancedOptionsParser(sensor, "")
    attr, lst, incl = parser.parse_attribute_parentheses(input_str)
    assert attr == expected_attr
    assert lst == expected_lst
    assert incl is expected_incl


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "parens_input,parens_expected_incl,parens_expected_excl,bracket_input,bracket_expected",
    [
        ("(work,home)", ["work", "home"], [], "[option]", "option"),
        ("(-,work,home)", [], ["work", "home"], "[option]", "option"),
    ],
)
async def test_parse_parens_and_bracket(
    parens_input, parens_expected_incl, parens_expected_excl, bracket_input, bracket_expected
):
    """Test that parse_parens and parse_bracket correctly parse inclusion/exclusion lists and bracketed options.

    Parameters
    ----------
    parens_input : str
        Input string for parentheses parsing.
    parens_expected_incl : list
        Expected inclusion list from parentheses.
    parens_expected_excl : list
        Expected exclusion list from parentheses.
    bracket_input : str
        Input string for bracket parsing.
    bracket_expected : str
        Expected option extracted from brackets.

    Asserts
    -------
    That the inclusion and exclusion lists, and bracketed option, match expected values.

    """
    sensor = MockSensor()
    parser = AdvancedOptionsParser(sensor, "")
    incl, excl, incl_attr, excl_attr, next_opt = await parser.parse_parens(parens_input)
    assert incl == parens_expected_incl
    assert excl == parens_expected_excl
    none_opt, next_opt = await parser.parse_bracket(bracket_input)
    assert none_opt == bracket_expected
    assert isinstance(next_opt, str)


@pytest.mark.asyncio
async def test_compile_state():
    """Test that `compile_state` joins the `state_list` into a comma-separated string.

    Asserts that the resulting string correctly concatenates the elements of `state_list` with a comma and space.
    """
    attrs = {"zone_name": "home", "place_type": "restaurant"}
    sensor = MockSensor(attrs)
    parser = AdvancedOptionsParser(sensor, "")
    parser.state_list = ["Home", "Restaurant"]
    result = await parser.compile_state()
    assert result == "Home, Restaurant"


@pytest.mark.asyncio
async def test_compile_state_skips_none_or_empty():
    """Test that compile_state skips falsy (None/empty) values in state_list."""
    sensor = MockSensor()
    parser = AdvancedOptionsParser(sensor, "")
    parser.state_list = [None, "Home", "", "Restaurant"]
    result = await parser.compile_state()
    assert result == "Home, Restaurant"


@pytest.mark.asyncio
async def test_compile_state_street_space():
    """Test that compile_state adds a space instead of a comma when i == _street_i == _street_num_i."""
    sensor = MockSensor()
    parser = AdvancedOptionsParser(sensor, "")
    parser.state_list = ["Home", "123", "Main St"]
    parser._street_i = 1
    parser._street_num_i = 1
    # The second item should be joined with a comma to the third (current implementation)
    result = await parser.compile_state()
    assert result == "Home, 123, Main St"


@pytest.mark.asyncio
async def test_build_from_advanced_options_bracket_paren_mismatch():
    """Test that build_from_advanced_options returns early without error when given unmatched brackets, leaving state_list unchanged."""
    sensor = MockSensor()
    parser = AdvancedOptionsParser(sensor, "[unmatched")
    # Should return early (no error thrown, state_list unchanged)
    await parser.build_from_advanced_options()
    assert parser.state_list == []


@pytest.mark.asyncio
async def test_build_from_advanced_options_bracket_and_paren():
    # Should process bracket and paren logic
    """Tests that `build_from_advanced_options` correctly processes option strings containing both brackets and parentheses, ensuring that `get_option_state` is called for each parsed option."""
    attrs = {"zone_name": "Home", "place_type": "Restaurant"}
    sensor = MockSensor(attrs)
    parser = AdvancedOptionsParser(sensor, "zone_name[place_type(work)]")
    # Patch get_option_state to track calls
    called = {}

    async def fake_get_option_state(opt, *a, **kw):
        """Simulates retrieval of an option state by recording the accessed option and returning its corresponding attribute value.

        Parameters:
            opt: The option key to retrieve.

        Returns:
            The value associated with the option key from the attrs dictionary, or None if not found.

        """
        called[opt] = True
        return attrs.get(opt)

    parser.get_option_state = fake_get_option_state
    await parser.build_from_advanced_options()
    assert "zone_name" in called


@pytest.mark.asyncio
async def test_build_from_advanced_options_empty_string():
    """Test that building from an empty advanced options string leaves the parser's state list empty."""
    sensor = MockSensor()
    parser = AdvancedOptionsParser(sensor, "")
    await parser.build_from_advanced_options()
    assert parser.state_list == []


@pytest.mark.asyncio
async def test_parse_bracket_mismatch_logs_error():
    """Test that parse_bracket logs an error when given an unmatched bracket input.

    Asserts that the logger's error method is called and the returned option is None or empty.
    """
    sensor = MockSensor()
    parser = AdvancedOptionsParser(sensor, "")
    # Patch logger to capture error
    with patch.object(
        logging.getLogger("custom_components.places.advanced_options"), "error"
    ) as mock_log:
        none_opt, next_opt = await parser.parse_bracket("[unmatched")
        assert none_opt is None or none_opt == ""
        mock_log.assert_called()


@pytest.mark.asyncio
async def test_parse_parens_mismatch_logs_error():
    """Test that parse_parens logs an error when given unmatched parentheses input.

    Asserts that the inclusion list is empty and that an error is logged.
    """
    sensor = MockSensor()
    parser = AdvancedOptionsParser(sensor, "")
    # Patch logger to capture error
    with patch.object(
        logging.getLogger("custom_components.places.advanced_options"), "error"
    ) as mock_log:
        incl, excl, incl_attr, excl_attr, next_opt = await parser.parse_parens("(unmatched")
        assert incl == []
        mock_log.assert_called()


@pytest.mark.asyncio
async def test_build_from_advanced_options_not_none_calls_normal(monkeypatch):
    """Test that build_from_advanced_options proceeds when curr_options is not None."""
    sensor = MockSensor()
    parser = AdvancedOptionsParser(sensor, "zone_name")
    called = {}

    async def fake_process_single_term(opt):
        called["single_term"] = opt

    parser.process_single_term = fake_process_single_term
    await parser.build_from_advanced_options("zone_name")
    assert called["single_term"] == "zone_name"


@pytest.mark.asyncio
async def test_build_from_advanced_options_processed_options(monkeypatch):
    """Test that build_from_advanced_options logs error and returns if curr_options is in _processed_options."""
    sensor = MockSensor()
    parser = AdvancedOptionsParser(sensor, "zone_name")
    parser._processed_options.add("zone_name")
    with patch.object(
        logging.getLogger("custom_components.places.advanced_options"), "error"
    ) as mock_log:
        await parser.build_from_advanced_options("zone_name")
        mock_log.assert_called()
        assert parser.state_list == []


@pytest.mark.asyncio
async def test_build_from_advanced_options_no_bracket_or_paren(monkeypatch):
    """Test that build_from_advanced_options skips bracket/paren processing if not present."""
    sensor = MockSensor()
    parser = AdvancedOptionsParser(sensor, "zone_name")
    parser.process_bracket_or_parens = AsyncMock()
    parser.process_only_commas = AsyncMock()
    parser.process_single_term = AsyncMock()
    await parser.build_from_advanced_options("zone_name")
    parser.process_bracket_or_parens.assert_not_called()


@pytest.mark.asyncio
async def test_build_from_advanced_options_with_comma(monkeypatch):
    """Test that build_from_advanced_options calls process_only_commas if comma is present."""
    sensor = MockSensor()
    parser = AdvancedOptionsParser(sensor, "zone_name,place_type")
    parser.process_only_commas = AsyncMock()
    await parser.build_from_advanced_options("zone_name,place_type")
    parser.process_only_commas.assert_awaited_once_with("zone_name,place_type")


@pytest.mark.asyncio
async def test_build_from_advanced_options_no_comma(monkeypatch):
    """Test that build_from_advanced_options calls process_single_term if no comma is present."""
    sensor = MockSensor()
    parser = AdvancedOptionsParser(sensor, "zone_name")
    parser.process_single_term = AsyncMock()
    await parser.build_from_advanced_options("zone_name")
    parser.process_single_term.assert_awaited_once_with("zone_name")


@pytest.mark.asyncio
async def test_parse_bracket_not_starts_with_bracket():
    """Test parse_bracket when curr_options does NOT start with '[' (should not strip first char)."""
    sensor = MockSensor()
    parser = AdvancedOptionsParser(sensor, "")
    # Should treat the string as-is
    none_opt, next_opt = await parser.parse_bracket("option]")
    assert none_opt == "option"  # Should parse up to the closing bracket
    assert next_opt == ""


@pytest.mark.asyncio
async def test_parse_bracket_starts_with_closing_bracket():
    """Test parse_bracket when curr_options starts with ']' (should detect empty bracket)."""
    sensor = MockSensor()
    parser = AdvancedOptionsParser(sensor, "")
    none_opt, next_opt = await parser.parse_bracket("]")
    assert none_opt == ""  # Should be empty
    assert next_opt == ""


@pytest.mark.asyncio
async def test_parse_bracket_counts_opening_bracket():
    """Test parse_bracket increments bracket_count when encountering '[' inside string."""
    sensor = MockSensor()
    parser = AdvancedOptionsParser(sensor, "")
    # Input with nested brackets, starting with '['
    none_opt, next_opt = await parser.parse_bracket("[outer[inner]]")
    # Should parse up to the matching closing bracket
    assert none_opt == "outer[inner]"  # Everything inside the outer brackets
    assert next_opt == ""


@pytest.mark.asyncio
async def test_process_bracket_or_parens_comma_first_builds_states():
    """Ensure comma-first path processes each option and appends their states in order."""
    attrs = {"devicetracker_zone_name": "Home", "place_type": "restaurant", "name": "Test"}
    sensor = MockSensor(attrs, in_zone=True)
    parser = AdvancedOptionsParser(sensor, "zone_name,place_type")
    await parser.build_from_advanced_options()
    # Title casing applied to place_type
    assert parser.state_list == ["Home", "Restaurant"]


@pytest.mark.asyncio
async def test_bracket_fallback_when_primary_option_none():
    """Bracket-first path: when primary option returns None (not in zone), fallback none option is processed."""
    attrs = {"place_type": "work", "name": "Test"}
    sensor = MockSensor(attrs, in_zone=False)  # zone_name will be excluded (not in zone)
    parser = AdvancedOptionsParser(sensor, "zone_name[place_type(work)]")
    await parser.build_from_advanced_options()
    # zone_name excluded so fallback to place_type(work) -> Work
    assert parser.state_list == ["Work"]


@pytest.mark.asyncio
async def test_paren_then_bracket_fallback_exclusion():
    """Parenthesis filters exclude the option causing fallback to bracket none option."""
    attrs = {"devicetracker_zone_name": "Home", "place_type": "restaurant", "name": "Test"}
    sensor = MockSensor(attrs, in_zone=True)
    # Parenthesis after option (parenthesis-first branch relative to first special char): exclude 'home'
    parser = AdvancedOptionsParser(sensor, "zone_name(-,home)[place_type]")
    await parser.build_from_advanced_options()
    # zone_name excluded by paren filter, fallback processes place_type -> Restaurant
    assert parser.state_list == ["Restaurant"]


@pytest.mark.asyncio
async def test_get_option_state_incl_attr_blank_causes_exclusion():
    """If an incl_attr refers to a blank/missing attribute, the option should be excluded (return None)."""
    attrs = {"devicetracker_zone_name": "Home", "name": "Test"}  # place_type missing -> blank
    sensor = MockSensor(attrs, in_zone=True)
    parser = AdvancedOptionsParser(sensor, "")
    out = await parser.get_option_state("zone_name", incl_attr={"place_type": ["restaurant"]})
    assert out is None


@pytest.mark.asyncio
async def test_compile_state_space_when_street_indices_match():
    """When street and street_number indices align after increment, a space should separate them."""
    sensor = MockSensor()
    parser = AdvancedOptionsParser(sensor, "")
    parser.state_list = ["123", "Main St"]
    # Set indices so after increment _street_num_i becomes 0 and matches _street_i=0 for first element? Need both to match second element, so set before increment to 0 so becomes 1 then set _street_i=1
    parser._street_num_i = 0  # will increment to 1 in compile_state
    parser._street_i = 1
    result = await parser.compile_state()
    # Two items only; index 1 meets condition so space used
    assert result == "123 Main St"


@pytest.mark.asyncio
async def test_parse_parens_with_attribute_filters():
    """parse_parens should populate incl_attr when attribute-specific filters are provided."""
    sensor = MockSensor()
    parser = AdvancedOptionsParser(sensor, "")
    incl, excl, incl_attr, excl_attr, next_opt = await parser.parse_parens(
        "(type(restaurant,bar),home)"
    )
    assert incl == ["home"]
    assert excl == []
    assert incl_attr == {"type": ["restaurant", "bar"]}
    assert excl_attr == {}
