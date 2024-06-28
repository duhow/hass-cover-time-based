"""Component to wrap switch entities in entities of other domains."""
from __future__ import annotations

import logging

import voluptuous as vol
from homeassistant.components.cover import DOMAIN as COVER_DOMAIN
from homeassistant.components.homeassistant import exposed_entities
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_ENTITY_ID
from homeassistant.core import callback
from homeassistant.core import Event
from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.event import async_track_entity_registry_updated_event

from .const import CONF_ENTITY_DOWN
from .const import CONF_ENTITY_UP
from .const import CONF_INVERT
from .const import CONF_TARGET_DEVICE_CLASS

_LOGGER = logging.getLogger(__name__)


@callback
def async_add_to_device(
    hass: HomeAssistant, entry: ConfigEntry, entity_id: str
) -> str | None:
    """Add our config entry to the tracked entity's device."""
    registry = er.async_get(hass)
    device_registry = dr.async_get(hass)
    device_id = None

    if (
        not (wrapped_switch := registry.async_get(entity_id))
        or not (device_id := wrapped_switch.device_id)
        or not (device_registry.async_get(device_id))
    ):
        return device_id

    device_registry.async_update_device(device_id, add_config_entry_id=entry.entry_id)

    return device_id


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Check light-swich up and down exist."""
    registry = er.async_get(hass)
    device_registry = dr.async_get(hass)
    try:
        for entity in [CONF_ENTITY_UP, CONF_ENTITY_DOWN]:
            entity_id = er.async_validate_entity_id(registry, entry.options[entity])
    except vol.Invalid:
        # The entity is identified by an unknown entity registry ID
        _LOGGER.error(
            "Failed to setup cover_time_based for unknown entity %s",
            entry.options[entity],
        )
        return False

    async def async_registry_updated(
        event: Event[er.EventEntityRegistryUpdatedData],
    ) -> None:
        """Handle entity registry update."""
        data = event.data
        if data["action"] == "remove":
            await hass.config_entries.async_remove(entry.entry_id)

        if data["action"] != "update":
            return

        if "entity_id" in data["changes"]:
            # Entity_id changed, reload the config entry
            await hass.config_entries.async_reload(entry.entry_id)

        if device_id and "device_id" in data["changes"]:
            # If the tracked switch is no longer in the device, remove our config entry
            # from the device
            if (
                not (entity_entry := registry.async_get(data[CONF_ENTITY_ID]))
                or not device_registry.async_get(device_id)
                or entity_entry.device_id == device_id
            ):
                # No need to do any cleanup
                return

            device_registry.async_update_device(
                device_id, remove_config_entry_id=entry.entry_id
            )

    entry.async_on_unload(
        async_track_entity_registry_updated_event(
            hass, entity_id, async_registry_updated
        )
    )
    entry.async_on_unload(entry.add_update_listener(config_entry_update_listener))

    device_id = async_add_to_device(hass, entry, entity_id)

    await hass.config_entries.async_forward_entry_setups(entry, (COVER_DOMAIN,))
    return True


async def config_entry_update_listener(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Update listener, called when the config entry options are changed."""
    await hass.config_entries.async_reload(entry.entry_id)


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    return await hass.config_entries.async_unload_platforms(entry, (COVER_DOMAIN,))


async def async_remove_entry(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Unload a config entry.

    This will unhide the wrapped entity and restore assistant expose
    settings.
    """
    registry = er.async_get(hass)
    try:
        switch_entity_id = er.async_validate_entity_id(
            registry, entry.options[CONF_ENTITY_ID]
        )
    except vol.Invalid:
        # The source entity has been removed from the entity registry
        return

    if not (switch_entity_entry := registry.async_get(switch_entity_id)):
        return

    # Unhide the wrapped entity
    if switch_entity_entry.hidden_by == er.RegistryEntryHider.INTEGRATION:
        registry.async_update_entity(switch_entity_id, hidden_by=None)

    switch_as_x_entries = er.async_entries_for_config_entry(registry, entry.entry_id)
    if not switch_as_x_entries:
        return

    switch_as_x_entry = switch_as_x_entries[0]

    # Restore assistant expose settings
    expose_settings = exposed_entities.async_get_entity_settings(
        hass, switch_as_x_entry.entity_id
    )
    for assistant, settings in expose_settings.items():
        if (should_expose := settings.get("should_expose")) is None:
            continue
        exposed_entities.async_expose_entity(
            hass, assistant, switch_entity_id, should_expose
        )
