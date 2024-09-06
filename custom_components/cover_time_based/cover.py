"""Cover support for switch entities."""
from __future__ import annotations

import logging
from datetime import timedelta

from homeassistant.components.cover import ATTR_CURRENT_POSITION
from homeassistant.components.cover import ATTR_POSITION
from homeassistant.components.cover import CoverEntity
from homeassistant.components.cover import DOMAIN as COVER_DOMAIN
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import ATTR_ENTITY_ID
from homeassistant.const import EVENT_STATE_CHANGED
from homeassistant.const import Platform
from homeassistant.const import SERVICE_CLOSE_COVER
from homeassistant.const import SERVICE_OPEN_COVER
from homeassistant.const import SERVICE_STOP_COVER
from homeassistant.const import STATE_OFF
from homeassistant.const import STATE_ON
from homeassistant.const import STATE_UNAVAILABLE
from homeassistant.const import STATE_UNKNOWN
from homeassistant.core import callback
from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.device_registry import DeviceEntry
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.event import async_track_time_interval
from homeassistant.helpers.restore_state import RestoreEntity
from homeassistant.util import slugify

from .const import CONF_ENTITY_DOWN
from .const import CONF_ENTITY_STOP
from .const import CONF_ENTITY_UP
from .const import CONF_TIME_CLOSE
from .const import CONF_TIME_OPEN
from .travelcalculator import TravelCalculator
from .travelcalculator import TravelStatus

_LOGGER = logging.getLogger(__name__)


async def async_get_device_entry_from_entity_id(
    hass: HomeAssistant, entity_id: str
) -> DeviceEntry:
    """Get DeviceEntry from an entity ID."""
    ent_reg = er.async_get(hass)
    entity_entry = ent_reg.async_get(entity_id)

    if (
        entity_entry is None
        or entity_entry.device_id is None
        or entity_entry.platform != DOMAIN
    ):
        return False

    device_id = entity_entry.device_id

    device_reg = dr.async_get(hass)
    device = device_reg.async_get(device_id)

    return device


def generate_unique_id(name: str) -> str:
    entity = f"{COVER_DOMAIN}.time_based_{name}".lower()
    unique_id = slugify(entity)
    return unique_id


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    """Initialize Cover Switch config entry."""
    registry = er.async_get(hass)

    entity_up = er.async_validate_entity_id(
        registry, config_entry.options[CONF_ENTITY_UP]
    )
    entity_down = er.async_validate_entity_id(
        registry, config_entry.options[CONF_ENTITY_DOWN]
    )
    entity_stop = None
    if config_entry.options.get(CONF_ENTITY_STOP):
        entity_stop = er.async_validate_entity_id(
            registry, config_entry.options[CONF_ENTITY_STOP]
        )

    async_add_entities(
        [
            CoverTimeBased(
                generate_unique_id(config_entry.title),
                config_entry.title,
                config_entry.options.get(CONF_TIME_CLOSE),
                config_entry.options[CONF_TIME_OPEN],
                entity_up,
                entity_down,
                entity_stop,
            )
        ]
    )


class CoverTimeBased(CoverEntity, RestoreEntity):
    def __init__(
        self,
        unique_id,
        name,
        travel_time_down,
        travel_time_up,
        open_switch_entity_id,
        close_switch_entity_id,
        stop_switch_entity_id=None,
    ):
        """Initialize the cover."""
        if not travel_time_down:
            travel_time_down = travel_time_up
        self._travel_time_down = travel_time_down
        self._travel_time_up = travel_time_up
        self._open_switch_state = STATE_OFF
        self._open_switch_entity_id = open_switch_entity_id
        self._close_switch_state = STATE_OFF
        self._close_switch_entity_id = close_switch_entity_id
        self._stop_switch_state = STATE_OFF
        self._stop_switch_entity_id = stop_switch_entity_id
        self._name = name
        self._attr_unique_id = unique_id

        self._unsubscribe_auto_updater = None

        self.tc = TravelCalculator(self._travel_time_down, self._travel_time_up)

    async def async_added_to_hass(self):
        """Only cover's position matters."""
        """The rest is calculated from this attribute."""
        # Listen to all change events, look for switch/light press
        self.hass.bus.async_listen(EVENT_STATE_CHANGED, self._handle_state_changed)
        old_state = await self.async_get_last_state()
        _LOGGER.debug("async_added_to_hass :: oldState %s", old_state)
        if (
            old_state is not None
            and self.tc is not None
            and old_state.attributes.get(ATTR_CURRENT_POSITION) is not None
        ):
            self.tc.set_position(int(old_state.attributes.get(ATTR_CURRENT_POSITION)))

    async def _handle_state_changed(self, event):
        """Process changes in Home Assistant, look if switch is opened
        manually."""
        # If switch/light is not the target, skip
        if event.data.get(ATTR_ENTITY_ID) not in [
            self._close_switch_entity_id,
            self._open_switch_entity_id,
            self._stop_switch_entity_id,
        ]:
            return

        if event.data.get("new_state") is None:
            return

        if event.data.get("old_state") is None:
            return

        if event.data.get("new_state").state == event.data.get("old_state").state:
            return

        # avoid loop
        if event.data.get(ATTR_ENTITY_ID).startswith("script."):
            return

        if event.data.get(ATTR_ENTITY_ID).startswith(f"{Platform.BUTTON}."):
            return

        # Target switch/light
        if event.data.get(ATTR_ENTITY_ID) == self._close_switch_entity_id:
            if self._close_switch_state == event.data.get("new_state").state:
                return
            self._close_switch_state = event.data.get("new_state").state
        elif event.data.get(ATTR_ENTITY_ID) == self._open_switch_entity_id:
            if self._open_switch_state == event.data.get("new_state").state:
                return
            self._open_switch_state = event.data.get("new_state").state
        elif (
            self.has_stop_entity
            and event.data.get(ATTR_ENTITY_ID) == self.stop_switch_entity_id
        ):
            if self._stop_switch_state == event.data.get("new_state").state:
                return
            self._stop_switch_state = event.data.get("new_state").state

        # Set unavailable if any of the switches becomes unavailable
        self._attr_available = not any(
            [
                self._open_switch_state == STATE_UNAVAILABLE,
                self._close_switch_state == STATE_UNAVAILABLE,
            ]
        )

        # Handle new status
        if (
            self._open_switch_state == STATE_OFF
            and self._close_switch_state == STATE_OFF
        ):
            _LOGGER.debug(f"{self._name}: open/close: off/off, stopping")
            return await self.async_stop_cover()
        elif (
            self._open_switch_state == STATE_ON and self._close_switch_state == STATE_ON
        ):
            _LOGGER.debug(f"{self._name}: open/close: on/on, turning off both switches")
            return await self.async_stop_cover()
        elif (
            self._open_switch_state == STATE_ON
            and self._close_switch_state == STATE_OFF
        ):
            await self.async_open_cover(handle_command=False)
        elif (
            self._open_switch_state == STATE_OFF
            and self._close_switch_state == STATE_ON
        ):
            await self.async_close_cover(handle_command=False)

    def _handle_my_button(self):
        """Handle the MY button press."""
        if self.tc.is_traveling():
            _LOGGER.debug("_handle_my_button :: button stops cover")
            self.tc.stop()
            self.stop_auto_updater()

    @property
    def name(self):
        """Return the name of the cover."""
        return self._name

    @property
    def device_state_attributes(self):
        """Return the device state attributes."""
        attr = {}
        if self._travel_time_down is not None:
            attr[CONF_TIME_CLOSE] = self._travel_time_down
        if self._travel_time_up is not None:
            attr[CONF_TIME_OPEN] = self._travel_time_up
        return attr

    @property
    def current_cover_position(self):
        """Return the current position of the cover."""
        return self.tc.current_position()

    @property
    def is_opening(self):
        """Return if the cover is opening or not."""
        return (
            self.tc.is_traveling()
            and self.tc.travel_direction == TravelStatus.DIRECTION_DOWN
        )

    @property
    def is_closing(self):
        """Return if the cover is closing or not."""
        return (
            self.tc.is_traveling()
            and self.tc.travel_direction == TravelStatus.DIRECTION_UP
        )

    @property
    def is_closed(self):
        """Return if the cover is closed."""
        return self.current_cover_position is None or self.current_cover_position <= 10

    @property
    def assumed_state(self):
        """Return True because covers can be stopped midway."""
        return True

    @property
    def has_stop_entity(self) -> bool:
        """Check if there is a third input used to stop the cover."""
        return self._stop_switch_entity_id is not None

    async def check_availability(self) -> None:
        """Check if any of the entities is unavailable and update status."""
        for entity in [self._close_switch_entity_id, self._open_switch_entity_id]:
            state = self.hass.states.get(entity)
            if state.state in [STATE_UNAVAILABLE, STATE_UNKNOWN]:
                self._attr_available = False
                return
        self._attr_available = True

    async def async_set_cover_position(self, **kwargs):
        """Move the cover to a specific position."""
        if ATTR_POSITION in kwargs:
            await self.check_availability()
            if not self.available:
                return
            position = kwargs[ATTR_POSITION]
            _LOGGER.debug("async_set_cover_position: %d", position)
            await self.set_position(position)

    async def async_close_cover(self, **kwargs):
        """Turn the device close."""
        _LOGGER.debug("async_close_cover")
        await self.check_availability()
        if not self.available:
            return
        if kwargs.get("handle_command") is not False:
            await self._async_handle_command(SERVICE_CLOSE_COVER)
        self.tc.start_travel_up()
        self.start_auto_updater()

    async def async_open_cover(self, **kwargs):
        """Turn the device open."""
        _LOGGER.debug("async_open_cover")
        await self.check_availability()
        if not self.available:
            return
        if kwargs.get("handle_command") is not False:
            await self._async_handle_command(SERVICE_OPEN_COVER)
        self.tc.start_travel_down()
        self.start_auto_updater()

    async def async_stop_cover(self, **kwargs):
        """Turn the device stop."""
        _LOGGER.debug("async_stop_cover")
        await self.check_availability()
        if not self.available:
            return
        await self._async_handle_command(SERVICE_STOP_COVER)
        self._handle_my_button()

    async def set_position(self, position):
        _LOGGER.debug("set_position")
        """Move cover to a designated position."""
        current_position = self.tc.current_position()
        _LOGGER.debug(
            "set_position :: current_position: %d, new_position: %d",
            current_position,
            position,
        )
        command = None
        if position < current_position:
            command = SERVICE_CLOSE_COVER
        elif position > current_position:
            command = SERVICE_OPEN_COVER
        if command is not None:
            await self._async_handle_command(command)
            self.start_auto_updater()
            self.tc.start_travel(position)
            _LOGGER.debug("set_position :: command %s", command)
        return

    def start_auto_updater(self):
        """Start the autoupdater to update HASS while cover is moving."""
        _LOGGER.debug("start_auto_updater")
        if self._unsubscribe_auto_updater is None:
            _LOGGER.debug("init _unsubscribe_auto_updater")
            interval = timedelta(seconds=0.1)
            self._unsubscribe_auto_updater = async_track_time_interval(
                self.hass, self.auto_updater_hook, interval
            )

    @callback
    def auto_updater_hook(self, now):
        """Call for the autoupdater."""
        _LOGGER.debug("auto_updater_hook")
        self.async_schedule_update_ha_state()
        if self.position_reached():
            _LOGGER.debug("auto_updater_hook :: position_reached")
            self.stop_auto_updater()
        self.hass.async_create_task(self.auto_stop_if_necessary())

    def stop_auto_updater(self):
        """Stop the autoupdater."""
        _LOGGER.debug("stop_auto_updater")
        if self._unsubscribe_auto_updater is not None:
            self._unsubscribe_auto_updater()
            self._unsubscribe_auto_updater = None

    def position_reached(self):
        """Return if cover has reached its final position."""
        return self.tc.position_reached()

    async def auto_stop_if_necessary(self):
        """Do auto stop if necessary."""
        if self.position_reached():
            _LOGGER.debug("auto_stop_if_necessary :: calling stop command")
            await self._async_handle_command(SERVICE_STOP_COVER)
            self.tc.stop()

    async def set_entity(self, state: str, entity_id, wait=False):
        if state not in [STATE_ON, STATE_OFF]:
            raise Exception(f"calling set_entity with wrong state {state}")

        domain = "homeassistant"
        action = f"turn_{state}"

        if entity_id.startswith(Platform.BUTTON):
            domain = "input_button"
            action = "press"
        elif entity_id.startswith("script"):
            domain = "script"

        return await self.hass.services.async_call(
            domain, action, {"entity_id": entity_id}, wait
        )

    async def _async_handle_command(self, command, *args):
        if command == SERVICE_CLOSE_COVER:
            self._state = False
            if self.has_stop_entity:
                await self.set_entity(STATE_OFF, self._stop_switch_entity_id)
            await self.set_entity(STATE_OFF, self._open_switch_entity_id)
            await self.set_entity(STATE_ON, self._close_switch_entity_id, True)

        elif command == SERVICE_OPEN_COVER:
            self._state = True
            if self.has_stop_entity:
                await self.set_entity(STATE_OFF, self._stop_switch_entity_id)
            await self.set_entity(STATE_OFF, self._close_switch_entity_id)
            await self.set_entity(STATE_ON, self._open_switch_entity_id, True)

        elif command == SERVICE_STOP_COVER:
            self._state = True
            await self.set_entity(STATE_OFF, self._close_switch_entity_id)
            await self.set_entity(STATE_OFF, self._open_switch_entity_id)
            if self.has_stop_entity:
                await self.set_entity(STATE_ON, self._stop_switch_entity_id, True)

        _LOGGER.debug("_async_handle_command :: %s", command)

        # Update state of entity
        self.async_write_ha_state()
