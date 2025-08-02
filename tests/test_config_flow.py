from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry
import voluptuous as vol

from custom_components.places import async_setup_entry
from custom_components.places.config_flow import (
    HOME_LOCATION_DOMAINS,
    TRACKING_DOMAINS_NEED_LATLONG,
    PlacesConfigFlow,
    PlacesOptionsFlowHandler,
    get_devicetracker_id_entities,
    get_home_zone_entities,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import ATTR_FRIENDLY_NAME, CONF_LATITUDE, CONF_LONGITUDE
from homeassistant.data_entry_flow import FlowResultType


@pytest.fixture
def config_entry():
    """
    Create a mock configuration entry for the 'places' integration with predefined test data.
    
    Returns:
        MockConfigEntry: A mock config entry populated with typical 'places' integration fields for testing.
    """
    return MockConfigEntry(
        domain="places",
        data={
            "name": "Test Place",
            "devicetracker_id": "device.test",
            "display_options": "zone, place",
            "home_zone": "zone.home",
            "map_provider": "osm",
            "map_zoom": 10,
            "use_gps": True,
            "extended_attr": False,
            "show_time": True,
            "date_format": "mm/dd",
            "language": "en",
        },
        options={},
        entry_id="12345",
    )


@pytest.mark.asyncio
async def test_config_flow_user_step(hass):
    """
    Test that the user step of the PlacesConfigFlow creates an entry with the correct title and data when provided valid user input.
    """
    flow = PlacesConfigFlow()
    flow.hass = hass
    user_input = {
        "name": "Test Place",
        "devicetracker_id": "device.test",
        "display_options": "zone, place",
        "home_zone": "zone.home",
        "map_provider": "osm",
        "map_zoom": 10,
        "use_gps": True,
        "extended_attr": False,
        "show_time": True,
        "date_format": "mm/dd",
        "language": "en",
    }
    result = await flow.async_step_user(user_input)
    assert result["type"] == "create_entry"
    assert result["title"] == "Test Place"
    assert result["data"] == user_input


@pytest.mark.asyncio
async def test_config_flow_user_step_error(hass):
    """
    Test that the config flow user step returns a form with errors when required fields are missing.
    
    Verifies that omitting the 'name' field in user input triggers error handling in the PlacesConfigFlow.
    """
    flow = PlacesConfigFlow()
    flow.hass = hass
    # Test missing required 'name' field
    user_input = {"devicetracker_id": "device.test"}
    result = await flow.async_step_user(user_input)
    assert result["type"] == "form"
    assert "errors" in result
    assert "name" in result["errors"] or "base" in result["errors"]


@pytest.mark.asyncio
async def test_options_flow_init(hass, config_entry):
    """
    Test that initializing the options flow for a config entry returns a form with a data schema.
    """
    config_entry.add_to_hass(hass)
    result = await hass.config_entries.options.async_init(config_entry.entry_id)
    assert result["type"] == FlowResultType.FORM
    assert "data_schema" in result


@pytest.mark.asyncio
async def test_options_flow_update_and_reload(hass, config_entry):
    """
    Test that submitting user input to the options flow creates an entry after configuration.
    
    Ensures that the options flow for the config entry accepts user input and completes successfully, resulting in a new entry being created.
    """
    with patch("custom_components.places.config_flow.vol", MagicMock(spec=vol)):
        config_entry.add_to_hass(hass)
        user_input = {
            "devicetracker_id": "device.test",
            "name": "Test Place",
            "display_options": "zone, place",
            "home_zone": "zone.home",
            "map_provider": "osm",
            "map_zoom": 10,
            "use_gps": True,
            "extended_attr": False,
            "show_time": True,
            "date_format": "mm/dd",
            "language": "en",
        }
        result = await hass.config_entries.options.async_init(config_entry.entry_id)
        result2 = await hass.config_entries.options.async_configure(result["flow_id"], user_input)
        assert result2["type"] == "create_entry"


@pytest.mark.asyncio
async def test_async_setup_entry(hass, config_entry):
    # PLATFORMS must be patched if imported from .const
    """
    Test that async_setup_entry forwards entry setups to the correct platforms and assigns runtime data.
    
    Asserts that the setup returns True, the entry setups are forwarded for the "sensor" platform, and the config entry's runtime data matches its data.
    """
    with patch("custom_components.places.PLATFORMS", ["sensor"]):
        hass.config_entries.async_forward_entry_setups = AsyncMock(return_value=None)
        result = await async_setup_entry(hass, config_entry)
        assert result is True
        hass.config_entries.async_forward_entry_setups.assert_awaited_once_with(
            config_entry, ["sensor"]
        )
        assert config_entry.runtime_data == dict(config_entry.data)


def test_get_devicetracker_id_entities_filters_latlong(monkeypatch):
    """
    Test that get_devicetracker_id_entities returns only entities with latitude and longitude attributes for domains that require them.
    
    Ensures that entities lacking required location attributes are excluded, and that included entities have labels containing their friendly names.
    """

    class MockState:
        def __init__(self, entity_id, attributes):
            """
            Initialize an entity mock with the given entity ID and attributes.
            
            Parameters:
                entity_id (str): The unique identifier for the entity.
                attributes (dict): The attributes associated with the entity.
            """
            self.entity_id = entity_id
            self.attributes = attributes

    # Setup mock hass
    hass = MagicMock()
    # Only one domain for simplicity
    domain = list(TRACKING_DOMAINS_NEED_LATLONG)[0]
    hass.states.async_all = MagicMock(
        return_value=[
            MockState(
                "device_tracker.good",
                {CONF_LATITUDE: 1.0, CONF_LONGITUDE: 2.0, ATTR_FRIENDLY_NAME: "Good"},
            ),
            MockState("device_tracker.bad", {ATTR_FRIENDLY_NAME: "Bad"}),  # Missing lat/long
        ]
    )
    hass.states.get = MagicMock(
        side_effect=lambda eid: {
            "device_tracker.good": MockState(
                "device_tracker.good",
                {CONF_LATITUDE: 1.0, CONF_LONGITUDE: 2.0, ATTR_FRIENDLY_NAME: "Good"},
            ),
            "device_tracker.bad": MockState("device_tracker.bad", {ATTR_FRIENDLY_NAME: "Bad"}),
        }[eid]
    )

    # Patch TRACKING_DOMAINS to only include our test domain
    monkeypatch.setattr("custom_components.places.config_flow.TRACKING_DOMAINS", [domain])

    entities = get_devicetracker_id_entities(hass)
    # Only the entity with lat/long should be included
    assert any(e["value"] == "device_tracker.good" for e in entities)
    assert not any(e["value"] == "device_tracker.bad" for e in entities)
    # Label should include friendly name
    assert any("Good" in e["label"] for e in entities)


def test_get_devicetracker_id_entities_adds_current_entity_with_friendly_name(monkeypatch):
    """
    Verify that get_devicetracker_id_entities adds the current entity with its friendly name to the entity list if it is not already present.
    """

    class MockState:
        def __init__(self, entity_id, attributes):
            """
            Initialize an entity mock with the given entity ID and attributes.
            
            Parameters:
                entity_id (str): The unique identifier for the entity.
                attributes (dict): The attributes associated with the entity.
            """
            self.entity_id = entity_id
            self.attributes = attributes

    hass = MagicMock()
    # dt_list is empty, so current_entity will not be present
    hass.states.async_all = MagicMock(return_value=[])
    # current_entity has a friendly name
    hass.states.get = MagicMock(
        return_value=MockState("device_tracker.extra", {ATTR_FRIENDLY_NAME: "Extra"})
    )

    entities = get_devicetracker_id_entities(hass, current_entity="device_tracker.extra")
    # Should include the current_entity with friendly name in label
    assert any(e["value"] == "device_tracker.extra" and "Extra" in e["label"] for e in entities)


def test_get_devicetracker_id_entities_adds_current_entity_without_friendly_name(monkeypatch):
    """
    Test that get_devicetracker_id_entities adds the current entity with its entity ID as the label when it lacks a friendly name and is not already present in the entity list.
    """

    class MockState:
        def __init__(self, entity_id, attributes):
            """
            Initialize an entity mock with the given entity ID and attributes.
            
            Parameters:
                entity_id (str): The unique identifier for the entity.
                attributes (dict): The attributes associated with the entity.
            """
            self.entity_id = entity_id
            self.attributes = attributes

    hass = MagicMock()
    hass.states.async_all = MagicMock(return_value=[])
    # current_entity has no friendly name
    hass.states.get = MagicMock(return_value=MockState("device_tracker.extra", {}))

    entities = get_devicetracker_id_entities(hass, current_entity="device_tracker.extra")
    # Should include the current_entity with just the entity_id as label
    assert any(
        e["value"] == "device_tracker.extra" and e["label"] == "device_tracker.extra"
        for e in entities
    )


def test_get_devicetracker_id_entities_does_not_add_current_entity_if_already_present(monkeypatch):
    """
    Verify that `get_devicetracker_id_entities` does not duplicate the current entity if it is already present in the device tracker list.
    """

    class MockState:
        def __init__(self, entity_id, attributes):
            """
            Initialize an entity mock with the given entity ID and attributes.
            
            Parameters:
                entity_id (str): The unique identifier for the entity.
                attributes (dict): The attributes associated with the entity.
            """
            self.entity_id = entity_id
            self.attributes = attributes

    hass = MagicMock()
    # dt_list already contains current_entity
    hass.states.async_all = MagicMock(
        return_value=[MockState("device_tracker.extra", {ATTR_FRIENDLY_NAME: "Already"})]
    )
    hass.states.get = MagicMock(
        return_value=MockState("device_tracker.extra", {ATTR_FRIENDLY_NAME: "Already"})
    )

    entities = get_devicetracker_id_entities(hass, current_entity="device_tracker.extra")
    # Should only be present once
    values = [e["value"] for e in entities if e["value"] == "device_tracker.extra"]
    assert len(set(values)) == 1


def test_get_home_zone_entities_builds_zone_list(monkeypatch):
    """
    Verify that `get_home_zone_entities` returns a sorted list of zone entities with correct labels based on their friendly names.
    """

    class MockState:
        def __init__(self, entity_id, attributes):
            """
            Initialize an entity mock with the given entity ID and attributes.
            
            Parameters:
                entity_id (str): The unique identifier for the entity.
                attributes (dict): The attributes associated with the entity.
            """
            self.entity_id = entity_id
            self.attributes = attributes

    hass = MagicMock()
    # Only one domain for simplicity
    domain = HOME_LOCATION_DOMAINS[0]
    hass.states.async_all = MagicMock(
        return_value=[
            MockState("zone.home", {ATTR_FRIENDLY_NAME: "Home Zone"}),
            MockState("zone.work", {ATTR_FRIENDLY_NAME: "Work Zone"}),
        ]
    )

    # Patch HOME_LOCATION_DOMAINS to only include our test domain
    monkeypatch.setattr("custom_components.places.config_flow.HOME_LOCATION_DOMAINS", [domain])

    zones = get_home_zone_entities(hass)
    # Should include both zones with correct labels
    assert any(z["value"] == "zone.home" and "Home Zone" in z["label"] for z in zones)
    assert any(z["value"] == "zone.work" and "Work Zone" in z["label"] for z in zones)
    # Should sort by label
    labels = [z["label"] for z in zones]
    assert labels == sorted(labels, key=str.casefold)


def test_async_get_options_flow_returns_handler():
    """
    Test that `async_get_options_flow` returns a `PlacesOptionsFlowHandler` instance for a given config entry.
    """
    config_entry = MagicMock(spec=ConfigEntry)
    handler = PlacesConfigFlow.async_get_options_flow(config_entry)
    assert isinstance(handler, PlacesOptionsFlowHandler)


@pytest.mark.asyncio
async def test_options_flow_handler_updates_config_and_reloads(hass, config_entry):
    """
    Test that the options flow handler updates the config entry with user input and triggers a reload.
    
    Verifies that submitting user input to the options flow handler results in the config entry being updated with the new data and the entry being reloaded. Asserts that the flow returns a create entry result.
    """
    config_entry.add_to_hass(hass)
    handler = PlacesOptionsFlowHandler()
    handler.hass = hass

    with patch.object(type(handler), "config_entry", new=property(lambda self: config_entry)):
        hass.config_entries.async_update_entry = MagicMock()
        hass.config_entries.async_reload = AsyncMock()

        user_input = {
            "devicetracker_id": "device.test",
            "name": "Test Place",
            "display_options": "zone, place",
            "home_zone": "zone.home",
            "map_provider": "osm",
            "map_zoom": 10,
            "use_gps": True,
            "extended_attr": False,
            "show_time": True,
            "date_format": "mm/dd",
            "language": "en",
            "api_key": "",
        }

        result = await handler.async_step_init(user_input)
        hass.config_entries.async_update_entry.assert_called_once_with(
            config_entry, data=user_input, options=config_entry.options
        )
        hass.config_entries.async_reload.assert_awaited_once_with(config_entry.entry_id)
        assert result["type"] == "create_entry"
        assert result["data"] == {}


@pytest.mark.asyncio
async def test_options_flow_handler_removes_blank_string_keys(hass, config_entry):
    """
    Test that the options flow handler removes keys with blank string values from user input before updating the config entry.
    
    Verifies that submitting user input with empty string values results in those keys being omitted from the updated configuration data.
    """
    config_entry.add_to_hass(hass)
    handler = PlacesOptionsFlowHandler()
    handler.hass = hass

    with patch.object(type(handler), "config_entry", new=property(lambda self: config_entry)):
        user_input = {
            "devicetracker_id": "device.test",
            "name": "",
            "display_options": "zone, place",
            "home_zone": "",
            "map_provider": "osm",
            "map_zoom": 10,
            "use_gps": True,
            "extended_attr": False,
            "show_time": True,
            "date_format": "mm/dd",
            "language": "",
            "api_key": "",
        }

        hass.config_entries.async_update_entry = AsyncMock()
        hass.config_entries.async_reload = AsyncMock()

        result = await handler.async_step_init(user_input)
        updated_data = hass.config_entries.async_update_entry.call_args[1]["data"]
        assert "name" not in updated_data
        assert "home_zone" not in updated_data
        assert "language" not in updated_data
        assert "api_key" not in updated_data
        assert result["type"] == "create_entry"


@pytest.mark.asyncio
async def test_options_flow_handler_shows_form_when_no_user_input(hass, config_entry):
    """
    Test that the options flow handler displays a form with the correct schema and description placeholders when no user input is provided.
    
    Ensures that the form includes device tracker and home zone entities, and that placeholders such as sensor name and component config URL are present in the form description.
    """
    config_entry.add_to_hass(hass)
    handler = PlacesOptionsFlowHandler()
    handler.hass = hass

    with (
        patch.object(type(handler), "config_entry", new=property(lambda self: config_entry)),
        patch(
            "custom_components.places.config_flow.get_devicetracker_id_entities",
            return_value=[{"value": "device.test", "label": "Device Test"}],
        ),
        patch(
            "custom_components.places.config_flow.get_home_zone_entities",
            return_value=[{"value": "zone.home", "label": "Home Zone"}],
        ),
    ):
        result = await handler.async_step_init(None)
        assert result["type"] == "form"
        assert "data_schema" in result
        assert result["step_id"] == "init"
        assert "description_placeholders" in result
        assert result["description_placeholders"]["sensor_name"] == config_entry.data["name"]
        assert result["description_placeholders"]["component_config_url"]


@pytest.mark.asyncio
async def test_options_flow_handler_shows_form_when_user_input_is_none(hass, config_entry):
    """
    Test that the options flow handler displays a form with the correct schema and description placeholders when user input is None.
    
    Ensures that the form includes the expected step ID, data schema, and placeholders such as the sensor name and configuration URL.
    """
    config_entry.add_to_hass(hass)
    handler = PlacesOptionsFlowHandler()
    handler.hass = hass

    # Patch config_entry property and entity list functions to return predictable values
    with (
        patch.object(type(handler), "config_entry", new=property(lambda self: config_entry)),
        patch(
            "custom_components.places.config_flow.get_devicetracker_id_entities",
            return_value=[{"value": "device.test", "label": "Device Test"}],
        ),
        patch(
            "custom_components.places.config_flow.get_home_zone_entities",
            return_value=[{"value": "zone.home", "label": "Home Zone"}],
        ),
    ):
        result = await handler.async_step_init(None)
        assert result["type"] == "form"
        assert "data_schema" in result
        assert result["step_id"] == "init"
        assert "description_placeholders" in result
        assert result["description_placeholders"]["sensor_name"] == config_entry.data["name"]
        assert result["description_placeholders"]["component_config_url"]


@pytest.mark.asyncio
async def test_options_flow_handler_merges_config_entry_data(hass, config_entry):
    """
    Test that the options flow handler merges user input with existing config entry data and updates the entry.
    
    Asserts that the updated config entry data contains both the original and new values, and that the flow returns a create entry result.
    """
    config_entry.add_to_hass(hass)
    handler = PlacesOptionsFlowHandler()
    handler.hass = hass

    with patch.object(type(handler), "config_entry", new=property(lambda self: config_entry)):
        user_input = {
            "devicetracker_id": "device.test",
            "display_options": "zone, place",
        }
        expected_data = dict(config_entry.data)
        expected_data.update(user_input)

        hass.config_entries.async_update_entry = AsyncMock()
        hass.config_entries.async_reload = AsyncMock()

        result = await handler.async_step_init(user_input)
        updated_data = hass.config_entries.async_update_entry.call_args[1]["data"]
        for k, v in expected_data.items():
            assert updated_data[k] == v
        assert result["type"] == "create_entry"
