"""Config flow for Cover Time-based integration."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

import voluptuous as vol
from homeassistant.const import CONF_NAME
from homeassistant.const import Platform
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers import selector
from homeassistant.helpers.schema_config_entry_flow import SchemaConfigFlowHandler
from homeassistant.helpers.schema_config_entry_flow import SchemaFlowFormStep

from .const import CONF_ENTITY_DOWN
from .const import CONF_ENTITY_STOP
from .const import CONF_ENTITY_UP
from .const import CONF_TIME_CLOSE
from .const import CONF_TIME_OPEN
from .const import DOMAIN

DOMAIN_ENTITIES_ALLOWED = [Platform.SWITCH, Platform.LIGHT, Platform.BUTTON, "script"]
COVER_ENTITIES_ALLOWED = [Platform.COVER]


def _validate_cover_input(user_input: dict) -> dict:
    """Validate that entity configuration is consistent.

    Accepts either:
    - Two switch/light entities for up and down (with optional stop)
    - A single cover entity for up (down is auto-filled with the same entity)
    """
    entity_up = user_input.get(CONF_ENTITY_UP, "")
    entity_down = user_input.get(CONF_ENTITY_DOWN) or ""
    entity_stop = user_input.get(CONF_ENTITY_STOP) or ""

    cover_prefix = f"{Platform.COVER}."
    up_is_cover = entity_up.startswith(cover_prefix)
    down_is_cover = entity_down.startswith(cover_prefix) if entity_down else False

    if up_is_cover:
        # Cover mode: down must be the same cover entity or omitted
        if entity_down and not down_is_cover:
            raise vol.Invalid("mixed_entity_types")
        if entity_down and entity_up != entity_down:
            raise vol.Invalid("different_cover_entities")
        if entity_stop:
            raise vol.Invalid("stop_not_supported_for_cover")
        # Auto-fill down with up entity so options always contain both
        user_input[CONF_ENTITY_DOWN] = entity_up
    elif down_is_cover:
        # down is a cover but up is not — mixed types
        raise vol.Invalid("mixed_entity_types")
    else:
        # Switch mode: both up and down must be provided
        if not entity_down:
            raise vol.Invalid("entity_down_required")

    return user_input


CONFIG_FLOW = {
    "user": SchemaFlowFormStep(
        vol.Schema(
            {
                vol.Required(CONF_NAME): selector.TextSelector(),
                vol.Required(CONF_ENTITY_UP): selector.EntitySelector(
                    selector.EntitySelectorConfig(
                        domain=DOMAIN_ENTITIES_ALLOWED + COVER_ENTITIES_ALLOWED
                    )
                ),
                vol.Optional(CONF_ENTITY_DOWN): selector.EntitySelector(
                    selector.EntitySelectorConfig(
                        domain=DOMAIN_ENTITIES_ALLOWED + COVER_ENTITIES_ALLOWED
                    )
                ),
                vol.Optional(CONF_ENTITY_STOP): selector.EntitySelector(
                    selector.EntitySelectorConfig(domain=DOMAIN_ENTITIES_ALLOWED)
                ),
                vol.Required(CONF_TIME_OPEN, default=25): selector.NumberSelector(
                    selector.NumberSelectorConfig(
                        mode=selector.NumberSelectorMode.BOX,
                        min=2,
                        max=120,
                        step="any",
                        unit_of_measurement="sec",
                    )
                ),
                vol.Optional(CONF_TIME_CLOSE): selector.NumberSelector(
                    selector.NumberSelectorConfig(
                        mode=selector.NumberSelectorMode.BOX,
                        max=120,
                        step="any",
                        unit_of_measurement="sec",
                    )
                ),
            }
        ),
        validate_user_input=_validate_cover_input,
    )
}

OPTIONS_FLOW = {
    "init": SchemaFlowFormStep(
        vol.Schema(
            {
                vol.Required(CONF_TIME_OPEN): selector.NumberSelector(
                    selector.NumberSelectorConfig(
                        mode=selector.NumberSelectorMode.BOX,
                        min=2,
                        max=120,
                        step="any",
                        unit_of_measurement="sec",
                    )
                ),
                vol.Optional(CONF_TIME_CLOSE): selector.NumberSelector(
                    selector.NumberSelectorConfig(
                        mode=selector.NumberSelectorMode.BOX,
                        max=120,
                        step="any",
                        unit_of_measurement="sec",
                    )
                ),
            }
        )
    ),
}


class CoverTimeBasedConfigFlowHandler(SchemaConfigFlowHandler, domain=DOMAIN):
    """Handle a config flow for Cover Time-based."""

    config_flow = CONFIG_FLOW
    options_flow = OPTIONS_FLOW

    VERSION = 1
    MINOR_VERSION = 5

    def async_config_entry_title(self, options: Mapping[str, Any]) -> str:
        """Return config entry title and hide the wrapped entity if
        registered."""
        # Hide the wrapped entry if registered
        registry = er.async_get(self.hass)

        for entity in [CONF_ENTITY_UP, CONF_ENTITY_DOWN, CONF_ENTITY_STOP]:
            if not options.get(entity):  # stop is optional
                continue
            entity_entry = registry.async_get(options[entity])
            if entity_entry is not None and not entity_entry.hidden:
                registry.async_update_entity(
                    options[entity], hidden_by=er.RegistryEntryHider.INTEGRATION
                )

        return options[CONF_NAME]
