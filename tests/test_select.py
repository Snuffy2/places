"""Tests for Places select entities."""

from unittest.mock import AsyncMock, MagicMock

from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.entity import EntityCategory
import pytest

from custom_components.places.config_schema import MAP_PROVIDER_OPTIONS
from custom_components.places.const import CONF_MAP_PROVIDER
from custom_components.places.select import PlacesMapProviderSelect, async_setup_entry


async def test_map_provider_select_setup_and_update() -> None:
    """The disabled config select exposes and updates the map provider."""
    coordinator = MagicMock()
    coordinator.get_attr_safe_str.return_value = "apple"
    coordinator.async_update_setting = AsyncMock()
    entry = MagicMock(runtime_data=coordinator)
    async_add_entities = MagicMock()

    await async_setup_entry(MagicMock(), entry, async_add_entities)

    entity = async_add_entities.call_args.args[0][0]
    assert entity.entity_category is EntityCategory.CONFIG
    assert entity.entity_registry_enabled_default is False
    assert entity.options == MAP_PROVIDER_OPTIONS
    assert entity.current_option == "apple"

    await entity.async_select_option("osm")

    coordinator.async_update_setting.assert_awaited_once_with(CONF_MAP_PROVIDER, "osm")


async def test_map_provider_select_propagates_coordinator_error() -> None:
    """An invalid provider selection propagates the coordinator's error."""
    coordinator = MagicMock()
    coordinator.async_update_setting = AsyncMock()
    entity = PlacesMapProviderSelect(coordinator)

    coordinator.async_update_setting.side_effect = HomeAssistantError("Invalid map provider")
    with pytest.raises(HomeAssistantError, match="Invalid map provider"):
        await entity.async_select_option("bing")

    coordinator.async_update_setting.assert_awaited_once_with(CONF_MAP_PROVIDER, "bing")


def test_map_provider_select_has_no_current_option_when_unconfigured() -> None:
    """An absent map provider should not be exposed as an empty option."""
    coordinator = MagicMock()
    coordinator.get_attr_safe_str.return_value = ""
    entity = PlacesMapProviderSelect(coordinator)

    assert entity.current_option is None
