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
    COUNT_ERRORS_AS_FAILURE,
    DEFAULT_COUNT_ERRORS_AS_FAILURE,
    DEFAULT_SCAN_INTERVAL,
    DOMAIN,
    MIN_SCAN_INTERVAL,
    RCLONE_COMMANDS,
)

_LOGGER = logging.getLogger(__name__)

# Linked from the command_args description. hassfest rejects URLs in the
# strings themselves, so the forms that show the field pass it in.
DESCRIPTION_PLACEHOLDERS = {
    "rc_docs_url": "https://rclone.org/rc/#specifying-remotes-to-work-on"
}

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
        vol.Required(COMMAND_ARGS, default="{}"): str,
    }
)


def command_args_errors(data: dict[str, Any]) -> dict[str, str]:
    """Return the form errors for command_args, keyed by field.

    rc takes its parameters as a JSON object, so anything else -- a parse
    error, or valid JSON that is a list, a string, or null -- is rejected
    here rather than when the job is first started.
    """
    try:
        args = json.loads(data[COMMAND_ARGS])
    except ValueError:
        return {COMMAND_ARGS: "invalid_json"}
    if not isinstance(args, dict):
        return {COMMAND_ARGS: "invalid_json"}
    return {}


async def validate_input(hass: HomeAssistant, data: dict[str, Any]) -> dict[str, Any]:
    """Validate the user input allows us to connect.

    Data has the keys from STEP_USER_DATA_SCHEMA with values provided by the user.
    """
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
            # Check the JSON first: it needs no network, and a connection
            # error would otherwise hide it.
            errors = command_args_errors(user_input)
            if not errors:
                try:
                    info = await validate_input(self.hass, user_input)
                except CannotConnect:
                    errors["base"] = "cannot_connect"
                except InvalidAuth:
                    errors["base"] = "invalid_auth"
                except Exception:  # pylint: disable=broad-except
                    _LOGGER.exception("Unexpected exception")
                    errors["base"] = "unknown"

            if not errors:
                await self.async_set_unique_id(info.get("title"))
                self._abort_if_unique_id_configured()
                return self.async_create_entry(title=info["title"], data=user_input)

        # Show the form: empty the first time, and after an error with what
        # the user entered, so they only have to correct the field that failed.
        return self.async_show_form(
            step_id="user",
            data_schema=self.add_suggested_values_to_schema(
                STEP_USER_DATA_SCHEMA, user_input
            ),
            errors=errors,
            description_placeholders=DESCRIPTION_PLACEHOLDERS,
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
                user_input[COUNT_ERRORS_AS_FAILURE] = config_entry.data.get(
                    COUNT_ERRORS_AS_FAILURE, DEFAULT_COUNT_ERRORS_AS_FAILURE
                )
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
            # After an error, show what the user entered rather than the
            # saved values. command_args is not on this form and is not
            # checked here: the options flow is where it is edited, and a
            # stored value this form cannot change must not block it.
            return self.async_show_form(
                step_id="reconfigure",
                data_schema=self.add_suggested_values_to_schema(
                    vol.Schema(
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
                    user_input,
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
        errors: dict[str, str] = {}
        if user_input is not None:
            errors = command_args_errors(user_input)
        if user_input is not None and not errors:
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
                    COMMAND_ARGS, default=self.config_entry.data[COMMAND_ARGS]
                ): str,
                vol.Required(
                    COUNT_ERRORS_AS_FAILURE,
                    default=self.config_entry.data.get(
                        COUNT_ERRORS_AS_FAILURE, DEFAULT_COUNT_ERRORS_AS_FAILURE
                    ),
                ): bool,
            }
        )

        return self.async_show_form(
            step_id="init",
            data_schema=self.add_suggested_values_to_schema(data_schema, user_input),
            errors=errors,
            description_placeholders=DESCRIPTION_PLACEHOLDERS,
        )


class CannotConnect(HomeAssistantError):
    """Error to indicate we cannot connect."""


class InvalidAuth(HomeAssistantError):
    """Error to indicate there is invalid auth."""
