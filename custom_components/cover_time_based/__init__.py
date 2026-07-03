"""Component to wrap switch entities in entities of other domains."""

from __future__ import annotations

import logging

import voluptuous as vol
from homeassistant.components.cover import DOMAIN as COVER_DOMAIN
from homeassistant.components.homeassistant import exposed_entities
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_ENTITY_ID
from homeassistant.core import Event
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.device import async_entity_id_to_device_id
from homeassistant.helpers.event import async_track_entity_registry_updated_event
from homeassistant.helpers.helper_integration import (
    async_remove_helper_config_entry_from_source_device,
)

from .const import CONF_ENTITY_DOWN
from .const import CONF_ENTITY_UP

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Check light-swich up and down exist."""
    registry = er.async_get(hass)
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

    entry.async_on_unload(
        async_track_entity_registry_updated_event(
            hass, entity_id, async_registry_updated
        )
    )
    entry.async_on_unload(entry.add_update_listener(config_entry_update_listener))

    await hass.config_entries.async_forward_entry_setups(entry, (COVER_DOMAIN,))
    return True


async def config_entry_update_listener(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Update listener, called when the config entry options are changed."""
    await hass.config_entries.async_reload(entry.entry_id)


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    return await hass.config_entries.async_unload_platforms(entry, (COVER_DOMAIN,))


async def async_migrate_entry(hass: HomeAssistant, config_entry: ConfigEntry) -> bool:
    """Migrate old entry."""
    _LOGGER.debug(
        "Migrating from version %s.%s",
        config_entry.version,
        config_entry.minor_version,
    )

    if config_entry.minor_version < 4:
        # Remove the helper config entry from source devices (deprecated old pattern)
        for entity_conf in [CONF_ENTITY_UP, CONF_ENTITY_DOWN]:
            try:
                source_device_id = async_entity_id_to_device_id(
                    hass, config_entry.options.get(entity_conf, "")
                )
            except vol.Invalid:
                source_device_id = None

            if source_device_id:
                async_remove_helper_config_entry_from_source_device(
                    hass,
                    helper_config_entry_id=config_entry.entry_id,
                    source_device_id=source_device_id,
                )

        hass.config_entries.async_update_entry(config_entry, minor_version=4)

    _LOGGER.debug(
        "Migration to version %s.%s successful",
        config_entry.version,
        config_entry.minor_version,
    )
    return True


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
