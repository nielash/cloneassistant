"""Config flow for Rclone integration."""

from __future__ import annotations

import json
import logging
from typing import Any

import voluptuous as vol

from homeassistant.config_entries import (
    ConfigEntry,
    ConfigFlow,
    ConfigFlowResult,
    OptionsFlow,
)
from homeassistant.const import (
    CONF_COMMAND,
    CONF_FRIENDLY_NAME,
    CONF_HOST,
    CONF_PASSWORD,
    CONF_SCAN_INTERVAL,
    CONF_USERNAME,
)
from homeassistant.core import HomeAssistant, callback
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.selector import (
    SelectOptionDict,
    SelectSelector,
    SelectSelectorConfig,
    SelectSelectorMode,
)

from .api import API, APIAuthError, APIConnectionError
from .const import (
    CHECK,
    COMMAND_ARGS,
    DEFAULT_SCAN_INTERVAL,
    DOMAIN,
    MIN_SCAN_INTERVAL,
    RCLONE_COMMANDS,
)

_LOGGER = logging.getLogger(__name__)

STEP_USER_DATA_SCHEMA = vol.Schema(
    {
        vol.Required(
            CONF_FRIENDLY_NAME, description={"suggested_value": "Bisync"}
        ): str,
        vol.Required(
            CONF_HOST, description={"suggested_value": "192.168.XX.XX:5572"}
        ): str,
        vol.Required(CONF_USERNAME, description={"suggested_value": "test"}): str,
        vol.Required(CONF_PASSWORD, description={"suggested_value": "1234"}): str,
        vol.Required(
            CONF_SCAN_INTERVAL,
            default=DEFAULT_SCAN_INTERVAL,
        ): (vol.All(vol.Coerce(int), vol.Clamp(min=MIN_SCAN_INTERVAL))),
        vol.Required(CONF_COMMAND, default=CHECK): SelectSelector(
            SelectSelectorConfig(
                options=[
                    SelectOptionDict(value=k, label=v)
                    for k, v in RCLONE_COMMANDS.items()
                ],
                translation_key="rclone commands",
                mode=SelectSelectorMode.DROPDOWN,
            )
        ),
        vol.Required(
            COMMAND_ARGS,
            default="",
            description={
                "json blob - see https://rclone.org/rc/#specifying-remotes-to-work-on"
            },
        ): str,
    }
)


async def validate_input(hass: HomeAssistant, data: dict[str, Any]) -> dict[str, Any]:
    """Validate the user input allows us to connect.

    Data has the keys from STEP_USER_DATA_SCHEMA with values provided by the user.
    """

    # If the PyPI package is not built with async, pass the methods
    # to the executor:
    # await hass.async_add_executor_job(
    #     the_validate_func, data[CONF_USERNAME], data[CONF_PASSWORD]
    # )

    api = API(
        data[CONF_HOST],
        data[CONF_USERNAME],
        data[CONF_PASSWORD],
        data[CONF_FRIENDLY_NAME],
    )
    try:
        await hass.async_add_executor_job(api.connect)
    except APIAuthError as err:
        raise InvalidAuth from err
    except APIConnectionError as err:
        raise CannotConnect from err

    if parse_json(data[COMMAND_ARGS]) is None:
        raise InvalidAuth("Invalid JSON for command args")
    return {"title": f"{data[CONF_FRIENDLY_NAME]}"}


class RcloneConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle a config flow for Rclone Integration."""

    VERSION = 1
    _input_data: dict[str, Any]

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: ConfigEntry) -> OptionsFlow:
        """Get the options flow for this handler."""
        return RcloneOptionsFlowHandler(config_entry)

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Handle the initial step."""
        # Called when you initiate adding an integration via the UI
        errors: dict[str, str] = {}

        if user_input is not None:
            # The form has been filled in and submitted, so process the data provided.
            try:
                # Validate that the setup data is valid and if not handle errors.
                # The errors["base"] values match the values in the strings.json and translation files.
                info = await validate_input(self.hass, user_input)
            except CannotConnect:
                errors["base"] = "cannot_connect"
            except InvalidAuth:
                errors["base"] = "invalid_auth"
            except Exception:  # pylint: disable=broad-except
                _LOGGER.exception("Unexpected exception")
                errors["base"] = "unknown"

            if "base" not in errors:
                # Validation was successful, so create a unique id for this instance of the integration
                # and create the config entry.
                await self.async_set_unique_id(info.get("title"))
                self._abort_if_unique_id_configured()
                return self.async_create_entry(title=info["title"], data=user_input)

        # Show initial form.
        return self.async_show_form(
            step_id="user", data_schema=STEP_USER_DATA_SCHEMA, errors=errors
        )

    async def async_step_reconfigure(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Add reconfigure step to allow to reconfigure a config entry."""
        # This method displays a reconfigure option in the integration and is
        # different to options.
        errors: dict[str, str] = {}
        config_entry = self.hass.config_entries.async_get_entry(
            self.context["entry_id"]
        )

        if user_input is not None and config_entry is not None:
            try:
                # fill options not exposed in UI
                user_input[CONF_COMMAND] = config_entry.data[CONF_COMMAND]
                user_input[COMMAND_ARGS] = config_entry.data[COMMAND_ARGS]
                user_input[CONF_SCAN_INTERVAL] = config_entry.data[CONF_SCAN_INTERVAL]
                await validate_input(self.hass, user_input)
            except CannotConnect:
                errors["base"] = "cannot_connect"
            except InvalidAuth:
                errors["base"] = "invalid_auth"
            except Exception:  # pylint: disable=broad-except
                _LOGGER.exception("Unexpected exception")
                errors["base"] = "unknown"
            else:
                return self.async_update_reload_and_abort(
                    config_entry,
                    unique_id=config_entry.unique_id,
                    data={**config_entry.data, **user_input},
                    reason="reconfigure_successful",
                )
        if config_entry is not None:
            return self.async_show_form(
                step_id="reconfigure",
                data_schema=vol.Schema(
                    {
                        vol.Required(
                            CONF_FRIENDLY_NAME,
                            default=config_entry.data[CONF_FRIENDLY_NAME],
                        ): str,
                        vol.Required(
                            CONF_HOST, default=config_entry.data[CONF_HOST]
                        ): str,
                        vol.Required(
                            CONF_USERNAME, default=config_entry.data[CONF_USERNAME]
                        ): str,
                        vol.Required(CONF_PASSWORD): str,
                    }
                ),
                errors=errors,
            )
        return self.async_update_reload_and_abort(entry=self._get_reconfigure_entry())


class RcloneOptionsFlowHandler(OptionsFlow):
    """Handles the options flow."""

    def __init__(self, config_entry: ConfigEntry) -> None:
        """Initialize options flow."""
        self.options = dict(config_entry.options)

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Handle options flow."""
        if user_input is not None:
            options = self.config_entry.options | user_input
            # fill options not exposed in UI
            user_input[CONF_HOST] = self.config_entry.data[CONF_HOST]
            user_input[CONF_USERNAME] = self.config_entry.data[CONF_USERNAME]
            user_input[CONF_PASSWORD] = self.config_entry.data[CONF_PASSWORD]
            user_input[CONF_FRIENDLY_NAME] = self.config_entry.data[CONF_FRIENDLY_NAME]
            self.hass.config_entries.async_update_entry(
                self.config_entry, data=user_input, options=options
            )
            return self.async_create_entry(title="", data={})

        data_schema = vol.Schema(
            {
                vol.Required(
                    CONF_SCAN_INTERVAL,
                    default=self.config_entry.data[CONF_SCAN_INTERVAL],
                ): (vol.All(vol.Coerce(int), vol.Clamp(min=MIN_SCAN_INTERVAL))),
                vol.Required(
                    CONF_COMMAND, default=self.config_entry.data[CONF_COMMAND]
                ): SelectSelector(
                    SelectSelectorConfig(
                        options=[
                            SelectOptionDict(value=k, label=v)
                            for k, v in RCLONE_COMMANDS.items()
                        ],
                        translation_key="rclone commands",
                        mode=SelectSelectorMode.DROPDOWN,
                    )
                ),
                vol.Required(
                    COMMAND_ARGS,
                    default=self.config_entry.data[COMMAND_ARGS],
                    description={
                        "json blob - see https://rclone.org/rc/#specifying-remotes-to-work-on"
                    },
                ): str,
            }
        )

        return self.async_show_form(step_id="init", data_schema=data_schema)


class CannotConnect(HomeAssistantError):
    """Error to indicate we cannot connect."""


class InvalidAuth(HomeAssistantError):
    """Error to indicate there is invalid auth."""


# Safe JSON parsing with error handling
def parse_json(json_string: str) -> dict[str, Any] | None:
    """Parse JSON string safely."""
    try:
        return json.loads(json_string)
    except json.JSONDecodeError as err:
        _LOGGER.error("Invalid JSON: %s", err)
        return None
