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

CONFIG_FLOW = {
    "user": SchemaFlowFormStep(
        vol.Schema(
            {
                vol.Required(CONF_NAME): selector.TextSelector(),
                vol.Required(CONF_ENTITY_UP): selector.EntitySelector(
                    selector.EntitySelectorConfig(domain=DOMAIN_ENTITIES_ALLOWED)
                ),
                vol.Required(CONF_ENTITY_DOWN): selector.EntitySelector(
                    selector.EntitySelectorConfig(domain=DOMAIN_ENTITIES_ALLOWED)
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
        )
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
    MINOR_VERSION = 3

    def async_config_entry_title(self, options: Mapping[str, Any]) -> str:
        """Return config entry title and hide the wrapped entity if
        registered."""
        # Hide the wrapped entry if registered
        registry = er.async_get(self.hass)

        for entity in [CONF_ENTITY_UP, CONF_ENTITY_DOWN, CONF_ENTITY_STOP]:
            entity_entry = registry.async_get(options[entity])
            if entity_entry is not None and not entity_entry.hidden:
                registry.async_update_entity(
                    options[entity], hidden_by=er.RegistryEntryHider.INTEGRATION
                )

        return options[CONF_NAME]
