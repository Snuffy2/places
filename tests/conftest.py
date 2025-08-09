"""Pytest fixtures and mock classes for testing Home Assistant integrations.

This module provides:
- hass: a fixture that returns a mock Home Assistant instance.
- MockSensor: a class for simulating sensor entities with customizable attributes.
"""

from unittest.mock import AsyncMock, MagicMock

import pytest


class MockMethod:
    """A callable mock method that supports default behavior, return values, and side effects.

    Attributes
    ----------
    _default_func : callable
        The default function to call if no return_value or side_effect is set.
    return_value : any
        The value to return when called, if set.
    side_effect : callable or None
        A function to call instead of the default, if set.

    Methods
    -------
    __call__(*args, **kwargs)
        Calls the side_effect, return_value, or default function as appropriate.

    """

    def __init__(self, default_func):
        """Initialize a MockMethod with a default function.

        Parameters:
            default_func (callable): The default function to call if no return_value or side_effect is set.

        """
        self._default_func = default_func
        self.return_value = None
        self.side_effect = None

    def __call__(self, *args, **kwargs):
        """Call the mock method, using side_effect, return_value, or the default function.

        Parameters
        ----------
        *args : tuple
            Positional arguments to pass to the function.
        **kwargs : dict
            Keyword arguments to pass to the function.

        Returns
        -------
        Any
            The result of side_effect, return_value, or the default function.

        """
        if self.side_effect is not None:
            return self.side_effect(*args, **kwargs)
        if self.return_value is not None:
            return self.return_value
        return self._default_func(*args, **kwargs)


class MockSensor:
    """A mock sensor entity for testing Home Assistant integrations.

    Attributes
    ----------
    attrs : dict
        Dictionary of sensor attributes.
    display_options_list : list
        List of display options for the sensor.
    blank_attrs : set
        Set of attribute names considered blank.
    _in_zone : bool
        Indicates if the sensor is in a zone.

    Methods
    -------
    is_attr_blank(attr)
        Determine if a given attribute is considered blank.
    get_attr_safe_str(attr, default=None)
        Safely retrieves the string value of a specified attribute.
    get_attr_safe_list(attr, default=None)
        Safely retrieve a list attribute by name.
    get_attr(key)
        Retrieve the value of the specified attribute key.
    in_zone()
        Asynchronously determine whether the sensor is currently in the designated zone.

    """

    def __init__(self, attrs=None, display_options_list=None, blank_attrs=None, in_zone=False):
        """Initialize a MockSensor instance with customizable attributes and zone status.

        Parameters:
            attrs (dict, optional): Dictionary of sensor attributes.
            display_options_list (list, optional): List of display options for the sensor.
            blank_attrs (set, optional): Set of attribute names considered blank.
            in_zone (bool, optional): Indicates if the sensor is in a zone. Defaults to False.

        """
        self.attrs = attrs or {}
        self.display_options_list = display_options_list or []
        self.blank_attrs = blank_attrs or set()
        self._in_zone = in_zone
        self.native_value = None
        self.entity_id = "sensor.test"
        self.warn_if_device_tracker_prob = False

        # get_attr: MagicMock with fallback to real attribute lookup
        def _get_attr_fallback(key):
            return self.attrs.get(key)

        self.get_attr = MagicMock(side_effect=_get_attr_fallback)

        # Custom is_attr_blank: MagicMock with default side_effect
        def _is_attr_blank_default(attr):
            if hasattr(self, "blank_attrs") and attr in self.blank_attrs:
                return True
            val = self.attrs.get(attr)
            if isinstance(val, MagicMock):
                return False
            return val is None or val == ""

        self.is_attr_blank = MagicMock(side_effect=_is_attr_blank_default)

        # Custom get_attr_safe_str: MockMethod
        def _get_attr_safe_str_default(attr, default=None):
            val = self.attrs.get(attr, default)
            # If val is a MagicMock, return default or empty string
            if isinstance(val, MagicMock):
                # If default is a MagicMock, return empty string
                if isinstance(default, MagicMock):
                    return ""
                return str(default) if default is not None else ""
            # If val is None, return default or empty string
            if val is None:
                if isinstance(default, MagicMock):
                    return ""
                return str(default) if default is not None else ""
            return str(val)

        self.get_attr_safe_str = MockMethod(_get_attr_safe_str_default)

        # Custom get_attr_safe_float: MockMethod
        def _get_attr_safe_float_default(attr, default=None):
            val = self.attrs.get(attr, default)
            if isinstance(val, MagicMock):
                if isinstance(default, MagicMock):
                    return 0.0
                return float(default) if default is not None else 0.0
            try:
                return float(val)
            except (TypeError, ValueError):
                if isinstance(default, MagicMock):
                    return 0.0
                return float(default) if default is not None else 0.0

        self.get_attr_safe_float = MockMethod(_get_attr_safe_float_default)

        # Custom get_attr_safe_dict: MockMethod
        def _get_attr_safe_dict_default(attr, default=None):
            val = self.attrs.get(attr, default)
            if isinstance(val, MagicMock):
                return {} if not isinstance(default, dict) else default
            return val if isinstance(val, dict) else (default if isinstance(default, dict) else {})

        self.get_attr_safe_dict = MockMethod(_get_attr_safe_dict_default)

        # Custom get_attr_safe_list: MockMethod
        def _get_attr_safe_list_default(attr, default=None):
            if attr == "display_options_list":
                return self.display_options_list
            val = self.attrs.get(attr, default)
            if isinstance(val, MagicMock):
                return [] if not isinstance(default, list) else default
            return val if isinstance(val, list) else (default if isinstance(default, list) else [])

        self.get_attr_safe_list = MockMethod(_get_attr_safe_list_default)
        # Custom set_attr: updates attrs and records calls
        self._set_attr_mock = MagicMock()

        def set_attr(key, value):
            self.attrs[key] = value
            self._set_attr_mock(key, value)

        self.set_attr = set_attr
        self.set_attr.call_args_list = self._set_attr_mock.call_args_list
        self.set_attr.assert_any_call = self._set_attr_mock.assert_any_call
        self.set_attr.assert_not_called = self._set_attr_mock.assert_not_called
        # Custom clear_attr: removes key from attrs and records calls
        self._clear_attr_mock = MagicMock()

        def clear_attr(key):
            self.attrs.pop(key, None)
            self._clear_attr_mock(key)

        self.clear_attr = clear_attr
        self.clear_attr.call_args_list = self._clear_attr_mock.call_args_list
        self.clear_attr.assert_called_once_with = self._clear_attr_mock.assert_called_once_with
        self.clear_attr.assert_called = self._clear_attr_mock.assert_called
        # Custom set_native_value: sets native_value and records calls
        self._set_native_value_mock = MagicMock()

        def set_native_value(value):
            self.native_value = value
            self._set_native_value_mock(value)

        self.set_native_value = set_native_value
        self.set_native_value.call_args_list = self._set_native_value_mock.call_args_list
        self.set_native_value.assert_any_call = self._set_native_value_mock.assert_any_call
        self.async_cleanup_attributes = AsyncMock()
        self.restore_previous_attr = AsyncMock(side_effect=self._restore_previous_attr)
        self.get_internal_attr = lambda: self.attrs

    def _set_attr(self, key, value):
        self.attrs[key] = value

    def _set_native_value(self, value):
        self.native_value = value

    def _clear_attr(self, key=None):
        """Remove only the specified key from attrs, not all attributes."""
        if key is not None and key in self.attrs:
            self.attrs.pop(key)

    def _restore_previous_attr(self, *args, **kwargs):
        pass

    def get_attr(self, key):
        """Retrieve the value of the specified attribute key from the sensor's attributes.

        Parameters:
            key: The attribute name to retrieve.

        Returns:
            The value associated with the given key, or None if the key is not present.

        """
        return self.attrs.get(key)

    async def in_zone(self):
        """Asynchronously determine whether the sensor is currently in the designated zone.

        Returns:
            bool: True if the sensor is in the zone, False otherwise.

        """
        return self._in_zone


class MockState:
    """A mock state object representing a Home Assistant entity.

    Attributes
    ----------
    entity_id : str
        The unique identifier for the entity.
    attributes : dict
        The attributes associated with the entity.

    Methods
    -------
    __init__(entity_id, attributes)
        Initialize the mock state with entity ID and attributes.

    """

    def __init__(self, entity_id, attributes):
        """Initialize an entity mock with the given entity ID and attributes.

        Parameters:
            entity_id (str): The unique identifier for the entity.
            attributes (dict): The attributes associated with the entity.

        """
        self.entity_id = entity_id
        self.attributes = attributes


@pytest.fixture(name="mock_hass")
def mock_hass():
    """Fixture that returns a comprehensive mock Home Assistant instance for all test types.

    Returns
    -------
    MagicMock
        A mock Home Assistant instance with mocked config entries, services, and options.

    """
    hass_instance = MagicMock()
    # Config entries
    hass_instance.config_entries = MagicMock()
    hass_instance.config_entries.async_forward_entry_setups = AsyncMock(return_value=True)
    # In Home Assistant this method is synchronous, so use MagicMock (AsyncMock caused un-awaited coroutine warnings in tests)
    hass_instance.config_entries.async_update_entry = MagicMock()
    hass_instance.config_entries.async_reload = AsyncMock()
    hass_instance.config_entries.async_unload_platforms = AsyncMock(return_value=True)
    # Options mocks
    hass_instance.config_entries.options = MagicMock()
    hass_instance.config_entries.options.async_init = AsyncMock(
        return_value={"type": "form", "flow_id": "abc", "data_schema": MagicMock()}
    )
    hass_instance.config_entries.options.async_configure = AsyncMock(
        return_value={"type": "create_entry"}
    )
    # Services
    hass_instance.services = MagicMock()
    # Other commonly used attributes
    hass_instance.config = MagicMock()
    hass_instance.bus = MagicMock()
    hass_instance.states = MagicMock()
    hass_instance.data = {}
    hass_instance.async_add_executor_job = AsyncMock()
    return hass_instance
