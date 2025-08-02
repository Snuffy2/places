from unittest.mock import MagicMock

import pytest

from custom_components.places.sensor import Places


@pytest.fixture
def places_instance():
    # Minimal mocks for required args
    hass = MagicMock()
    config = {"devicetracker_id": "test_id"}  # <-- Add required key
    config_entry = MagicMock()
    name = "TestSensor"
    unique_id = "unique123"
    imported_attributes = {}
    return Places(hass, config, config_entry, name, unique_id, imported_attributes)


def test_get_attr_safe_float_not_set_returns_zero(places_instance):
    assert places_instance.get_attr_safe_float("missing_attr") == 0.0


def test_get_attr_safe_float_valid_float(places_instance):
    places_instance.set_attr("float_attr", 42.5)
    assert places_instance.get_attr_safe_float("float_attr") == 42.5


def test_get_attr_safe_float_string_float(places_instance):
    places_instance.set_attr("float_str_attr", "3.1415")
    assert places_instance.get_attr_safe_float("float_str_attr") == 3.1415


def test_get_attr_safe_float_non_numeric_string(places_instance):
    places_instance.set_attr("bad_str_attr", "not_a_float")
    assert places_instance.get_attr_safe_float("bad_str_attr") == 0.0


def test_get_attr_safe_float_none(places_instance):
    places_instance.set_attr("none_attr", None)
    assert places_instance.get_attr_safe_float("none_attr") == 0.0


def test_get_attr_safe_float_int(places_instance):
    places_instance.set_attr("int_attr", 7)
    assert places_instance.get_attr_safe_float("int_attr") == 7.0


def test_get_attr_safe_float_list(places_instance):
    places_instance.set_attr("list_attr", [1, 2, 3])
    assert places_instance.get_attr_safe_float("list_attr") == 0.0


def test_get_attr_safe_float_dict(places_instance):
    places_instance.set_attr("dict_attr", {"a": 1})
    assert places_instance.get_attr_safe_float("dict_attr") == 0.0


def test_get_attr_safe_float_with_default(places_instance):
    assert places_instance.get_attr_safe_float("missing_attr", default=5.5) == 5.5


def test_set_and_get_attr(places_instance):
    places_instance.set_attr("foo", "bar")
    assert places_instance.get_attr("foo") == "bar"


def test_clear_attr(places_instance):
    places_instance.set_attr("foo", "bar")
    places_instance.clear_attr("foo")
    assert places_instance.get_attr("foo") is None


def test_get_attr_safe_str_returns_empty_on_none(places_instance):
    assert places_instance.get_attr_safe_str("missing") == ""


def test_get_attr_safe_str_returns_str(places_instance):
    places_instance.set_attr("foo", 123)
    assert places_instance.get_attr_safe_str("foo") == "123"


def test_get_attr_safe_list_returns_empty_on_non_list(places_instance):
    places_instance.set_attr("notalist", "string")
    assert places_instance.get_attr_safe_list("notalist") == []


def test_get_attr_safe_list_returns_list(places_instance):
    places_instance.set_attr("alist", [1, 2, 3])
    assert places_instance.get_attr_safe_list("alist") == [1, 2, 3]


def test_get_attr_safe_dict_returns_empty_on_non_dict(places_instance):
    places_instance.set_attr("notadict", "string")
    assert places_instance.get_attr_safe_dict("notadict") == {}


def test_get_attr_safe_dict_returns_dict(places_instance):
    places_instance.set_attr("adict", {"a": 1})
    assert places_instance.get_attr_safe_dict("adict") == {"a": 1}


def test_is_attr_blank_true_for_missing(places_instance):
    assert places_instance.is_attr_blank("missing_attr") is True


def test_is_attr_blank_false_for_value(places_instance):
    places_instance.set_attr("foo", "bar")
    assert places_instance.is_attr_blank("foo") is False


def test_is_attr_blank_false_for_zero(places_instance):
    places_instance.set_attr("zero_attr", 0)
    assert places_instance.is_attr_blank("zero_attr") is False
