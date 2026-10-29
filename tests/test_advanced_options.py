"""Unit tests for AdvancedOptionsParser in custom_components.places.advanced_options."""

from collections.abc import Mapping, Sequence
import logging
from typing import Protocol

import pytest

from custom_components.places.advanced_options import AdvancedOptionsParser
from tests.conftest import MockSensor, mock_sensor

type Attrs = Mapping[str, object]
type FilterMap = Mapping[str, Sequence[str]]


class AdvancedParserFactory(Protocol):
    """Factory fixture for an advanced options parser and mock sensor."""

    def __call__(
        self, opts_str: str | None = None, attrs: Attrs | None = None, in_zone: bool = False
    ) -> tuple[AdvancedOptionsParser, MockSensor]:
        """Create the parser and sensor.

        Args:
            opts_str (str | None):
                Display-options expression parsed by the fixture.
            attrs (Attrs | None):
                Places attribute mapping used by the test.
            in_zone (bool):
                Whether the tracker is inside the selected zone.

        Returns:
            tuple[AdvancedOptionsParser, MockSensor]:
                Advanced options parser and the backing ``MockSensor``.
        """


@pytest.fixture
def advanced_parser() -> AdvancedParserFactory:
    """Factory fixture to create an AdvancedOptionsParser and its sensor.

    Returns (parser, sensor).

    Returns:
        AdvancedParserFactory:
            Factory that constructs advanced-option parsers for test inputs.
    """

    def _create(
        opts_str: str | None = None, attrs: Attrs | None = None, in_zone: bool = False
    ) -> tuple[AdvancedOptionsParser, MockSensor]:
        """Create an advanced-options parser backed by a configured mock sensor.

        Args:
            opts_str (str | None):
                Advanced display options string to parse.
            attrs (Attrs | None):
                Sensor attributes exposed to parser lookups.
            in_zone (bool):
                Whether the mock sensor should report itself in a zone.

        Returns:
            tuple[AdvancedOptionsParser, MockSensor]:
                Parser instance and the sensor backing it.
        """
        sensor = mock_sensor(attrs=attrs, in_zone=in_zone)
        parser = AdvancedOptionsParser(sensor, opts_str or "")
        return parser, sensor

    return _create


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("input_str", "expected"),
    [
        ("a[b](c)", True),
        ("a[b(c]", False),
        ("a[b](c", False),
        ("a[b]c)", False),
    ],
)
async def test_do_brackets_and_parens_count_match(
    input_str: str, expected: bool, advanced_parser: AdvancedParserFactory
) -> None:
    """Assert bracket and parenthesis count matching for the supplied text.

    Args:
        input_str (str):
            Text supplied to the display-options parser.
        expected (bool):
            Expected result for this parametrized case.
        advanced_parser (AdvancedParserFactory):
            Advanced display-options parser fixture.
    """
    parser, _sensor = advanced_parser()
    assert await parser.do_brackets_and_parens_count_match(input_str) is expected


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("key", "expected"),
    [
        ("osm_formatted_address", "123 Any Street"),
        ("zone_name", "Home"),
        ("province", "Virginia"),
        ("missing", None),
    ],
)
async def test_get_option_state_basic(
    key: str, expected: str | None, advanced_parser: AdvancedParserFactory
) -> None:
    """Return the expected option state for a basic key lookup.

    Args:
        key (str):
            Configuration or attribute key being accessed.
        expected (str | None):
            Expected result for this parametrized case.
        advanced_parser (AdvancedParserFactory):
            Advanced display-options parser fixture.
    """
    attrs = {
        "formatted_address": "123 Any Street",
        "zone_name": "Home",
        "place_type": "Restaurant",
        "street": "Main St",
        "state": "Virginia",
        "name": "Test",
    }
    parser, _sensor = advanced_parser(attrs=attrs, in_zone=True)
    out = await parser.get_option_state(key)
    assert out == expected


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("incl", "excl", "expected"),
    [
        (["home"], None, "Home"),
        (["work"], None, None),
        (None, ["home"], None),
    ],
)
async def test_get_option_state_incl_excl(
    incl: list[str] | None,
    excl: list[str] | None,
    expected: str | None,
    advanced_parser: AdvancedParserFactory,
) -> None:
    """Respect inclusion/exclusion lists when resolving option state.

    Args:
        incl (list[str] | None):
            Option tokens included in the rendered state.
        excl (list[str] | None):
            Option tokens excluded from the rendered state.
        expected (str | None):
            Expected result for this parametrized case.
        advanced_parser (AdvancedParserFactory):
            Advanced display-options parser fixture.
    """
    attrs = {"zone_name": "Home", "place_type": "Restaurant", "name": "Test"}
    parser, _sensor = advanced_parser(attrs=attrs, in_zone=True)
    out = await parser.get_option_state("zone_name", incl=incl, excl=excl)
    assert out == expected


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("incl_attr", "excl_attr", "expected"),
    [
        ({"place_type": ["Restaurant"]}, None, "Home"),
        ({"place_type": ["Work"]}, None, None),
        (None, {"place_type": ["Restaurant"]}, None),
    ],
)
async def test_get_option_state_incl_attr_excl_attr(
    incl_attr: FilterMap | None,
    excl_attr: FilterMap | None,
    expected: str | None,
    advanced_parser: AdvancedParserFactory,
) -> None:
    """Apply attribute-based inclusion/exclusion filters when resolving option state.

    Args:
        incl_attr (FilterMap | None):
            Attributes included in the rendered state.
        excl_attr (FilterMap | None):
            Attributes excluded from the rendered state.
        expected (str | None):
            Expected result for this parametrized case.
        advanced_parser (AdvancedParserFactory):
            Advanced display-options parser fixture.
    """
    attrs = {"zone_name": "Home", "place_type": "Restaurant", "name": "Test"}
    parser, _sensor = advanced_parser(attrs=attrs, in_zone=True)
    out = await parser.get_option_state("zone_name", incl_attr=incl_attr, excl_attr=excl_attr)
    assert out == expected


@pytest.mark.asyncio
async def test_get_option_state_numeric_values_are_stringified(
    advanced_parser: AdvancedParserFactory,
) -> None:
    """Handle numeric display values by normalizing them before string operations.

    Args:
        advanced_parser (AdvancedParserFactory):
            Advanced display-options parser fixture.
    """
    attrs = {
        "latitude": 40.715,
        "longitude": -74.006,
        "name": "Test",
    }
    parser, _sensor = advanced_parser(attrs=attrs, in_zone=True)
    out = await parser.get_option_state("latitude")
    assert out == "40.715"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("key", "expected"),
    [
        ("place_type", "Restaurant"),
        ("place_category", "Food"),
    ],
)
async def test_get_option_state_title_case(
    key: str, expected: str, advanced_parser: AdvancedParserFactory
) -> None:
    """Return title-cased option values when appropriate.

    Args:
        key (str):
            Configuration or attribute key being accessed.
        expected (str):
            Expected result for this parametrized case.
        advanced_parser (AdvancedParserFactory):
            Advanced display-options parser fixture.
    """
    attrs = {
        "zone_name": "home",
        "place_type": "restaurant",
        "place_category": "food",
        "name": "Test",
    }
    parser, _sensor = advanced_parser(attrs=attrs)
    out = await parser.get_option_state(key)
    assert out == expected


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("input_str", "expected_attr", "expected_lst", "expected_incl"),
    [
        ("type(work,home)", "type", ["work", "home"], True),
        ("type(-,work,home)", "type", ["work", "home"], False),
    ],
)
async def test_parse_attribute_parentheses_incl_excl(
    input_str: str,
    expected_attr: str,
    expected_lst: list[str],
    expected_incl: bool,
    advanced_parser: AdvancedParserFactory,
) -> None:
    """Parse attribute parentheses into (attr, list, include_flag).

    Args:
        input_str (str):
            Text supplied to the display-options parser.
        expected_attr (str):
            Attribute name whose resulting content is asserted.
        expected_lst (list[str]):
            Parsed option list expected for this case.
        expected_incl (bool):
            Included option tokens expected after parsing.
        advanced_parser (AdvancedParserFactory):
            Advanced display-options parser fixture.
    """
    parser, _sensor = advanced_parser()
    attr, lst, incl = parser.parse_attribute_parentheses(input_str)
    assert attr == expected_attr
    assert lst == expected_lst
    assert incl is expected_incl


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("parens_input", "parens_expected_incl", "parens_expected_excl"),
    [
        ("(work,home)", ["work", "home"], []),
        ("(-,work,home)", [], ["work", "home"]),
    ],
)
async def test_parse_parens_inclusion_and_exclusion(
    parens_input: str,
    parens_expected_incl: list[str],
    parens_expected_excl: list[str],
    advanced_parser: AdvancedParserFactory,
) -> None:
    """Parse included and excluded values from parenthesized expressions.

    Args:
        parens_input (str):
            Parenthesized expression supplied to the parser.
        parens_expected_incl (list[str]):
            Tokens expected inside the parenthesized group.
        parens_expected_excl (list[str]):
            Tokens expected outside the parenthesized group.
        advanced_parser (AdvancedParserFactory):
            Advanced display-options parser fixture.
    """
    parser, _sensor = advanced_parser()
    incl, excl, _incl_attr, _excl_attr, _next_opt = await parser.parse_parens(parens_input)
    assert incl == parens_expected_incl
    assert excl == parens_expected_excl


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("options", "attrs", "expected"),
    [
        (
            "zone_name,place_type",
            {"zone_name": "Home", "place_type": "Restaurant"},
            "Home, Restaurant",
        ),
        (
            "zone_name,missing,place_type",
            {"zone_name": "Home", "place_type": "Restaurant"},
            "Home, Restaurant",
        ),
        (
            "zone_name,street_number,street",
            {"zone_name": "Home", "street_number": "123", "street": "Main St"},
            "Home, 123 Main St",
        ),
        ("street_number,street", {"street_number": "123", "street": "Main St"}, "123 Main St"),
    ],
)
async def test_compile_state_variants(
    options: str,
    attrs: Attrs,
    expected: str,
    advanced_parser: AdvancedParserFactory,
) -> None:
    """Compile states produced from display expressions across variants.

    Args:
        options (str):
            Advanced display-options expression to parse.
        attrs (Attrs):
            Sensor attributes used to resolve the expression.
        expected (str):
            Expected compiled state.
        advanced_parser (AdvancedParserFactory):
            Factory fixture for an expression-driven parser and sensor.
    """
    parser, _sensor = advanced_parser(options, attrs, in_zone=True)
    await parser.build_from_advanced_options()
    result = await parser.compile_state()
    assert result == expected


@pytest.mark.asyncio
async def test_build_next_option_only_traverses_comma_prefixed_suffix(
    advanced_parser: AdvancedParserFactory,
) -> None:
    """Do not process malformed non-comma suffix text after a bracket fallback.

    Args:
        advanced_parser (AdvancedParserFactory):
            Factory for the parser and sensor used by this expression.
    """
    parser, _sensor = advanced_parser(
        "zone_name[place_type]place_type",
        {"zone_name": "Home", "place_type": "Restaurant"},
        in_zone=False,
    )
    await parser.build_from_advanced_options()
    assert await parser.compile_state() == "Restaurant"


@pytest.mark.asyncio
async def test_build_from_advanced_options_empty_string(sensor: MockSensor) -> None:
    """No-op when advanced options string is empty.

    Args:
        sensor (MockSensor):
            Places sensor fixture whose state is asserted.
    """
    sensor.attrs = {}
    parser = AdvancedOptionsParser(sensor, "")
    await parser.build_from_advanced_options()
    assert await parser.compile_state() == ""


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "input_val",
    [
        "[unmatched",
        "zone_name(unmatched",
    ],
)
async def test_mismatched_special_chars_log_error(
    caplog: pytest.LogCaptureFixture,
    advanced_parser: AdvancedParserFactory,
    input_val: str,
) -> None:
    """Reject malformed expressions with a diagnostic and no rendered state.

    Args:
        caplog (pytest.LogCaptureFixture):
            Captured log records used for message assertions.
        advanced_parser (AdvancedParserFactory):
            Factory for the parser and sensor used by this expression.
        input_val (str):
            Malformed expression passed through the parser's public build method.
    """
    parser, _sensor = advanced_parser(input_val, {}, in_zone=True)
    caplog.set_level(logging.ERROR, logger="custom_components.places.advanced_options")
    await parser.build_from_advanced_options()
    assert any(r.levelname == "ERROR" for r in caplog.records)
    assert await parser.compile_state() == ""


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("input_str", "expected_none_opt", "expected_next_opt"),
    [
        ("option]", "option", ""),
        ("]", "", ""),
        ("[outer[inner]]", "outer[inner]", ""),
    ],
)
async def test_parse_bracket_variants(
    input_str: str, expected_none_opt: object, expected_next_opt: object, sensor: MockSensor
) -> None:
    """Parse bracket inputs and return expected (none_opt, next_opt) pairs.

    Args:
        input_str (str):
            Text supplied to the display-options parser.
        expected_none_opt (object):
            Option expected to produce no selection.
        expected_next_opt (object):
            Option expected after advancing the selection.
        sensor (MockSensor):
            Places sensor fixture whose state is asserted.
    """
    parser = AdvancedOptionsParser(sensor, "")
    none_opt, next_opt = await parser.parse_bracket(input_str)
    assert none_opt == expected_none_opt
    assert next_opt == expected_next_opt


@pytest.mark.asyncio
async def test_bracket_fallback_when_primary_option_none(
    advanced_parser: AdvancedParserFactory,
) -> None:
    """Use bracket fallback when primary option yields None.

    Args:
        advanced_parser (AdvancedParserFactory):
            Factory for the parser and sensor used by this expression.
    """
    attrs: dict[str, object] = {"place_type": "work", "name": "Test"}
    parser, _sensor = advanced_parser("zone_name[place_type(work)]", attrs, in_zone=False)
    await parser.build_from_advanced_options()
    # zone_name excluded so fallback to place_type(work) -> Work
    assert await parser.compile_state() == "Work"


@pytest.mark.asyncio
async def test_paren_then_bracket_fallback_exclusion(
    advanced_parser: AdvancedParserFactory,
) -> None:
    """Parenthesis filters can exclude primary option and fall back to bracket option.

    Args:
        advanced_parser (AdvancedParserFactory):
            Factory for the parser and sensor used by this expression.
    """
    attrs: dict[str, object] = {
        "zone_name": "Home",
        "place_type": "restaurant",
        "name": "Test",
    }
    # Parenthesis after option (parenthesis-first branch relative to first special char): exclude 'home'
    parser, _sensor = advanced_parser("zone_name(-,home)[place_type]", attrs, in_zone=True)
    await parser.build_from_advanced_options()
    # zone_name excluded by paren filter, fallback processes place_type -> Restaurant
    assert await parser.compile_state() == "Restaurant"


@pytest.mark.asyncio
async def test_get_option_state_incl_attr_blank_causes_exclusion(
    advanced_parser: AdvancedParserFactory,
) -> None:
    """Return None when included attribute filters reference missing/blank attributes.

    Args:
        advanced_parser (AdvancedParserFactory):
            Factory for the parser and its configured sensor.
    """
    attrs: dict[str, object] = {
        "zone_name": "Home",
        "name": "Test",
    }  # place_type missing -> blank
    parser, _sensor = advanced_parser(attrs=attrs, in_zone=True)
    out = await parser.get_option_state("zone_name", incl_attr={"place_type": ["restaurant"]})
    assert out is None


@pytest.mark.asyncio
async def test_parse_parens_with_attribute_filters(sensor: MockSensor) -> None:
    """Populate incl_attr when attribute-specific filters are present in parens.

    Args:
        sensor (MockSensor):
            Places sensor fixture whose state is asserted.
    """
    sensor.attrs = {}
    parser = AdvancedOptionsParser(sensor, "")
    incl, excl, incl_attr, excl_attr, _next_opt = await parser.parse_parens(
        "(type(restaurant,bar),home)"
    )
    assert incl == ["home"]
    assert excl == []
    assert incl_attr == {"type": ["restaurant", "bar"]}
    assert excl_attr == {}
