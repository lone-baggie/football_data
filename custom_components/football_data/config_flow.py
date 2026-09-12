"""Config flow and Options flow for Football Data integration."""
import logging
import aiohttp
import voluptuous as vol

from homeassistant import config_entries
from homeassistant.core import callback
from homeassistant.helpers.selector import (
    SelectSelector,
    SelectSelectorConfig,
    SelectSelectorMode,
)

from .const import (
    DOMAIN,
    CONF_API_KEY,
    CONF_LEAGUES,
    API_BASE_URL,
    AVAILABLE_LEAGUES,
    DEFAULT_LEAGUES,
)

_LOGGER = logging.getLogger(__name__)


class FootballDataConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle initial setup config flow for Football Data."""

    VERSION = 1

    async def async_step_user(self, user_input=None):
        """Handle initial step."""
        errors = {}

        if user_input is not None:
            api_key = user_input[CONF_API_KEY]
            headers = {"X-Auth-Token": api_key}
            
            # Simple API connection test using a standard public endpoint
            url = f"{API_BASE_URL}/competitions/PL"

            try:
                async with aiohttp.ClientSession() as session:
                    async with session.get(url, headers=headers) as response:
                        if response.status == 200:
                            return self.async_create_entry(
                                title="Football Data",
                                data=user_input,
                            )
                        elif response.status == 403:
                            errors["base"] = "invalid_auth"
                        else:
                            errors["base"] = "cannot_connect"
            except Exception:
                errors["base"] = "cannot_connect"

        # Build form schema
        schema = vol.Schema(
            {
                vol.Required(CONF_API_KEY): str,
                vol.Optional(CONF_LEAGUES, default=DEFAULT_LEAGUES): SelectSelector(
                    SelectSelectorConfig(
                        options=[{"value": k, "label": v} for k, v in AVAILABLE_LEAGUES.items()],
                        multiple=True,
                        mode=SelectSelectorMode.DROPDOWN,
                    )
                ),
            }
        )

        return self.async_show_form(
            step_id="user", data_schema=schema, errors=errors
        )

    @staticmethod
    @callback
    def async_get_options_flow(config_entry):
        """Get the options flow for this handler."""
        return FootballDataOptionsFlowHandler(config_entry)


class FootballDataOptionsFlowHandler(config_entries.OptionsFlow):
    """Handle dynamic configuration options (League selections)."""

    def __init__(self, config_entry):
        """Initialize options flow."""
        self.config_entry = config_entry

    async def async_step_init(self, user_input=None):
        """Manage the options."""
        if user_input is not None:
            return self.async_create_entry(title="", data=user_input)

        current_leagues = self.config_entry.options.get(
            CONF_LEAGUES,
            self.config_entry.data.get(CONF_LEAGUES, DEFAULT_LEAGUES),
        )

        schema = vol.Schema(
            {
                vol.Optional(CONF_LEAGUES, default=current_leagues): SelectSelector(
                    SelectSelectorConfig(
                        options=[{"value": k, "label": v} for k, v in AVAILABLE_LEAGUES.items()],
                        multiple=True,
                        mode=SelectSelectorMode.DROPDOWN,
                    )
                ),
            }
        )

        return self.async_show_form(step_id="init", data_schema=schema)
