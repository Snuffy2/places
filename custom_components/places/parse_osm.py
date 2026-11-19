"""Map aioplaces results to Home Assistant attributes and place naming rules."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from aioplaces import parse_place
from homeassistant.const import ATTR_ATTRIBUTION, CONF_NAME

from .const import (
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
    PLACE_NAME_DUPLICATE_LIST,
)

if TYPE_CHECKING:
    from .coordinator import PlacesUpdateCoordinator

_LOGGER = logging.getLogger(__name__)


class OSMParser:
    """Translate Nominatim/OpenStreetMap response fields into coordinator attributes."""

    def __init__(self, coordinator: PlacesUpdateCoordinator) -> None:
        """Initialize the parser for a Places coordinator.

        Args:
            coordinator (PlacesUpdateCoordinator):
                Places coordinator whose internal attributes receive parsed OSM
                values.
        """
        self.coordinator = coordinator

    async def parse_osm_dict(self) -> None:
        """Map aioplaces fields into sensor attributes and apply HA naming rules."""
        osm_dict = self.coordinator.get_attr_safe_dict(ATTR_OSM_DICT)
        if not osm_dict:
            return
        place = parse_place(osm_dict, language=self.coordinator.get_attr_safe_str(CONF_LANGUAGE))
        attributes = {
            ATTR_ATTRIBUTION: place.attribution,
            ATTR_OSM_ID: place.osm_id,
            ATTR_OSM_TYPE: place.osm_type,
            ATTR_PLACE_TYPE: place.place_type,
            ATTR_PLACE_CATEGORY: place.place_category,
            ATTR_PLACE_NAME: place.place_name,
            ATTR_STREET_NUMBER: place.street_number,
            ATTR_STREET: place.street,
            ATTR_CITY: place.city,
            ATTR_CITY_CLEAN: place.city_clean,
            ATTR_POSTAL_TOWN: place.postal_town,
            ATTR_PLACE_NEIGHBOURHOOD: place.neighbourhood,
            ATTR_REGION: place.region,
            ATTR_STATE_ABBR: place.state_abbr,
            ATTR_COUNTY: place.county,
            ATTR_COUNTRY: place.country,
            ATTR_COUNTRY_CODE: place.country_code,
            ATTR_POSTAL_CODE: place.postal_code,
            ATTR_FORMATTED_ADDRESS: place.formatted_address,
            ATTR_ROUTE_NUMBER: place.route_number,
        }
        for attribute, value in attributes.items():
            if value is not None:
                self.coordinator.set_attr(attribute, value)
        await self.set_place_name_no_dupe()

    async def set_place_name_no_dupe(self) -> None:
        """Expose place name only when it is not already shown by another field."""
        dupe_attributes_check: list[str] = []
        dupe_attributes_check.extend(
            [
                self.coordinator.get_attr_safe_str(attr)
                for attr in PLACE_NAME_DUPLICATE_LIST
                if not self.coordinator.is_attr_blank(attr)
            ]
        )
        if (
            not self.coordinator.is_attr_blank(ATTR_PLACE_NAME)
            and self.coordinator.get_attr_safe_str(ATTR_PLACE_NAME) not in dupe_attributes_check
        ):
            self.coordinator.set_attr(
                ATTR_PLACE_NAME_NO_DUPE,
                self.coordinator.get_attr(ATTR_PLACE_NAME),
            )

    async def finalize_last_place_name(self, prev_last_place_name: str) -> None:
        """Preserve the useful previous place name after a successful parse.

        Args:
            prev_last_place_name (str):
                Last known place name captured before this
                update began.
        """
        if self.coordinator.get_attr(ATTR_INITIAL_UPDATE):
            self.coordinator.set_attr(ATTR_LAST_PLACE_NAME, prev_last_place_name)
            _LOGGER.debug(
                "(%s) Running initial update after load, using prior last_place_name",
                self.coordinator.get_attr(CONF_NAME),
            )
        elif self.coordinator.get_attr(ATTR_LAST_PLACE_NAME) == self.coordinator.get_attr(
            ATTR_PLACE_NAME
        ) or self.coordinator.get_attr(ATTR_LAST_PLACE_NAME) == self.coordinator.get_attr(
            ATTR_DEVICETRACKER_ZONE_NAME
        ):
            # If current place name/zone are the same as previous, keep older last_place_name
            self.coordinator.set_attr(ATTR_LAST_PLACE_NAME, prev_last_place_name)
            _LOGGER.debug(
                "(%s) Initial last_place_name is same as new: place_name=%s or "
                "devicetracker_zone_name=%s, "
                "keeping previous last_place_name",
                self.coordinator.get_attr(CONF_NAME),
                self.coordinator.get_attr(ATTR_PLACE_NAME),
                self.coordinator.get_attr(ATTR_DEVICETRACKER_ZONE_NAME),
            )
        else:
            _LOGGER.debug(
                "(%s) Keeping initial last_place_name", self.coordinator.get_attr(CONF_NAME)
            )
        _LOGGER.info(
            "(%s) last_place_name: %s",
            self.coordinator.get_attr(CONF_NAME),
            self.coordinator.get_attr(ATTR_LAST_PLACE_NAME),
        )
