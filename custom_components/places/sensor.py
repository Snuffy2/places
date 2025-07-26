"""Place Support for OpenStreetMap Geocode sensors.

Previous Authors:  Jim Thompson, Ian Richardson
Current Author:  Snuffy2

Description:
  Provides a sensor with a variable state consisting of reverse geocode (place) details for a linked device_tracker entity that provides GPS co-ordinates (ie owntracks, icloud)
  Allows you to specify a 'home_zone' for each device and calculates distance from home and direction of travel.
  Configuration Instructions are on GitHub.

GitHub: https://github.com/custom-components/places
"""

import asyncio
from collections.abc import MutableMapping
import contextlib
import copy
from datetime import datetime, timedelta
import json
import locale
import logging
import re
from typing import Any
from zoneinfo import ZoneInfo

import aiohttp
import cachetools

from homeassistant.components.recorder import DATA_INSTANCE as RECORDER_INSTANCE
from homeassistant.components.sensor import SensorEntity
from homeassistant.components.zone import ATTR_PASSIVE
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import (
    ATTR_ATTRIBUTION,
    ATTR_FRIENDLY_NAME,
    ATTR_GPS_ACCURACY,
    CONF_API_KEY,
    CONF_FRIENDLY_NAME,
    CONF_ICON,
    CONF_LATITUDE,
    CONF_LONGITUDE,
    CONF_NAME,
    CONF_UNIQUE_ID,
    CONF_ZONE,
    MATCH_ALL,
    STATE_UNAVAILABLE,
    STATE_UNKNOWN,
)
from homeassistant.core import Event, HomeAssistant, callback
from homeassistant.helpers.entity import generate_entity_id
from homeassistant.helpers.entity_platform import AddEntitiesCallback
import homeassistant.helpers.entity_registry as er
from homeassistant.helpers.event import EventStateChangedData, async_track_state_change_event
from homeassistant.util import Throttle, slugify
from homeassistant.util.location import distance

from .advanced_options import AdvancedOptionsParser
from .basic_options import build_basic_display, build_formatted_place
from .const import (
    ATTR_ATTRIBUTES,
    ATTR_CITY,
    ATTR_CITY_CLEAN,
    ATTR_COUNTRY,
    ATTR_COUNTRY_CODE,
    ATTR_COUNTY,
    ATTR_DEVICETRACKER_ID,
    ATTR_DEVICETRACKER_ZONE,
    ATTR_DEVICETRACKER_ZONE_NAME,
    ATTR_DIRECTION_OF_TRAVEL,
    ATTR_DISPLAY_OPTIONS,
    ATTR_DISPLAY_OPTIONS_LIST,
    ATTR_DISTANCE_FROM_HOME_KM,
    ATTR_DISTANCE_FROM_HOME_M,
    ATTR_DISTANCE_FROM_HOME_MI,
    ATTR_DISTANCE_TRAVELED_M,
    ATTR_DISTANCE_TRAVELED_MI,
    ATTR_DRIVING,
    ATTR_FORMATTED_ADDRESS,
    ATTR_FORMATTED_PLACE,
    ATTR_HOME_LATITUDE,
    ATTR_HOME_LOCATION,
    ATTR_HOME_LONGITUDE,
    ATTR_INITIAL_UPDATE,
    ATTR_JSON_FILENAME,
    ATTR_LAST_CHANGED,
    ATTR_LAST_PLACE_NAME,
    ATTR_LAST_UPDATED,
    ATTR_LATITUDE,
    ATTR_LATITUDE_OLD,
    ATTR_LOCATION_CURRENT,
    ATTR_LOCATION_PREVIOUS,
    ATTR_LONGITUDE,
    ATTR_LONGITUDE_OLD,
    ATTR_MAP_LINK,
    ATTR_NATIVE_VALUE,
    ATTR_OSM_DETAILS_DICT,
    ATTR_OSM_DICT,
    ATTR_OSM_ID,
    ATTR_OSM_TYPE,
    ATTR_PICTURE,
    ATTR_PLACE_CATEGORY,
    ATTR_PLACE_NAME,
    ATTR_PLACE_NAME_NO_DUPE,
    ATTR_PLACE_NEIGHBOURHOOD,
    ATTR_PLACE_TYPE,
    ATTR_POSTAL_CODE,
    ATTR_POSTAL_TOWN,
    ATTR_PREVIOUS_STATE,
    ATTR_REGION,
    ATTR_SHOW_DATE,
    ATTR_STATE_ABBR,
    ATTR_STREET,
    ATTR_STREET_NUMBER,
    ATTR_STREET_REF,
    ATTR_WIKIDATA_DICT,
    ATTR_WIKIDATA_ID,
    CONF_DATE_FORMAT,
    CONF_DEVICETRACKER_ID,
    CONF_DISPLAY_OPTIONS,
    CONF_EXTENDED_ATTR,
    CONF_HOME_ZONE,
    CONF_LANGUAGE,
    CONF_MAP_PROVIDER,
    CONF_MAP_ZOOM,
    CONF_SHOW_TIME,
    CONF_USE_GPS,
    CONFIG_ATTRIBUTES_LIST,
    DEFAULT_DATE_FORMAT,
    DEFAULT_DISPLAY_OPTIONS,
    DEFAULT_EXTENDED_ATTR,
    DEFAULT_HOME_ZONE,
    DEFAULT_ICON,
    DEFAULT_MAP_PROVIDER,
    DEFAULT_MAP_ZOOM,
    DEFAULT_SHOW_TIME,
    DEFAULT_USE_GPS,
    DISPLAY_OPTIONS_MAP,
    DOMAIN,
    ENTITY_ID_FORMAT,
    EVENT_ATTRIBUTE_LIST,
    EVENT_TYPE,
    EXTENDED_ATTRIBUTE_LIST,
    EXTRA_STATE_ATTRIBUTE_LIST,
    JSON_ATTRIBUTE_LIST,
    JSON_IGNORE_ATTRIBUTE_LIST,
    OSM_CACHE,
    OSM_CACHE_MAX_AGE_HOURS,
    OSM_CACHE_MAX_SIZE,
    OSM_THROTTLE,
    OSM_THROTTLE_INTERVAL_SECONDS,
    PLACE_NAME_DUPLICATE_LIST,
    PLATFORM,
    RESET_ATTRIBUTE_LIST,
    VERSION,
)
from .helpers import (
    create_json_folder,
    get_dict_from_json_file,
    is_float,
    remove_json_file,
    write_sensor_to_json,
)

_LOGGER: logging.Logger = logging.getLogger(__name__)
THROTTLE_INTERVAL = timedelta(seconds=600)
MIN_THROTTLE_INTERVAL = timedelta(seconds=10)
SCAN_INTERVAL = timedelta(seconds=30)


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Create places sensor entities."""
    # _LOGGER.debug("[aync_setup_entity] all entities: %s", hass.data.get(DOMAIN))

    config: MutableMapping[str, Any] = dict(config_entry.data)
    unique_id: str = config_entry.entry_id
    name: str = config[CONF_NAME]
    json_folder: str = hass.config.path("custom_components", DOMAIN, "json_sensors")
    await hass.async_add_executor_job(create_json_folder, json_folder)
    filename: str = f"{DOMAIN}-{slugify(unique_id)}.json"
    imported_attributes: MutableMapping[str, Any] = await hass.async_add_executor_job(
        get_dict_from_json_file, name, filename, json_folder
    )
    # _LOGGER.debug("[async_setup_entry] name: %s", name)
    # _LOGGER.debug("[async_setup_entry] unique_id: %s", unique_id)
    # _LOGGER.debug("[async_setup_entry] config: %s", config)

    if DOMAIN not in hass.data:
        hass.data[DOMAIN] = {}
    if OSM_CACHE not in hass.data[DOMAIN]:
        hass.data[DOMAIN][OSM_CACHE] = cachetools.TTLCache(
            maxsize=OSM_CACHE_MAX_SIZE, ttl=OSM_CACHE_MAX_AGE_HOURS * 3600
        )
    if OSM_THROTTLE not in hass.data[DOMAIN]:
        hass.data[DOMAIN][OSM_THROTTLE] = {
            "lock": asyncio.Lock(),
            "last_query": 0.0,
        }

    if config.get(CONF_EXTENDED_ATTR, DEFAULT_EXTENDED_ATTR):
        _LOGGER.debug("(%s) Extended Attr is True. Excluding from Recorder", name)
        async_add_entities(
            [
                PlacesNoRecorder(
                    hass=hass,
                    config=config,
                    config_entry=config_entry,
                    name=name,
                    unique_id=unique_id,
                    imported_attributes=imported_attributes,
                )
            ],
            update_before_add=True,
        )
    else:
        async_add_entities(
            [
                Places(
                    hass=hass,
                    config=config,
                    config_entry=config_entry,
                    name=name,
                    unique_id=unique_id,
                    imported_attributes=imported_attributes,
                )
            ],
            update_before_add=True,
        )


class Places(SensorEntity):
    """Representation of a Places Sensor."""

    def __init__(
        self,
        hass: HomeAssistant,
        config: MutableMapping[str, Any],
        config_entry: ConfigEntry,
        name: str,
        unique_id: str,
        imported_attributes: MutableMapping[str, Any],
    ) -> None:
        """Initialize the sensor."""
        self._attr_should_poll = True
        _LOGGER.info("(%s) [Init] Places sensor: %s", name, name)
        _LOGGER.debug("(%s) [Init] System Locale: %s", name, locale.getlocale())
        _LOGGER.debug(
            "(%s) [Init] System Locale Date Format: %s", name, locale.nl_langinfo(locale.D_FMT)
        )
        _LOGGER.debug("(%s) [Init] HASS TimeZone: %s", name, hass.config.time_zone)

        self._warn_if_device_tracker_prob = False
        self._internal_attr: MutableMapping[str, Any] = {}
        self._set_attr(ATTR_INITIAL_UPDATE, True)
        self._config: MutableMapping[str, Any] = config
        self._config_entry: ConfigEntry = config_entry
        self._hass: HomeAssistant = hass
        self._set_attr(CONF_NAME, name)
        self._attr_name: str = name
        self._set_attr(CONF_UNIQUE_ID, unique_id)
        self._attr_unique_id: str = unique_id
        registry: er.EntityRegistry | None = er.async_get(self._hass)
        self._json_folder: str = hass.config.path("custom_components", DOMAIN, "json_sensors")
        _LOGGER.debug("json_sensors Location: %s", self._json_folder)
        current_entity_id: str | None = None
        if registry:
            current_entity_id = registry.async_get_entity_id(PLATFORM, DOMAIN, self._attr_unique_id)
        if current_entity_id:
            self._entity_id: str = current_entity_id
        else:
            self._entity_id = generate_entity_id(
                ENTITY_ID_FORMAT, slugify(name.lower()), hass=self._hass
            )
        _LOGGER.debug("(%s) [Init] entity_id: %s", self._attr_name, self._entity_id)
        self._street_num_i: int = -1
        self._street_i: int = -1
        self._temp_i: int = 0
        self._adv_options_state_list: list = []
        self._set_attr(CONF_ICON, DEFAULT_ICON)
        self._attr_icon = DEFAULT_ICON
        self._set_attr(CONF_API_KEY, config.get(CONF_API_KEY))
        self._set_attr(
            CONF_DISPLAY_OPTIONS,
            config.setdefault(CONF_DISPLAY_OPTIONS, DEFAULT_DISPLAY_OPTIONS).lower(),
        )
        self._set_attr(CONF_DEVICETRACKER_ID, config[CONF_DEVICETRACKER_ID].lower())
        # Consider reconciling this in the future
        self._set_attr(ATTR_DEVICETRACKER_ID, config[CONF_DEVICETRACKER_ID].lower())
        self._set_attr(CONF_HOME_ZONE, config.setdefault(CONF_HOME_ZONE, DEFAULT_HOME_ZONE).lower())
        self._set_attr(
            CONF_MAP_PROVIDER,
            config.setdefault(CONF_MAP_PROVIDER, DEFAULT_MAP_PROVIDER).lower(),
        )
        self._set_attr(CONF_MAP_ZOOM, int(config.setdefault(CONF_MAP_ZOOM, DEFAULT_MAP_ZOOM)))
        self._set_attr(CONF_LANGUAGE, config.get(CONF_LANGUAGE))

        if not self.is_attr_blank(CONF_LANGUAGE):
            self._set_attr(
                CONF_LANGUAGE,
                self.get_attr_safe_str(CONF_LANGUAGE).replace(" ", "").strip(),
            )
        self._set_attr(
            CONF_EXTENDED_ATTR,
            config.setdefault(CONF_EXTENDED_ATTR, DEFAULT_EXTENDED_ATTR),
        )
        self._set_attr(CONF_SHOW_TIME, config.setdefault(CONF_SHOW_TIME, DEFAULT_SHOW_TIME))
        self._set_attr(
            CONF_DATE_FORMAT,
            config.setdefault(CONF_DATE_FORMAT, DEFAULT_DATE_FORMAT).lower(),
        )
        self._set_attr(CONF_USE_GPS, config.setdefault(CONF_USE_GPS, DEFAULT_USE_GPS))
        self._set_attr(
            ATTR_JSON_FILENAME,
            f"{DOMAIN}-{slugify(str(self.get_attr(CONF_UNIQUE_ID)))}.json",
        )
        self._set_attr(ATTR_DISPLAY_OPTIONS, self.get_attr(CONF_DISPLAY_OPTIONS))
        _LOGGER.debug(
            "(%s) [Init] JSON Filename: %s",
            self.get_attr(CONF_NAME),
            self.get_attr(ATTR_JSON_FILENAME),
        )

        self._attr_native_value = None  # Represents the state in SensorEntity
        self._clear_attr(ATTR_NATIVE_VALUE)

        if (
            not self.is_attr_blank(CONF_HOME_ZONE)
            and CONF_LATITUDE in hass.states.get(self.get_attr(CONF_HOME_ZONE)).attributes
            and hass.states.get(self.get_attr(CONF_HOME_ZONE)).attributes.get(CONF_LATITUDE)
            is not None
            and is_float(
                hass.states.get(self.get_attr(CONF_HOME_ZONE)).attributes.get(CONF_LATITUDE)
            )
        ):
            self._set_attr(
                ATTR_HOME_LATITUDE,
                str(hass.states.get(self.get_attr(CONF_HOME_ZONE)).attributes.get(CONF_LATITUDE)),
            )
        if (
            not self.is_attr_blank(CONF_HOME_ZONE)
            and CONF_LONGITUDE in hass.states.get(self.get_attr(CONF_HOME_ZONE)).attributes
            and hass.states.get(self.get_attr(CONF_HOME_ZONE)).attributes.get(CONF_LONGITUDE)
            is not None
            and is_float(
                hass.states.get(self.get_attr(CONF_HOME_ZONE)).attributes.get(CONF_LONGITUDE)
            )
        ):
            self._set_attr(
                ATTR_HOME_LONGITUDE,
                str(hass.states.get(self.get_attr(CONF_HOME_ZONE)).attributes.get(CONF_LONGITUDE)),
            )

        self._attr_entity_picture = (
            hass.states.get(self.get_attr(CONF_DEVICETRACKER_ID)).attributes.get(ATTR_PICTURE)
            if hass.states.get(self.get_attr(CONF_DEVICETRACKER_ID))
            else None
        )
        self._set_attr(ATTR_SHOW_DATE, False)

        self._import_attributes_from_json(imported_attributes)
        ##
        # For debugging:
        # imported_attributes = {}
        # imported_attributes.update({CONF_NAME: self.get_attr(CONF_NAME)})
        # imported_attributes.update({ATTR_NATIVE_VALUE: self.get_attr(ATTR_NATIVE_VALUE)})
        # imported_attributes.update(self.extra_state_attributes)
        # _LOGGER.debug("(%s) [Init] Sensor Attributes Imported: %s", self.get_attr(CONF_NAME), imported_attributes)
        ##
        if not self.get_attr(ATTR_INITIAL_UPDATE):
            _LOGGER.debug(
                "(%s) [Init] Sensor Attributes Imported from JSON file", self.get_attr(CONF_NAME)
            )
        self._cleanup_attributes()
        if self.get_attr(CONF_EXTENDED_ATTR):
            self._exclude_event_types()
        _LOGGER.info(
            "(%s) [Init] Tracked Entity ID: %s",
            self.get_attr(CONF_NAME),
            self.get_attr(CONF_DEVICETRACKER_ID),
        )

    def _exclude_event_types(self) -> None:
        if RECORDER_INSTANCE in self._hass.data:
            ha_history_recorder = self._hass.data[RECORDER_INSTANCE]
            ha_history_recorder.exclude_event_types.add(EVENT_TYPE)
            _LOGGER.debug(
                "(%s) exclude_event_types: %s",
                self.get_attr(CONF_NAME),
                ha_history_recorder.exclude_event_types,
            )

    async def async_added_to_hass(self) -> None:
        """Run after sensor is added to HA."""
        await super().async_added_to_hass()
        self.async_on_remove(
            async_track_state_change_event(
                self._hass,
                [str(self.get_attr(CONF_DEVICETRACKER_ID))],
                self._async_tsc_update,
            )
        )
        _LOGGER.debug(
            "(%s) [Init] Subscribed to Tracked Entity state change events",
            self.get_attr(CONF_NAME),
        )

    async def async_will_remove_from_hass(self) -> None:
        """Run when entity will be removed from hass."""

        await self._hass.async_add_executor_job(
            remove_json_file,
            self.get_attr(CONF_NAME),
            self.get_attr(ATTR_JSON_FILENAME),
            self._json_folder,
        )

        if RECORDER_INSTANCE in self._hass.data and self.get_attr(CONF_EXTENDED_ATTR):
            _LOGGER.debug(
                "(%s) Removing entity exclusion from recorder: %s", self._attr_name, self._entity_id
            )
            # Only do this if no places entities with extended_attr exist
            ex_attr_count = 0
            for ent in self._config_entry.runtime_data.values():
                if ent.get(CONF_EXTENDED_ATTR):
                    ex_attr_count += 1

            if (self.get_attr(CONF_EXTENDED_ATTR) and ex_attr_count == 1) or ex_attr_count == 0:
                _LOGGER.debug(
                    "(%s) Removing event exclusion from recorder: %s",
                    self.get_attr(CONF_NAME),
                    EVENT_TYPE,
                )
                ha_history_recorder = self._hass.data[RECORDER_INSTANCE]
                ha_history_recorder.exclude_event_types.discard(EVENT_TYPE)

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return the state attributes."""
        return_attr: dict[str, Any] = {}
        self._cleanup_attributes()
        for attr in EXTRA_STATE_ATTRIBUTE_LIST:
            if self.get_attr(attr):
                return_attr.update({attr: self.get_attr(attr)})

        if self.get_attr(CONF_EXTENDED_ATTR):
            for attr in EXTENDED_ATTRIBUTE_LIST:
                if self.get_attr(attr):
                    return_attr.update({attr: self.get_attr(attr)})
        # _LOGGER.debug("(%s) Extra State Attributes: %s", self.get_attr(CONF_NAME), return_attr)
        return return_attr

    def _import_attributes_from_json(self, json_attr: MutableMapping[str, Any]) -> None:
        """Import the JSON state attributes. Takes a Dictionary as input."""

        self._set_attr(ATTR_INITIAL_UPDATE, False)
        for attr in JSON_ATTRIBUTE_LIST:
            if attr in json_attr:
                self._set_attr(attr, json_attr.pop(attr, None))
        if not self.is_attr_blank(ATTR_NATIVE_VALUE):
            self._attr_native_value = self.get_attr(ATTR_NATIVE_VALUE)

        # Remove attributes that are part of the Config and are explicitly not imported from JSON
        for attr in CONFIG_ATTRIBUTES_LIST + JSON_IGNORE_ATTRIBUTE_LIST:
            if attr in json_attr:
                json_attr.pop(attr, None)
        if json_attr is not None and json_attr:
            _LOGGER.debug(
                "(%s) [import_attributes] Attributes not imported: %s",
                self.get_attr(CONF_NAME),
                json_attr,
            )

    def _cleanup_attributes(self) -> None:
        for attr in list(self._internal_attr):
            if self.is_attr_blank(attr):
                self._clear_attr(attr)

    def is_attr_blank(self, attr: str) -> bool:
        """Check if an attribute is blank or not set."""
        if self._internal_attr.get(attr) or self._internal_attr.get(attr) == 0:
            return False
        return True

    def get_attr(self, attr: str | None, default: Any | None = None) -> None | Any:
        """Get an attribute value, returning None if not set."""
        if attr is None or (default is None and self.is_attr_blank(attr)):
            return None
        return self._internal_attr.get(attr, default)

    def get_attr_safe_str(self, attr: str | None, default: Any | None = None) -> str:
        """Get an attribute value as a string, returning an empty string if not set."""
        value: None | Any = self.get_attr(attr=attr, default=default)
        if value is not None:
            try:
                return str(value)
            except ValueError:
                return ""
        return ""

    def get_attr_safe_float(self, attr: str | None, default: Any | None = None) -> float:
        """Get an attribute value as a float, returning 0 if not set or not a float."""
        value: None | Any = self.get_attr(attr=attr, default=default)
        if not isinstance(value, float):
            return 0
        return value

    def get_attr_safe_list(self, attr: str | None, default: Any | None = None) -> list:
        """Get an attribute value as a list, returning an empty list if not set or not a list."""
        value: None | Any = self.get_attr(attr=attr, default=default)
        if not isinstance(value, list):
            return []
        return value

    def get_attr_safe_dict(self, attr: str | None, default: Any | None = None) -> MutableMapping:
        """Get an attribute value as a dictionary, returning an empty dict if not set or not a dict."""
        value: None | Any = self.get_attr(attr=attr, default=default)
        if not isinstance(value, MutableMapping):
            return {}
        return value

    def _set_attr(self, attr: str, value: Any | None = None) -> None:
        if attr:
            self._internal_attr.update({attr: value})

    def _clear_attr(self, attr: str) -> None:
        self._internal_attr.pop(attr, None)

    async def _async_is_devicetracker_set(self) -> int:
        proceed_with_update = 0
        # 0: False. 1: True. 2: False, but set direction of travel to stationary

        if (
            self.is_attr_blank(CONF_DEVICETRACKER_ID)
            or self._hass.states.get(self.get_attr(CONF_DEVICETRACKER_ID)) is None
            or (
                isinstance(
                    self._hass.states.get(self.get_attr(CONF_DEVICETRACKER_ID)),
                    str,
                )
                and self._hass.states.get(self.get_attr(CONF_DEVICETRACKER_ID)).lower()
                in {"none", STATE_UNKNOWN, STATE_UNAVAILABLE}
            )
        ):
            if self._warn_if_device_tracker_prob or self.get_attr(ATTR_INITIAL_UPDATE):
                _LOGGER.warning(
                    "(%s) Tracked Entity (%s) "
                    "is not set or is not available. Not Proceeding with Update",
                    self.get_attr(CONF_NAME),
                    self.get_attr(CONF_DEVICETRACKER_ID),
                )
                self._warn_if_device_tracker_prob = False
            else:
                _LOGGER.info(
                    "(%s) Tracked Entity (%s) "
                    "is not set or is not available. Not Proceeding with Update",
                    self.get_attr(CONF_NAME),
                    self.get_attr(CONF_DEVICETRACKER_ID),
                )
            return 0
            # 0: False. 1: True. 2: False, but set direction of travel to stationary
        if (
            hasattr(
                self._hass.states.get(self.get_attr(CONF_DEVICETRACKER_ID)),
                ATTR_ATTRIBUTES,
            )
            and CONF_LATITUDE
            in self._hass.states.get(self.get_attr(CONF_DEVICETRACKER_ID)).attributes
            and CONF_LONGITUDE
            in self._hass.states.get(self.get_attr(CONF_DEVICETRACKER_ID)).attributes
            and self._hass.states.get(self.get_attr(CONF_DEVICETRACKER_ID)).attributes.get(
                CONF_LATITUDE
            )
            is not None
            and self._hass.states.get(self.get_attr(CONF_DEVICETRACKER_ID)).attributes.get(
                CONF_LONGITUDE
            )
            is not None
            and is_float(
                self._hass.states.get(self.get_attr(CONF_DEVICETRACKER_ID)).attributes.get(
                    CONF_LATITUDE
                )
            )
            and is_float(
                self._hass.states.get(self.get_attr(CONF_DEVICETRACKER_ID)).attributes.get(
                    CONF_LONGITUDE
                )
            )
        ):
            self._warn_if_device_tracker_prob = True
            proceed_with_update = 1
            # 0: False. 1: True. 2: False, but set direction of travel to stationary
        else:
            if self._warn_if_device_tracker_prob or self.get_attr(ATTR_INITIAL_UPDATE):
                _LOGGER.warning(
                    "(%s) Tracked Entity (%s) "
                    "Latitude/Longitude is not set or is not a number. Not Proceeding with Update.",
                    self.get_attr(CONF_NAME),
                    self.get_attr(CONF_DEVICETRACKER_ID),
                )
                self._warn_if_device_tracker_prob = False
            else:
                _LOGGER.info(
                    "(%s) Tracked Entity (%s) "
                    "Latitude/Longitude is not set or is not a number. Not Proceeding with Update.",
                    self.get_attr(CONF_NAME),
                    self.get_attr(CONF_DEVICETRACKER_ID),
                )
            _LOGGER.debug(
                "(%s) Tracked Entity (%s) details: %s",
                self.get_attr(CONF_NAME),
                self.get_attr(CONF_DEVICETRACKER_ID),
                self._hass.states.get(self.get_attr(CONF_DEVICETRACKER_ID)),
            )
            return 0
            # 0: False. 1: True. 2: False, but set direction of travel to stationary
        return proceed_with_update

    @Throttle(MIN_THROTTLE_INTERVAL)
    @callback
    def _async_tsc_update(self, event: Event[EventStateChangedData]) -> None:
        """Call the _async_do_update function based on the TSC (track state change) event."""
        # _LOGGER.debug(f"({self.get_attr(CONF_NAME)}) [TSC Update] event: {event}")
        new_state = event.data["new_state"]
        if new_state is None or (
            isinstance(new_state.state, str)
            and new_state.state.lower() in {"none", STATE_UNKNOWN, STATE_UNAVAILABLE}
        ):
            return
        # _LOGGER.debug("(%s) [TSC Update] new_state: %s", self.get_attr(CONF_NAME), new_state)

        update_type: str = "Track State Change"
        self._hass.async_create_task(self._async_do_update(update_type))

    @Throttle(THROTTLE_INTERVAL)
    async def async_update(self) -> None:
        """Call the _async_do_update function based on scan interval and throttle."""
        update_type = "Scan Interval"
        self._hass.async_create_task(self._async_do_update(update_type))

    @staticmethod
    async def _async_clear_since_from_state(orig_state: str) -> str:
        return re.sub(r" \(since \d\d[:/]\d\d\)", "", orig_state)

    async def async_in_zone(self) -> bool:
        """Check if the tracked entity is in a zone."""
        if not self.is_attr_blank(ATTR_DEVICETRACKER_ZONE):
            zone: str = self.get_attr_safe_str(ATTR_DEVICETRACKER_ZONE).lower()
            zone_state = self._hass.states.get(f"{CONF_ZONE}.{zone}")
            if (
                self.get_attr_safe_str(CONF_DEVICETRACKER_ID).split(".")[0] == CONF_ZONE
                or (
                    "stationary" in zone
                    or zone.startswith(("statzon", "ic3_statzone_"))
                    or zone in {"away", "not_home", "notset", "not_set"}
                )
                or (
                    zone_state is not None
                    and zone_state.attributes.get(ATTR_PASSIVE, False) is True
                )
            ):
                return False
            return True
        return False

    async def _async_cleanup_attributes(self) -> None:
        attrs: MutableMapping[str, Any] = copy.deepcopy(self._internal_attr)
        for attr in attrs:
            if self.is_attr_blank(attr):
                self._clear_attr(attr)

    async def _async_check_for_updated_entity_name(self) -> None:
        if hasattr(self, "entity_id") and self._entity_id is not None:
            # _LOGGER.debug("(%s) Entity ID: %s", self.get_attr(CONF_NAME), self._entity_id)
            if (
                self._hass.states.get(str(self._entity_id)) is not None
                and self._hass.states.get(str(self._entity_id)).attributes.get(ATTR_FRIENDLY_NAME)
                is not None
                and self.get_attr(CONF_NAME)
                != self._hass.states.get(str(self._entity_id)).attributes.get(ATTR_FRIENDLY_NAME)
            ):
                _LOGGER.debug(
                    "(%s) Sensor Name Changed. Updating Name to: %s",
                    self.get_attr(CONF_NAME),
                    self._hass.states.get(str(self._entity_id)).attributes.get(ATTR_FRIENDLY_NAME),
                )
                self._set_attr(
                    CONF_NAME,
                    self._hass.states.get(str(self._entity_id)).attributes.get(ATTR_FRIENDLY_NAME),
                )
                self._config.update({CONF_NAME: self.get_attr(CONF_NAME)})
                self._set_attr(CONF_NAME, self.get_attr(CONF_NAME))
                _LOGGER.debug(
                    "(%s) Updated Config Name: %s",
                    self.get_attr(CONF_NAME),
                    self._config.get(CONF_NAME),
                )
                self._hass.config_entries.async_update_entry(
                    self._config_entry,
                    data=self._config,
                    options=self._config_entry.options,
                )
                _LOGGER.debug(
                    "(%s) Updated ConfigEntry Name: %s",
                    self.get_attr(CONF_NAME),
                    self._config_entry.data.get(CONF_NAME),
                )

    async def _async_get_zone_details(self) -> None:
        if self.get_attr_safe_str(CONF_DEVICETRACKER_ID).split(".")[0] != CONF_ZONE:
            self._set_attr(
                ATTR_DEVICETRACKER_ZONE,
                self._hass.states.get(self.get_attr(CONF_DEVICETRACKER_ID)).state,
            )
        if await self.async_in_zone():
            devicetracker_zone_name_state = None
            devicetracker_zone_id: str | None = self._hass.states.get(
                self.get_attr(CONF_DEVICETRACKER_ID)
            ).attributes.get(CONF_ZONE)
            if devicetracker_zone_id:
                devicetracker_zone_id = f"{CONF_ZONE}.{devicetracker_zone_id}"
                devicetracker_zone_name_state = self._hass.states.get(devicetracker_zone_id)
            # _LOGGER.debug("(%s) Tracked Entity Zone ID: %s", self.get_attr(CONF_NAME), devicetracker_zone_id)
            # _LOGGER.debug("(%s) Tracked Entity Zone Name State: %s", self.get_attr(CONF_NAME), devicetracker_zone_name_state)
            if devicetracker_zone_name_state:
                if devicetracker_zone_name_state.attributes.get(CONF_FRIENDLY_NAME):
                    self._set_attr(
                        ATTR_DEVICETRACKER_ZONE_NAME,
                        devicetracker_zone_name_state.attributes.get(CONF_FRIENDLY_NAME),
                    )
                else:
                    self._set_attr(ATTR_DEVICETRACKER_ZONE_NAME, devicetracker_zone_name_state.name)
            else:
                self._set_attr(
                    ATTR_DEVICETRACKER_ZONE_NAME,
                    self.get_attr(ATTR_DEVICETRACKER_ZONE),
                )

            if not self.is_attr_blank(ATTR_DEVICETRACKER_ZONE_NAME) and (
                self.get_attr_safe_str(ATTR_DEVICETRACKER_ZONE_NAME)
            ).lower() == self.get_attr(ATTR_DEVICETRACKER_ZONE_NAME):
                self._set_attr(
                    ATTR_DEVICETRACKER_ZONE_NAME,
                    self.get_attr_safe_str(ATTR_DEVICETRACKER_ZONE_NAME).title(),
                )
            _LOGGER.debug(
                "(%s) Tracked Entity Zone Name: %s",
                self.get_attr(CONF_NAME),
                self.get_attr(ATTR_DEVICETRACKER_ZONE_NAME),
            )
        else:
            _LOGGER.debug(
                "(%s) Tracked Entity Zone: %s",
                self.get_attr(CONF_NAME),
                self.get_attr(ATTR_DEVICETRACKER_ZONE),
            )
            self._set_attr(
                ATTR_DEVICETRACKER_ZONE_NAME,
                self.get_attr(ATTR_DEVICETRACKER_ZONE),
            )

    async def _async_determine_if_update_needed(self) -> int:
        proceed_with_update = 1
        # 0: False. 1: True. 2: False, but set direction of travel to stationary

        if self.get_attr(ATTR_INITIAL_UPDATE):
            _LOGGER.info("(%s) Performing Initial Update for user", self.get_attr(CONF_NAME))
            # 0: False. 1: True. 2: False, but set direction of travel to stationary
            return 1

        if self.is_attr_blank(ATTR_NATIVE_VALUE) or (
            isinstance(self.get_attr(ATTR_NATIVE_VALUE), str)
            and self.get_attr_safe_str(ATTR_NATIVE_VALUE).lower()
            in {"none", STATE_UNKNOWN, STATE_UNAVAILABLE}
        ):
            _LOGGER.info(
                "(%s) Previous State is Unknown, performing update", self.get_attr(CONF_NAME)
            )
            # 0: False. 1: True. 2: False, but set direction of travel to stationary
            return 1

        if self.get_attr(ATTR_LOCATION_CURRENT) == self.get_attr(ATTR_LOCATION_PREVIOUS):
            _LOGGER.info(
                "(%s) Not performing update because coordinates are identical",
                self.get_attr(CONF_NAME),
            )
            return 2
            # 0: False. 1: True. 2: False, but set direction of travel to stationary
        if int(self.get_attr_safe_float(ATTR_DISTANCE_TRAVELED_M)) < 10:
            _LOGGER.info(
                "(%s) "
                "Not performing update, distance traveled from last update is less than 10 m (%s m)",
                self.get_attr(CONF_NAME),
                round(self.get_attr_safe_float(ATTR_DISTANCE_TRAVELED_M), 1),
            )
            return 2
            # 0: False. 1: True. 2: False, but set direction of travel to stationary
        return proceed_with_update
        # 0: False. 1: True. 2: False, but set direction of travel to stationary

    async def _get_dict_from_url(self, url: str, name: str, dict_name: str) -> None:
        osm_cache = self._hass.data[DOMAIN][OSM_CACHE]
        if url in osm_cache:
            self._set_attr(dict_name, osm_cache[url])
            _LOGGER.debug(
                "(%s) %s data loaded from cache (Cache size: %s)",
                self.get_attr(CONF_NAME),
                name,
                len(osm_cache),
            )
            return

        throttle = self._hass.data[DOMAIN][OSM_THROTTLE]
        async with throttle["lock"]:
            now = asyncio.get_running_loop().time()
            wait_time = max(0, OSM_THROTTLE_INTERVAL_SECONDS - (now - throttle["last_query"]))
            if wait_time > 0:
                await asyncio.sleep(wait_time)
            throttle["last_query"] = asyncio.get_running_loop().time()

            _LOGGER.info("(%s) Requesting data for %s", self.get_attr(CONF_NAME), name)
            _LOGGER.debug("(%s) %s URL: %s", self.get_attr(CONF_NAME), name, url)
            self._set_attr(dict_name, {})
            headers: dict[str, str] = {
                "user-agent": f"Mozilla/5.0 (Home Assistant) {DOMAIN}/{VERSION}"
            }
            get_dict = None

            try:
                async with (
                    aiohttp.ClientSession(headers=headers) as session,
                    session.get(url, timeout=aiohttp.ClientTimeout(total=10)) as response,
                ):
                    get_json_input = await response.text()
                    _LOGGER.debug(
                        "(%s) %s Response: %s", self.get_attr(CONF_NAME), name, get_json_input
                    )
                    try:
                        get_dict = json.loads(get_json_input)
                    except json.decoder.JSONDecodeError as e:
                        _LOGGER.warning(
                            "(%s) JSON Decode Error with %s info [%s: %s]: %s",
                            self.get_attr(CONF_NAME),
                            name,
                            type(e).__name__,
                            e,
                            get_json_input,
                        )
                        return
            except (aiohttp.ClientError, TimeoutError, OSError) as e:
                _LOGGER.warning(
                    "(%s) Error connecting to %s [%s: %s]: %s",
                    self.get_attr(CONF_NAME),
                    name,
                    type(e).__name__,
                    e,
                    url,
                )
                return

            if get_dict is None:
                return

            if "error_message" in get_dict:
                _LOGGER.warning(
                    "(%s) An error occurred contacting the web service for %s: %s",
                    self.get_attr(CONF_NAME),
                    name,
                    get_dict.get("error_message"),
                )
                return

            if (
                isinstance(get_dict, list)
                and len(get_dict) == 1
                and isinstance(get_dict[0], MutableMapping)
            ):
                self._set_attr(dict_name, get_dict[0])
                osm_cache[url] = get_dict[0]
                return

            self._set_attr(dict_name, get_dict)
            osm_cache[url] = get_dict
            return

    async def _async_get_map_link(self) -> None:
        if self.get_attr(CONF_MAP_PROVIDER) == "google":
            self._set_attr(
                ATTR_MAP_LINK,
                (
                    "https://maps.google.com/?q="
                    f"{self.get_attr(ATTR_LOCATION_CURRENT)}"
                    f"&ll={self.get_attr(ATTR_LOCATION_CURRENT)}"
                    f"&z={self.get_attr(CONF_MAP_ZOOM)}"
                ),
            )
        elif self.get_attr(CONF_MAP_PROVIDER) == "osm":
            self._set_attr(
                ATTR_MAP_LINK,
                (
                    "https://www.openstreetmap.org/?mlat="
                    f"{self.get_attr(ATTR_LATITUDE)}"
                    f"&mlon={self.get_attr(ATTR_LONGITUDE)}"
                    f"#map={self.get_attr(CONF_MAP_ZOOM)}/"
                    f"{self.get_attr_safe_str(ATTR_LATITUDE)[:8]}/"
                    f"{self.get_attr_safe_str(ATTR_LONGITUDE)[:9]}"
                ),
            )
        else:
            self._set_attr(
                ATTR_MAP_LINK,
                (
                    "https://maps.apple.com/?q="
                    f"{self.get_attr(ATTR_LOCATION_CURRENT)}"
                    f"&z={self.get_attr(CONF_MAP_ZOOM)}"
                ),
            )
        _LOGGER.debug(
            "(%s) Map Link Type: %s", self.get_attr(CONF_NAME), self.get_attr(CONF_MAP_PROVIDER)
        )
        _LOGGER.debug(
            "(%s) Map Link URL: %s", self.get_attr(CONF_NAME), self.get_attr(ATTR_MAP_LINK)
        )

    async def _async_get_gps_accuracy(self) -> int:
        if (
            self._hass.states.get(self.get_attr(CONF_DEVICETRACKER_ID))
            and self._hass.states.get(self.get_attr(CONF_DEVICETRACKER_ID)).attributes
            and ATTR_GPS_ACCURACY
            in self._hass.states.get(self.get_attr(CONF_DEVICETRACKER_ID)).attributes
            and self._hass.states.get(self.get_attr(CONF_DEVICETRACKER_ID)).attributes.get(
                ATTR_GPS_ACCURACY
            )
            is not None
            and is_float(
                self._hass.states.get(self.get_attr(CONF_DEVICETRACKER_ID)).attributes.get(
                    ATTR_GPS_ACCURACY
                )
            )
        ):
            self._set_attr(
                ATTR_GPS_ACCURACY,
                float(
                    self._hass.states.get(self.get_attr(CONF_DEVICETRACKER_ID)).attributes.get(
                        ATTR_GPS_ACCURACY
                    )
                ),
            )
        else:
            _LOGGER.debug(
                "(%s) GPS Accuracy attribute not found in: %s",
                self.get_attr(CONF_NAME),
                self.get_attr(CONF_DEVICETRACKER_ID),
            )
        proceed_with_update = 1
        # 0: False. 1: True. 2: False, but set direction of travel to stationary

        if not self.is_attr_blank(ATTR_GPS_ACCURACY):
            if self.get_attr(CONF_USE_GPS) and self.get_attr(ATTR_GPS_ACCURACY) == 0:
                proceed_with_update = 0
                # 0: False. 1: True. 2: False, but set direction of travel to stationary
                _LOGGER.info(
                    "(%s) GPS Accuracy is 0.0, not performing update", self.get_attr(CONF_NAME)
                )
            else:
                _LOGGER.debug(
                    "(%s) GPS Accuracy: %s",
                    self.get_attr(CONF_NAME),
                    round(self.get_attr_safe_float(ATTR_GPS_ACCURACY), 3),
                )
        return proceed_with_update

    async def _async_get_driving_status(self) -> None:
        self._clear_attr(ATTR_DRIVING)
        isDriving: bool = False
        if not await self.async_in_zone():
            if self.get_attr(ATTR_DIRECTION_OF_TRAVEL) != "stationary" and (
                self.get_attr(ATTR_PLACE_CATEGORY) == "highway"
                or self.get_attr(ATTR_PLACE_TYPE) == "motorway"
            ):
                isDriving = True
        if isDriving:
            self._set_attr(ATTR_DRIVING, "Driving")

    async def _async_parse_osm_dict(self) -> None:
        osm_dict: MutableMapping[str, Any] | None = self.get_attr(ATTR_OSM_DICT)
        if not osm_dict:
            return

        await self._set_attribution(osm_dict=osm_dict)
        await self._parse_type(osm_dict=osm_dict)
        await self._parse_category(osm_dict=osm_dict)
        await self._parse_namedetails(osm_dict=osm_dict)
        await self._parse_address(osm_dict=osm_dict)
        await self._parse_miscellaneous(osm_dict=osm_dict)
        await self._set_place_name_no_dupe()

        _LOGGER.debug(
            "(%s) Entity attributes after parsing OSM Dict: %s",
            self.get_attr(CONF_NAME),
            self._internal_attr,
        )

    async def _set_attribution(self, osm_dict: MutableMapping[str, Any]) -> None:
        if "licence" not in osm_dict:
            return
        attribution: str | None = osm_dict.get("licence")
        if attribution:
            self._set_attr(ATTR_ATTRIBUTION, attribution)
        #     _LOGGER.debug(
        #         "(%s) OSM Attribution: %s",
        #         self.get_attr(CONF_NAME),
        #         self.get_attr(ATTR_ATTRIBUTION),
        #     )
        # else:
        #     _LOGGER.debug("(%s) No OSM Attribution found", self.get_attr(CONF_NAME))

    async def _parse_type(self, osm_dict: MutableMapping[str, Any]) -> None:
        if "type" not in osm_dict:
            return
        self._set_attr(ATTR_PLACE_TYPE, osm_dict.get("type"))
        if self.get_attr(ATTR_PLACE_TYPE) == "yes":
            if "addresstype" in osm_dict:
                self._set_attr(
                    ATTR_PLACE_TYPE,
                    osm_dict.get("addresstype"),
                )
            else:
                self._clear_attr(ATTR_PLACE_TYPE)
        if "address" in osm_dict and self.get_attr(ATTR_PLACE_TYPE) in osm_dict["address"]:
            self._set_attr(
                ATTR_PLACE_NAME,
                osm_dict["address"].get(self.get_attr(ATTR_PLACE_TYPE)),
            )

    async def _parse_category(self, osm_dict: MutableMapping[str, Any]) -> None:
        if "category" not in osm_dict:
            return

        self._set_attr(
            ATTR_PLACE_CATEGORY,
            osm_dict.get("category"),
        )
        if "address" in osm_dict and self.get_attr(ATTR_PLACE_CATEGORY) in osm_dict["address"]:
            self._set_attr(
                ATTR_PLACE_NAME,
                osm_dict["address"].get(self.get_attr(ATTR_PLACE_CATEGORY)),
            )

    async def _parse_namedetails(self, osm_dict: MutableMapping[str, Any]) -> None:
        namedetails: MutableMapping[str, Any] | None = osm_dict.get("namedetails")
        if not namedetails:
            return
        if "name" in namedetails:
            self._set_attr(
                ATTR_PLACE_NAME,
                namedetails.get("name"),
            )
        if not self.is_attr_blank(CONF_LANGUAGE):
            for language in self.get_attr_safe_str(CONF_LANGUAGE).split(","):
                if f"name:{language}" in namedetails:
                    self._set_attr(
                        ATTR_PLACE_NAME,
                        namedetails.get(f"name:{language}"),
                    )
                    break

    async def _parse_address(self, osm_dict: MutableMapping[str, Any]) -> None:
        address: MutableMapping[str, Any] | None = osm_dict.get("address")
        if not address:
            return

        await self._set_address_details(address)
        await self._set_city_details(address)
        await self._set_region_details(address)

    async def _set_address_details(self, address: MutableMapping[str, Any]) -> None:
        if "house_number" in address:
            self._set_attr(
                ATTR_STREET_NUMBER,
                address.get("house_number"),
            )
        if "road" in address:
            self._set_attr(
                ATTR_STREET,
                address.get("road"),
            )
        if "retail" in address and (
            self.is_attr_blank(ATTR_PLACE_NAME)
            or (
                not self.is_attr_blank(ATTR_PLACE_CATEGORY)
                and not self.is_attr_blank(ATTR_STREET)
                and self.get_attr(ATTR_PLACE_CATEGORY) == "highway"
                and self.get_attr(ATTR_STREET) == self.get_attr(ATTR_PLACE_NAME)
            )
        ):
            self._set_attr(
                ATTR_PLACE_NAME,
                self.get_attr_safe_dict(ATTR_OSM_DICT).get("address", {}).get("retail"),
            )
        _LOGGER.debug(
            "(%s) Place Name: %s", self.get_attr(CONF_NAME), self.get_attr(ATTR_PLACE_NAME)
        )

    async def _set_city_details(self, address: MutableMapping[str, Any]) -> None:
        CITY_LIST: list[str] = [
            "city",
            "town",
            "village",
            "township",
            "hamlet",
            "city_district",
            "municipality",
        ]
        POSTAL_TOWN_LIST: list[str] = [
            "city",
            "town",
            "village",
            "township",
            "hamlet",
            "borough",
            "suburb",
        ]
        NEIGHBOURHOOD_LIST: list[str] = [
            "village",
            "township",
            "hamlet",
            "borough",
            "suburb",
            "quarter",
            "neighbourhood",
        ]
        for city_type in CITY_LIST:
            with contextlib.suppress(ValueError):
                POSTAL_TOWN_LIST.remove(city_type)

            with contextlib.suppress(ValueError):
                NEIGHBOURHOOD_LIST.remove(city_type)
            if city_type in address:
                self._set_attr(
                    ATTR_CITY,
                    address.get(city_type),
                )
                break
        for postal_town_type in POSTAL_TOWN_LIST:
            with contextlib.suppress(ValueError):
                NEIGHBOURHOOD_LIST.remove(postal_town_type)
            if postal_town_type in address:
                self._set_attr(
                    ATTR_POSTAL_TOWN,
                    address.get(postal_town_type),
                )
                break
        for neighbourhood_type in NEIGHBOURHOOD_LIST:
            if neighbourhood_type in address:
                self._set_attr(
                    ATTR_PLACE_NEIGHBOURHOOD,
                    address.get(neighbourhood_type),
                )
                break

        if not self.is_attr_blank(ATTR_CITY):
            self._set_attr(
                ATTR_CITY_CLEAN,
                self.get_attr_safe_str(ATTR_CITY).replace(" Township", "").strip(),
            )
            if self.get_attr_safe_str(ATTR_CITY_CLEAN).startswith("City of"):
                self._set_attr(
                    ATTR_CITY_CLEAN,
                    f"{self.get_attr_safe_str(ATTR_CITY_CLEAN)[8:]} City",
                )

    async def _set_region_details(self, address: MutableMapping[str, Any]) -> None:
        if "state" in address:
            self._set_attr(
                ATTR_REGION,
                address.get("state"),
            )
        if "ISO3166-2-lvl4" in address:
            self._set_attr(
                ATTR_STATE_ABBR,
                address["ISO3166-2-lvl4"].split("-")[1].upper(),
            )
        if "county" in address:
            self._set_attr(
                ATTR_COUNTY,
                address.get("county"),
            )
        if "country" in address:
            self._set_attr(
                ATTR_COUNTRY,
                address.get("country"),
            )
        if "country_code" in address:
            self._set_attr(
                ATTR_COUNTRY_CODE,
                address["country_code"].upper(),
            )
        if "postcode" in address:
            self._set_attr(
                ATTR_POSTAL_CODE,
                self.get_attr_safe_dict(ATTR_OSM_DICT).get("address", {}).get("postcode"),
            )

    async def _parse_miscellaneous(self, osm_dict: MutableMapping[str, Any]) -> None:
        if "display_name" in osm_dict:
            self._set_attr(
                ATTR_FORMATTED_ADDRESS,
                osm_dict.get("display_name"),
            )

        if "osm_id" in osm_dict:
            self._set_attr(
                ATTR_OSM_ID,
                str(self.get_attr_safe_dict(ATTR_OSM_DICT).get("osm_id", "")),
            )
        if "osm_type" in osm_dict:
            self._set_attr(
                ATTR_OSM_TYPE,
                osm_dict.get("osm_type"),
            )

        if (
            not self.is_attr_blank(ATTR_PLACE_CATEGORY)
            and self.get_attr_safe_str(ATTR_PLACE_CATEGORY).lower() == "highway"
            and "namedetails" in osm_dict
            and osm_dict.get("namedetails") is not None
            and "ref" in osm_dict["namedetails"]
        ):
            street_refs: list = re.split(
                r"[\;\\\/\,\.\:]",
                osm_dict["namedetails"].get("ref"),
            )
            street_refs = [i for i in street_refs if i.strip()]  # Remove blank strings
            # _LOGGER.debug("(%s) Street Refs: %s", self.get_attr(CONF_NAME), street_refs)
            for ref in street_refs:
                if bool(re.search(r"\d", ref)):
                    self._set_attr(ATTR_STREET_REF, ref)
                    break
            if not self.is_attr_blank(ATTR_STREET_REF):
                _LOGGER.debug(
                    "(%s) Street: %s / Street Ref: %s",
                    self.get_attr(CONF_NAME),
                    self.get_attr(ATTR_STREET),
                    self.get_attr(ATTR_STREET_REF),
                )

    async def _set_place_name_no_dupe(self) -> None:
        dupe_attributes_check: list[str] = []
        dupe_attributes_check.extend(
            [
                self.get_attr_safe_str(attr)
                for attr in PLACE_NAME_DUPLICATE_LIST
                if not self.is_attr_blank(attr)
            ]
        )
        if (
            not self.is_attr_blank(ATTR_PLACE_NAME)
            and self.get_attr(ATTR_PLACE_NAME) not in dupe_attributes_check
        ):
            self._set_attr(ATTR_PLACE_NAME_NO_DUPE, self.get_attr(ATTR_PLACE_NAME))

    async def _async_build_formatted_place(self) -> None:
        formatted_place = await build_formatted_place(
            internal_attr=self._internal_attr,
            display_options=self.get_attr_safe_list(ATTR_DISPLAY_OPTIONS_LIST),
            sensor=self,
        )
        self._set_attr(ATTR_FORMATTED_PLACE, formatted_place)

    async def async_get_option_state(
        self,
        opt: str,
        incl: list | None = None,
        excl: list | None = None,
        incl_attr: MutableMapping[str, Any] | None = None,
        excl_attr: MutableMapping[str, Any] | None = None,
    ) -> str | None:
        """Get the state of a display option."""
        incl = [] if incl is None else incl
        excl = [] if excl is None else excl
        incl_attr = {} if incl_attr is None else incl_attr
        excl_attr = {} if excl_attr is None else excl_attr
        if opt:
            opt = str(opt).lower().strip()
        _LOGGER.debug("(%s) [get_option_state] Option: %s", self.get_attr(CONF_NAME), opt)
        out: str | None = self.get_attr(DISPLAY_OPTIONS_MAP.get(opt))
        if (
            DISPLAY_OPTIONS_MAP.get(opt) in {ATTR_DEVICETRACKER_ZONE, ATTR_DEVICETRACKER_ZONE_NAME}
            and not await self.async_in_zone()
        ):
            out = None
        _LOGGER.debug("(%s) [get_option_state] State: %s", self.get_attr(CONF_NAME), out)
        _LOGGER.debug("(%s) [get_option_state] incl list: %s", self.get_attr(CONF_NAME), incl)
        _LOGGER.debug("(%s) [get_option_state] excl list: %s", self.get_attr(CONF_NAME), excl)
        _LOGGER.debug(
            "(%s) [get_option_state] incl_attr dict: %s", self.get_attr(CONF_NAME), incl_attr
        )
        _LOGGER.debug(
            "(%s) [get_option_state] excl_attr dict: %s", self.get_attr(CONF_NAME), excl_attr
        )
        if out:
            if (
                incl
                and str(out).strip().lower() not in incl
                or excl
                and str(out).strip().lower() in excl
            ):
                out = None
            if incl_attr:
                for attr, states in incl_attr.items():
                    _LOGGER.debug(
                        "(%s) [get_option_state] incl_attr: %s / State: %s",
                        self.get_attr(CONF_NAME),
                        attr,
                        self.get_attr(DISPLAY_OPTIONS_MAP.get(attr)),
                    )
                    _LOGGER.debug(
                        "(%s) [get_option_state] incl_states: %s", self.get_attr(CONF_NAME), states
                    )
                    map_attr: str | None = DISPLAY_OPTIONS_MAP.get(attr)
                    if (
                        not map_attr
                        or self.is_attr_blank(map_attr)
                        or self.get_attr(map_attr) not in states
                    ):
                        out = None
            if excl_attr:
                for attr, states in excl_attr.items():
                    _LOGGER.debug(
                        "(%s) [get_option_state] excl_attr: %s / State: %s",
                        self.get_attr(CONF_NAME),
                        attr,
                        self.get_attr(DISPLAY_OPTIONS_MAP.get(attr)),
                    )
                    _LOGGER.debug(
                        "(%s) [get_option_state] excl_states: %s", self.get_attr(CONF_NAME), states
                    )
                    if self.get_attr(DISPLAY_OPTIONS_MAP.get(attr)) in states:
                        out = None
            _LOGGER.debug(
                "(%s) [get_option_state] State after incl/excl: %s", self.get_attr(CONF_NAME), out
            )
        if out:
            if out == out.lower() and (
                DISPLAY_OPTIONS_MAP.get(opt) == ATTR_DEVICETRACKER_ZONE_NAME
                or DISPLAY_OPTIONS_MAP.get(opt) == ATTR_PLACE_TYPE
                or DISPLAY_OPTIONS_MAP.get(opt) == ATTR_PLACE_CATEGORY
            ):
                out = out.title()
            out = out.strip()
            if (
                DISPLAY_OPTIONS_MAP.get(opt) == ATTR_STREET
                or DISPLAY_OPTIONS_MAP.get(opt) == ATTR_STREET_REF
            ):
                self._street_i = self._temp_i
                # _LOGGER.debug(
                #     "(%s) [get_option_state] street_i: %s",
                #     self.get_attr(CONF_NAME),
                #     self._street_i,
                # )
            if DISPLAY_OPTIONS_MAP.get(opt) == ATTR_STREET_NUMBER:
                self._street_num_i = self._temp_i
                # _LOGGER.debug(
                #     "(%s) [get_option_state] street_num_i: %s",
                #     self.get_attr(CONF_NAME),
                #     self._street_num_i,
                # )
            self._temp_i += 1
            return out
        return None

    async def _async_build_state_from_display_options(self) -> None:
        display_options: list[str] = self.get_attr_safe_list(ATTR_DISPLAY_OPTIONS_LIST)
        state = await build_basic_display(
            internal_attr=self._internal_attr, display_options=display_options, sensor=self
        )
        if state:
            self._set_attr(ATTR_NATIVE_VALUE, state)
        _LOGGER.debug(
            "(%s) New State from Display Options: %s",
            self.get_attr(CONF_NAME),
            self.get_attr(ATTR_NATIVE_VALUE),
        )

    async def _async_get_extended_attr(self) -> None:
        if not self.is_attr_blank(ATTR_OSM_ID) and not self.is_attr_blank(ATTR_OSM_TYPE):
            if self.get_attr_safe_str(ATTR_OSM_TYPE).lower() == "node":
                osm_type_abbr = "N"
            elif self.get_attr_safe_str(ATTR_OSM_TYPE).lower() == "way":
                osm_type_abbr = "W"
            elif self.get_attr_safe_str(ATTR_OSM_TYPE).lower() == "relation":
                osm_type_abbr = "R"

            osm_details_url: str = (
                "https://nominatim.openstreetmap.org/lookup?osm_ids="
                f"{osm_type_abbr}{self.get_attr(ATTR_OSM_ID)}"
                "&format=json&addressdetails=1&extratags=1&namedetails=1"
                f"&email={
                    self.get_attr(CONF_API_KEY) if not self.is_attr_blank(CONF_API_KEY) else ''
                }"
                f"&accept-language={
                    self.get_attr(CONF_LANGUAGE) if not self.is_attr_blank(CONF_LANGUAGE) else ''
                }"
            )
            await self._get_dict_from_url(
                url=osm_details_url,
                name="OpenStreetMaps Details",
                dict_name=ATTR_OSM_DETAILS_DICT,
            )

            if not self.is_attr_blank(ATTR_OSM_DETAILS_DICT):
                osm_details_dict = self.get_attr_safe_dict(ATTR_OSM_DETAILS_DICT)
                _LOGGER.debug(
                    "(%s) OSM Details Dict: %s", self.get_attr(CONF_NAME), osm_details_dict
                )

                if (
                    "extratags" in osm_details_dict
                    and osm_details_dict.get("extratags") is not None
                    and "wikidata" in osm_details_dict.get("extratags", {})
                    and osm_details_dict.get("extratags", {}).get("wikidata") is not None
                ):
                    self._set_attr(
                        ATTR_WIKIDATA_ID,
                        osm_details_dict.get("extratags", {}).get("wikidata"),
                    )

                self._set_attr(ATTR_WIKIDATA_DICT, {})
                if not self.is_attr_blank(ATTR_WIKIDATA_ID):
                    wikidata_url: str = f"https://www.wikidata.org/wiki/Special:EntityData/{
                        self.get_attr(ATTR_WIKIDATA_ID)
                    }.json"
                    await self._get_dict_from_url(
                        url=wikidata_url,
                        name="Wikidata",
                        dict_name=ATTR_WIKIDATA_DICT,
                    )

    async def _async_fire_event_data(self, prev_last_place_name: str) -> None:
        _LOGGER.debug("(%s) Building Event Data", self.get_attr(CONF_NAME))
        event_data: MutableMapping[str, Any] = {}
        if not self.is_attr_blank(CONF_NAME):
            event_data.update({"entity": self.get_attr(CONF_NAME)})
        if not self.is_attr_blank(ATTR_PREVIOUS_STATE):
            event_data.update({"from_state": self.get_attr(ATTR_PREVIOUS_STATE)})
        if not self.is_attr_blank(ATTR_NATIVE_VALUE):
            event_data.update({"to_state": self.get_attr(ATTR_NATIVE_VALUE)})

        for attr in EVENT_ATTRIBUTE_LIST:
            if not self.is_attr_blank(attr):
                event_data.update({attr: self.get_attr(attr)})

        if (
            not self.is_attr_blank(ATTR_LAST_PLACE_NAME)
            and self.get_attr(ATTR_LAST_PLACE_NAME) != prev_last_place_name
        ):
            event_data.update({ATTR_LAST_PLACE_NAME: self.get_attr(ATTR_LAST_PLACE_NAME)})

        if self.get_attr(CONF_EXTENDED_ATTR):
            for attr in EXTENDED_ATTRIBUTE_LIST:
                if not self.is_attr_blank(attr):
                    event_data.update({attr: self.get_attr(attr)})

        self._hass.bus.fire(EVENT_TYPE, event_data)
        _LOGGER.debug(
            "(%s) Event Details [event_type: %s_state_update]: %s",
            self.get_attr(CONF_NAME),
            DOMAIN,
            event_data,
        )
        _LOGGER.info(
            "(%s) Event Fired [event_type: %s_state_update]", self.get_attr(CONF_NAME), DOMAIN
        )

    async def _async_get_initial_last_place_name(self) -> None:
        _LOGGER.debug(
            "(%s) Previous State: %s",
            self.get_attr(CONF_NAME),
            self.get_attr(ATTR_PREVIOUS_STATE),
        )
        _LOGGER.debug(
            "(%s) Previous last_place_name: %s",
            self.get_attr(CONF_NAME),
            self.get_attr(ATTR_LAST_PLACE_NAME),
        )

        if not await self.async_in_zone():
            # Previously Not in a Zone
            if not self.is_attr_blank(ATTR_PLACE_NAME):
                # If place name is set
                self._set_attr(ATTR_LAST_PLACE_NAME, self.get_attr(ATTR_PLACE_NAME))
                _LOGGER.debug(
                    "(%s) Previous place is Place Name, last_place_name is set: %s",
                    self.get_attr(CONF_NAME),
                    self.get_attr(ATTR_LAST_PLACE_NAME),
                )
            else:
                # If blank, keep previous last_place_name
                _LOGGER.debug(
                    "(%s) Previous Place Name is None, keeping prior", self.get_attr(CONF_NAME)
                )
        else:
            # Previously In a Zone
            self._set_attr(
                ATTR_LAST_PLACE_NAME,
                self.get_attr(ATTR_DEVICETRACKER_ZONE_NAME),
            )
            _LOGGER.debug(
                "(%s) Previous Place is Zone: %s",
                self.get_attr(CONF_NAME),
                self.get_attr(ATTR_LAST_PLACE_NAME),
            )
        _LOGGER.debug(
            "(%s) last_place_name (Initial): %s",
            self.get_attr(CONF_NAME),
            self.get_attr(ATTR_LAST_PLACE_NAME),
        )

    async def _async_update_coordinates_and_distance(self) -> int:
        last_distance_traveled_m: float = self.get_attr_safe_float(ATTR_DISTANCE_FROM_HOME_M)
        proceed_with_update = 1
        # 0: False. 1: True. 2: False, but set direction of travel to stationary

        if not self.is_attr_blank(ATTR_LATITUDE) and not self.is_attr_blank(ATTR_LONGITUDE):
            self._set_attr(
                ATTR_LOCATION_CURRENT,
                f"{self.get_attr(ATTR_LATITUDE)},{self.get_attr(ATTR_LONGITUDE)}",
            )
        if not self.is_attr_blank(ATTR_LATITUDE_OLD) and not self.is_attr_blank(ATTR_LONGITUDE_OLD):
            self._set_attr(
                ATTR_LOCATION_PREVIOUS,
                f"{self.get_attr(ATTR_LATITUDE_OLD)},{self.get_attr(ATTR_LONGITUDE_OLD)}",
            )
        if not self.is_attr_blank(ATTR_HOME_LATITUDE) and not self.is_attr_blank(
            ATTR_HOME_LONGITUDE
        ):
            self._set_attr(
                ATTR_HOME_LOCATION,
                f"{self.get_attr(ATTR_HOME_LATITUDE)},{self.get_attr(ATTR_HOME_LONGITUDE)}",
            )

        if (
            not self.is_attr_blank(ATTR_LATITUDE)
            and not self.is_attr_blank(ATTR_LONGITUDE)
            and not self.is_attr_blank(ATTR_HOME_LATITUDE)
            and not self.is_attr_blank(ATTR_HOME_LONGITUDE)
        ):
            self._set_attr(
                ATTR_DISTANCE_FROM_HOME_M,
                distance(
                    float(self.get_attr_safe_str(ATTR_LATITUDE)),
                    float(self.get_attr_safe_str(ATTR_LONGITUDE)),
                    float(self.get_attr_safe_str(ATTR_HOME_LATITUDE)),
                    float(self.get_attr_safe_str(ATTR_HOME_LONGITUDE)),
                ),
            )
            if not self.is_attr_blank(ATTR_DISTANCE_FROM_HOME_M):
                self._set_attr(
                    ATTR_DISTANCE_FROM_HOME_KM,
                    round(self.get_attr_safe_float(ATTR_DISTANCE_FROM_HOME_M) / 1000, 3),
                )
                self._set_attr(
                    ATTR_DISTANCE_FROM_HOME_MI,
                    round(self.get_attr_safe_float(ATTR_DISTANCE_FROM_HOME_M) / 1609, 3),
                )

            if not self.is_attr_blank(ATTR_LATITUDE_OLD) and not self.is_attr_blank(
                ATTR_LONGITUDE_OLD
            ):
                self._set_attr(
                    ATTR_DISTANCE_TRAVELED_M,
                    distance(
                        float(self.get_attr_safe_str(ATTR_LATITUDE)),
                        float(self.get_attr_safe_str(ATTR_LONGITUDE)),
                        float(self.get_attr_safe_str(ATTR_LATITUDE_OLD)),
                        float(self.get_attr_safe_str(ATTR_LONGITUDE_OLD)),
                    ),
                )
                if not self.is_attr_blank(ATTR_DISTANCE_TRAVELED_M):
                    self._set_attr(
                        ATTR_DISTANCE_TRAVELED_MI,
                        round(
                            self.get_attr_safe_float(ATTR_DISTANCE_TRAVELED_M) / 1609,
                            3,
                        ),
                    )

                if last_distance_traveled_m > self.get_attr_safe_float(ATTR_DISTANCE_FROM_HOME_M):
                    self._set_attr(ATTR_DIRECTION_OF_TRAVEL, "towards home")
                elif last_distance_traveled_m < self.get_attr_safe_float(ATTR_DISTANCE_FROM_HOME_M):
                    self._set_attr(ATTR_DIRECTION_OF_TRAVEL, "away from home")
                else:
                    self._set_attr(ATTR_DIRECTION_OF_TRAVEL, "stationary")
            else:
                self._set_attr(ATTR_DIRECTION_OF_TRAVEL, "stationary")
                self._set_attr(ATTR_DISTANCE_TRAVELED_M, 0)
                self._set_attr(ATTR_DISTANCE_TRAVELED_MI, 0)

            _LOGGER.debug(
                "(%s) Previous Location: %s",
                self.get_attr(CONF_NAME),
                self.get_attr(ATTR_LOCATION_PREVIOUS),
            )
            _LOGGER.debug(
                "(%s) Current Location: %s",
                self.get_attr(CONF_NAME),
                self.get_attr(ATTR_LOCATION_CURRENT),
            )
            _LOGGER.debug(
                "(%s) Home Location: %s",
                self.get_attr(CONF_NAME),
                self.get_attr(ATTR_HOME_LOCATION),
            )
            _LOGGER.info(
                "(%s) Distance from home [%s]: %s km",
                self.get_attr(CONF_NAME),
                self.get_attr_safe_str(CONF_HOME_ZONE).split(".")[1],
                self.get_attr(ATTR_DISTANCE_FROM_HOME_KM),
            )
            _LOGGER.info(
                "(%s) Travel Direction: %s",
                self.get_attr(CONF_NAME),
                self.get_attr(ATTR_DIRECTION_OF_TRAVEL),
            )
            _LOGGER.info(
                "(%s) Meters traveled since last update: %s",
                self.get_attr(CONF_NAME),
                round(self.get_attr_safe_float(ATTR_DISTANCE_TRAVELED_M), 1),
            )
        else:
            proceed_with_update = 0
            # 0: False. 1: True. 2: False, but set direction of travel to stationary
            _LOGGER.info(
                "(%s) Problem with updated lat/long, not performing update: "
                "old_latitude=%s, old_longitude=%s, "
                "new_latitude=%s, new_longitude=%s, "
                "home_latitude=%s, home_longitude=%s",
                self.get_attr(CONF_NAME),
                self.get_attr(ATTR_LATITUDE_OLD),
                self.get_attr(ATTR_LONGITUDE_OLD),
                self.get_attr(ATTR_LATITUDE),
                self.get_attr(ATTR_LONGITUDE),
                self.get_attr(ATTR_HOME_LATITUDE),
                self.get_attr(ATTR_HOME_LONGITUDE),
            )
        return proceed_with_update

    async def _async_finalize_last_place_name(self, prev_last_place_name: str) -> None:
        if self.get_attr(ATTR_INITIAL_UPDATE):
            self._set_attr(ATTR_LAST_PLACE_NAME, prev_last_place_name)
            _LOGGER.debug(
                "(%s) Runnining initial update after load, using prior last_place_name",
                self.get_attr(CONF_NAME),
            )
        elif self.get_attr(ATTR_LAST_PLACE_NAME) == self.get_attr(ATTR_PLACE_NAME) or self.get_attr(
            ATTR_LAST_PLACE_NAME
        ) == self.get_attr(ATTR_DEVICETRACKER_ZONE_NAME):
            # If current place name/zone are the same as previous, keep older last_place_name
            self._set_attr(ATTR_LAST_PLACE_NAME, prev_last_place_name)
            _LOGGER.debug(
                "(%s) Initial last_place_name is same as new: place_name=%s or devicetracker_zone_name=%s, "
                "keeping previous last_place_name",
                self.get_attr(CONF_NAME),
                self.get_attr(ATTR_PLACE_NAME),
                self.get_attr(ATTR_DEVICETRACKER_ZONE_NAME),
            )
        else:
            _LOGGER.debug("(%s) Keeping initial last_place_name", self.get_attr(CONF_NAME))
        _LOGGER.info(
            "(%s) last_place_name: %s",
            self.get_attr(CONF_NAME),
            self.get_attr(ATTR_LAST_PLACE_NAME),
        )

    async def _async_do_update(self, reason: str) -> None:
        """Get the latest data and updates the states."""
        _LOGGER.info(
            "(%s) Starting %s Update (Tracked Entity: %s)",
            self.get_attr(CONF_NAME),
            reason,
            self.get_attr(CONF_DEVICETRACKER_ID),
        )

        now: datetime = await self._get_current_time()
        previous_attr: MutableMapping[str, Any] = copy.deepcopy(self._internal_attr)

        await self._update_entity_name_and_cleanup()
        await self._update_previous_state()
        await self._update_old_coordinates()
        prev_last_place_name = self.get_attr_safe_str(ATTR_LAST_PLACE_NAME)

        # 0: False. 1: True. 2: False, but set direction of travel to stationary
        proceed_with_update: int = await self._check_device_tracker_and_update_coords()

        if proceed_with_update == 1:
            proceed_with_update = await self._determine_update_criteria()

        if proceed_with_update == 1:
            await self._process_osm_update(now=now)

            if await self._should_update_state(now=now):
                await self._handle_state_update(now=now, prev_last_place_name=prev_last_place_name)
            else:
                _LOGGER.info(
                    "(%s) No entity update needed, Previous State = New State",
                    self.get_attr(CONF_NAME),
                )
                await self._rollback_update(previous_attr, now, proceed_with_update)
        else:
            await self._rollback_update(previous_attr, now, proceed_with_update)

        self._set_attr(ATTR_LAST_UPDATED, now.isoformat(sep=" ", timespec="seconds"))
        _LOGGER.info("(%s) End of Update", self.get_attr(CONF_NAME))

    async def _should_update_state(self, now: datetime) -> bool:
        prev_state: str = self.get_attr_safe_str(ATTR_PREVIOUS_STATE)
        native_value: str = self.get_attr_safe_str(ATTR_NATIVE_VALUE)
        tracker_zone: str = self.get_attr_safe_str(ATTR_DEVICETRACKER_ZONE)

        if (
            (
                not self.is_attr_blank(ATTR_PREVIOUS_STATE)
                and not self.is_attr_blank(ATTR_NATIVE_VALUE)
                and prev_state.lower().strip() != native_value.lower().strip()
                and prev_state.replace(" ", "").lower().strip() != native_value.lower().strip()
                and prev_state.lower().strip() != tracker_zone.lower().strip()
            )
            or self.is_attr_blank(ATTR_PREVIOUS_STATE)
            or self.is_attr_blank(ATTR_NATIVE_VALUE)
            or self.get_attr(ATTR_INITIAL_UPDATE)
        ):
            return True
        return False

    async def _handle_state_update(self, now: datetime, prev_last_place_name: str) -> None:
        if self.get_attr(CONF_EXTENDED_ATTR):
            await self._async_get_extended_attr()
        self._set_attr(ATTR_SHOW_DATE, False)
        await self._async_cleanup_attributes()

        if not self.is_attr_blank(ATTR_NATIVE_VALUE):
            current_time: str = f"{now.hour:02}:{now.minute:02}"
            if self.get_attr(CONF_SHOW_TIME):
                state: str = await Places._async_clear_since_from_state(
                    self.get_attr_safe_str(ATTR_NATIVE_VALUE)
                )
                self._set_attr(ATTR_NATIVE_VALUE, f"{state[: 255 - 14]} (since {current_time})")
            else:
                self._set_attr(ATTR_NATIVE_VALUE, self.get_attr_safe_str(ATTR_NATIVE_VALUE)[:255])
            _LOGGER.info(
                "(%s) New State: %s",
                self.get_attr(CONF_NAME),
                self.get_attr(ATTR_NATIVE_VALUE),
            )
        else:
            self._clear_attr(ATTR_NATIVE_VALUE)
            _LOGGER.warning("(%s) New State is None", self.get_attr(CONF_NAME))

        if not self.is_attr_blank(ATTR_NATIVE_VALUE):
            self._attr_native_value = self.get_attr(ATTR_NATIVE_VALUE)
        else:
            self._attr_native_value = None

        await self._async_fire_event_data(prev_last_place_name=prev_last_place_name)
        self._set_attr(ATTR_INITIAL_UPDATE, False)
        await self._hass.async_add_executor_job(
            write_sensor_to_json,
            self._internal_attr,
            self.get_attr(CONF_NAME),
            self.get_attr(ATTR_JSON_FILENAME),
            self._json_folder,
        )

    async def _rollback_update(
        self, previous_attr: MutableMapping[str, Any], now: datetime, proceed_with_update: int
    ) -> None:
        self._internal_attr = previous_attr
        _LOGGER.debug(
            "(%s) Reverting attributes back to before the update started", self.get_attr(CONF_NAME)
        )
        changed_diff_sec = await self._async_get_seconds_from_last_change(now=now)
        if (
            proceed_with_update == 2
            and self.get_attr(ATTR_DIRECTION_OF_TRAVEL) != "stationary"
            and changed_diff_sec >= 60
        ):
            await self._async_change_dot_to_stationary(now=now, changed_diff_sec=changed_diff_sec)
        if (
            self.get_attr(CONF_SHOW_TIME)
            and changed_diff_sec >= 86399
            and not self.get_attr(ATTR_SHOW_DATE)
        ):
            await self._async_change_show_time_to_date()

    async def _get_current_time(self) -> datetime:
        if self._hass.config.time_zone:
            return datetime.now(tz=ZoneInfo(str(self._hass.config.time_zone)))
        return datetime.now()

    async def _update_entity_name_and_cleanup(self) -> None:
        await self._async_check_for_updated_entity_name()
        await self._async_cleanup_attributes()

    async def _update_previous_state(self) -> None:
        if not self.is_attr_blank(ATTR_NATIVE_VALUE) and self.get_attr(CONF_SHOW_TIME):
            self._set_attr(
                ATTR_PREVIOUS_STATE,
                await Places._async_clear_since_from_state(
                    orig_state=self.get_attr_safe_str(ATTR_NATIVE_VALUE)
                ),
            )
        else:
            self._set_attr(ATTR_PREVIOUS_STATE, self.get_attr(ATTR_NATIVE_VALUE))

    async def _update_old_coordinates(self) -> None:
        if is_float(self.get_attr(ATTR_LATITUDE)):
            self._set_attr(ATTR_LATITUDE_OLD, str(self.get_attr(ATTR_LATITUDE)))
        if is_float(self.get_attr(ATTR_LONGITUDE)):
            self._set_attr(ATTR_LONGITUDE_OLD, str(self.get_attr(ATTR_LONGITUDE)))

    async def _check_device_tracker_and_update_coords(self) -> int:
        proceed_with_update: int = await self._async_is_devicetracker_set()
        _LOGGER.debug(
            "(%s) [is_devicetracker_set] proceed_with_update: %s",
            self.get_attr(CONF_NAME),
            proceed_with_update,
        )
        if proceed_with_update == 1:
            await self._update_coordinates()
            proceed_with_update = await self._async_get_gps_accuracy()
            _LOGGER.debug(
                "(%s) [is_devicetracker_set] proceed_with_update: %s",
                self.get_attr(CONF_NAME),
                proceed_with_update,
            )
        return proceed_with_update

    async def _update_coordinates(self) -> None:
        device_tracker = self._hass.states.get(self.get_attr(CONF_DEVICETRACKER_ID))
        if is_float(device_tracker.attributes.get(CONF_LATITUDE)):
            self._set_attr(ATTR_LATITUDE, str(device_tracker.attributes.get(CONF_LATITUDE)))
        if is_float(device_tracker.attributes.get(CONF_LONGITUDE)):
            self._set_attr(ATTR_LONGITUDE, str(device_tracker.attributes.get(CONF_LONGITUDE)))

    async def _determine_update_criteria(self) -> int:
        await self._async_get_initial_last_place_name()
        await self._async_get_zone_details()
        proceed_with_update = await self._async_update_coordinates_and_distance()
        _LOGGER.debug(
            "(%s) [update_coordinates_and_distance] proceed_with_update: %s",
            self.get_attr(CONF_NAME),
            proceed_with_update,
        )
        if proceed_with_update == 1:
            proceed_with_update = await self._async_determine_if_update_needed()
            _LOGGER.debug(
                "(%s) [determine_if_update_needed] proceed_with_update: %s",
                self.get_attr(CONF_NAME),
                proceed_with_update,
            )
        return proceed_with_update

    async def _process_osm_update(self, now: datetime) -> None:
        _LOGGER.info(
            "(%s) Meets criteria, proceeding with OpenStreetMap query",
            self.get_attr(CONF_NAME),
        )
        _LOGGER.info(
            "(%s) Tracked Entity Zone: %s",
            self.get_attr(CONF_NAME),
            self.get_attr(ATTR_DEVICETRACKER_ZONE),
        )

        await self._async_reset_attributes()
        await self._async_get_map_link()
        await self._query_osm_and_finalize(now=now)

    async def _query_osm_and_finalize(self, now: datetime) -> None:
        osm_url: str = await self._build_osm_url()
        await self._get_dict_from_url(url=osm_url, name="OpenStreetMaps", dict_name=ATTR_OSM_DICT)
        if not self.is_attr_blank(ATTR_OSM_DICT):
            await self._async_parse_osm_dict()
            await self._async_finalize_last_place_name(self.get_attr_safe_str(ATTR_LAST_PLACE_NAME))
            await self._process_display_options()
            self._set_attr(ATTR_LAST_CHANGED, now.isoformat(sep=" ", timespec="seconds"))

    async def _process_display_options(self) -> None:
        display_options: list[str] = []
        if not self.is_attr_blank(ATTR_DISPLAY_OPTIONS):
            options_array: list[str] = self.get_attr_safe_str(ATTR_DISPLAY_OPTIONS).split(",")
            for option in options_array:
                display_options.extend([option.strip()])
        self._set_attr(ATTR_DISPLAY_OPTIONS_LIST, display_options)

        await self._async_get_driving_status()

        if "formatted_place" in display_options:
            await self._async_build_formatted_place()
            self._set_attr(
                ATTR_NATIVE_VALUE,
                self.get_attr(ATTR_FORMATTED_PLACE),
            )
            _LOGGER.debug(
                "(%s) New State using formatted_place: %s",
                self.get_attr(CONF_NAME),
                self.get_attr(ATTR_NATIVE_VALUE),
            )
        elif any(
            ext in (self.get_attr_safe_str(ATTR_DISPLAY_OPTIONS)) for ext in ["(", ")", "[", "]"]
        ):
            parser = AdvancedOptionsParser(self)
            await parser.build_from_advanced_options(self.get_attr_safe_str(ATTR_DISPLAY_OPTIONS))
            state = await parser.compile_state()
            self._set_attr(ATTR_NATIVE_VALUE, state)
            _LOGGER.debug(
                "(%s) New State from Advanced Display Options: %s",
                self.get_attr(CONF_NAME),
                self.get_attr(ATTR_NATIVE_VALUE),
            )
        elif not await self.async_in_zone():
            await self._async_build_state_from_display_options()
        elif (
            "zone" in display_options and not self.is_attr_blank(ATTR_DEVICETRACKER_ZONE)
        ) or self.is_attr_blank(ATTR_DEVICETRACKER_ZONE_NAME):
            self._set_attr(
                ATTR_NATIVE_VALUE,
                self.get_attr(ATTR_DEVICETRACKER_ZONE),
            )
            _LOGGER.debug(
                "(%s) New State from Tracked Entity Zone: %s",
                self.get_attr(CONF_NAME),
                self.get_attr(ATTR_NATIVE_VALUE),
            )
        elif not self.is_attr_blank(ATTR_DEVICETRACKER_ZONE_NAME):
            self._set_attr(
                ATTR_NATIVE_VALUE,
                self.get_attr(ATTR_DEVICETRACKER_ZONE_NAME),
            )
            _LOGGER.debug(
                "(%s) New State from Tracked Entity Zone Name: %s",
                self.get_attr(CONF_NAME),
                self.get_attr(ATTR_NATIVE_VALUE),
            )

    async def _build_osm_url(self) -> str:
        """Build the OpenStreetMap query URL."""
        base_url = "https://nominatim.openstreetmap.org/reverse?format=json"
        lat: str = self.get_attr_safe_str(ATTR_LATITUDE)
        lon: str = self.get_attr_safe_str(ATTR_LONGITUDE)
        lang: str = self.get_attr_safe_str(CONF_LANGUAGE)
        email: str = self.get_attr_safe_str(CONF_API_KEY)
        return f"{base_url}&lat={lat}&lon={lon}&accept-language={lang}&addressdetails=1&namedetails=1&zoom=18&limit=1&email={email}"

    async def _async_change_dot_to_stationary(self, now: datetime, changed_diff_sec: int) -> None:
        self._set_attr(ATTR_DIRECTION_OF_TRAVEL, "stationary")
        self._set_attr(ATTR_LAST_CHANGED, now.isoformat(sep=" ", timespec="seconds"))
        await self._hass.async_add_executor_job(
            write_sensor_to_json,
            self._internal_attr,
            self.get_attr(CONF_NAME),
            self.get_attr(ATTR_JSON_FILENAME),
            self._json_folder,
        )
        _LOGGER.debug(
            "(%s) Updating direction of travel to stationary (Last changed %s seconds ago)",
            self.get_attr(CONF_NAME),
            int(changed_diff_sec),
        )

    async def _async_change_show_time_to_date(self) -> None:
        if not self.is_attr_blank(ATTR_NATIVE_VALUE) and self.get_attr(CONF_SHOW_TIME):
            if self.get_attr(CONF_DATE_FORMAT) == "dd/mm":
                dateformat = "%d/%m"
            else:
                dateformat = "%m/%d"
            mmddstring: str = (
                datetime.fromisoformat(self.get_attr_safe_str(ATTR_LAST_CHANGED))
                .strftime(f"{dateformat}")
                .replace(" ", "")[:5]
            )
            self._set_attr(
                ATTR_NATIVE_VALUE,
                f"{await Places._async_clear_since_from_state(self.get_attr_safe_str(ATTR_NATIVE_VALUE))} (since {mmddstring})",
            )

            if not self.is_attr_blank(ATTR_NATIVE_VALUE):
                self._attr_native_value = self.get_attr(ATTR_NATIVE_VALUE)
            else:
                self._attr_native_value = None
            self._set_attr(ATTR_SHOW_DATE, True)
            await self._hass.async_add_executor_job(
                write_sensor_to_json,
                self._internal_attr,
                self.get_attr(CONF_NAME),
                self.get_attr(ATTR_JSON_FILENAME),
                self._json_folder,
            )
            _LOGGER.debug(
                "(%s) Updating state to show date instead of time since last change",
                self.get_attr(CONF_NAME),
            )
            _LOGGER.debug(
                "(%s) New State: %s", self.get_attr(CONF_NAME), self.get_attr(ATTR_NATIVE_VALUE)
            )

    async def _async_get_seconds_from_last_change(self, now: datetime) -> int:
        if self.is_attr_blank(ATTR_LAST_CHANGED):
            return 3600
        try:
            last_changed: datetime = datetime.fromisoformat(
                self.get_attr_safe_str(ATTR_LAST_CHANGED)
            )
        except (TypeError, ValueError) as e:
            _LOGGER.warning(
                "Error converting Last Changed date/time (%s) into datetime: %r",
                self.get_attr(ATTR_LAST_CHANGED),
                e,
            )
            return 3600
        else:
            try:
                changed_diff_sec = (now - last_changed).total_seconds()
            except TypeError:
                try:
                    changed_diff_sec = (datetime.now() - last_changed).total_seconds()
                except (TypeError, OverflowError) as e:
                    _LOGGER.warning(
                        "Error calculating the seconds between last change to now: %r", e
                    )
                    return 3600
            except OverflowError as e:
                _LOGGER.warning("Error calculating the seconds between last change to now: %r", e)
                return 3600
            return int(changed_diff_sec)

    async def _async_reset_attributes(self) -> None:
        """Reset sensor attributes."""
        for attr in RESET_ATTRIBUTE_LIST:
            self._clear_attr(attr)
        await self._async_cleanup_attributes()


class PlacesNoRecorder(Places):
    """Places Class without the HA Recorder."""

    _unrecorded_attributes = frozenset({MATCH_ALL})
