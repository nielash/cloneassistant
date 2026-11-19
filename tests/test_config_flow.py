"""Tests for the config, reconfigure and options flows.

After an error, every form must come back holding what the user entered
(issue #6), and a bad command_args must be reported against that field, not as
an authentication error (issue #7).
"""

from contextlib import contextmanager
import json
from pathlib import Path
import re
from typing import Any
from unittest.mock import patch

import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.rclone.api import APIAuthError, APIConnectionError
from custom_components.rclone.config_flow import STEP_USER_DATA_SCHEMA
from custom_components.rclone.const import (
    CHECK,
    COMMAND_ARGS,
    COUNT_ERRORS_AS_FAILURE,
    DOMAIN,
    SYNC,
)
from homeassistant import config_entries
from homeassistant.const import (
    CONF_COMMAND,
    CONF_FRIENDLY_NAME,
    CONF_HOST,
    CONF_PASSWORD,
    CONF_SCAN_INTERVAL,
    CONF_USERNAME,
)
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType

from .conftest import VERSION_INFO

NOOPAUTH = "custom_components.rclone.api.API.noopauth_call"
VERSION = "custom_components.rclone.api.API.version"
COMPONENT = Path(__file__).parent.parent / "custom_components" / DOMAIN

USER_INPUT = {
    CONF_FRIENDLY_NAME: "Photos",
    CONF_HOST: "10.0.0.9:5572",
    CONF_USERNAME: "bas",
    CONF_PASSWORD: "secret",
    CONF_SCAN_INTERVAL: 120,
    CONF_COMMAND: SYNC,
    COMMAND_ARGS: '{"srcFs": "a:", "dstFs": "b:"}',
}

# Not a JSON object: unparseable, empty, or valid JSON of another type.
BAD_ARGS = [",{}", "{key: value}", "", "[1, 2]", '"a:"', "null", "5"]

CONNECT_ERRORS = [
    (APIAuthError("401"), "invalid_auth"),
    (APIConnectionError("refused"), "cannot_connect"),
    (RuntimeError("boom"), "unknown"),
]


def shown_values(result: dict[str, Any]) -> dict[str, Any]:
    """Return the value each field of a shown form starts out holding.

    The frontend fills a field from its suggested value, falling back to its
    default, so that is what the user sees.
    """
    values = {}
    for key in result["data_schema"].schema:
        description = key.description if isinstance(key.description, dict) else {}
        if "suggested_value" in description:
            values[key.schema] = description["suggested_value"]
        elif callable(key.default):
            values[key.schema] = key.default()
    return values


@contextmanager
def rclone(connect_error=None):
    """Stand in for the rcd: connect() calls noopauth_call, then version().

    Yields the noopauth_call mock, to check whether a connection was tried.
    """
    with (
        patch(NOOPAUTH, side_effect=connect_error, return_value=True) as noop,
        patch(VERSION, return_value=VERSION_INFO),
    ):
        yield noop


async def submit_user(
    hass: HomeAssistant, user_input: dict[str, Any], connect_error=None
):
    """Start an add flow and submit user_input; return (result, noopauth mock)."""
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    with rclone(connect_error) as noop:
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], user_input
        )
        # A created entry is set up in the background; let it finish here.
        await hass.async_block_till_done()
    return result, noop


# --- add ---------------------------------------------------------------------


async def test_user_creates_entry(
    hass: HomeAssistant, enable_custom_integrations: None
) -> None:
    """Valid input with a reachable rcd creates the entry as entered."""
    with patch("custom_components.rclone.async_setup_entry", return_value=True):
        result, _ = await submit_user(hass, USER_INPUT)

    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["title"] == "Photos"
    assert result["data"] == USER_INPUT


@pytest.mark.parametrize(("connect_error", "expected"), CONNECT_ERRORS)
async def test_user_connect_error_keeps_input(
    hass: HomeAssistant, enable_custom_integrations: None, connect_error, expected
) -> None:
    """A failed connection reports why and shows the form as the user left it."""
    result, _ = await submit_user(hass, USER_INPUT, connect_error)

    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"base": expected}
    assert shown_values(result) == USER_INPUT


@pytest.mark.parametrize("bad_args", BAD_ARGS)
async def test_user_bad_command_args(
    hass: HomeAssistant, enable_custom_integrations: None, bad_args: str
) -> None:
    """Bad JSON is reported on its field, before any connection attempt."""
    user_input = {**USER_INPUT, COMMAND_ARGS: bad_args}
    result, noop = await submit_user(hass, user_input, APIAuthError("401"))

    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {COMMAND_ARGS: "invalid_json"}
    noop.assert_not_called()
    assert shown_values(result) == user_input


async def test_user_corrected_after_error(
    hass: HomeAssistant, enable_custom_integrations: None
) -> None:
    """The same flow goes through once the bad field is fixed."""
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    with rclone():
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {**USER_INPUT, COMMAND_ARGS: "{key: value}"}
        )
        assert result["errors"] == {COMMAND_ARGS: "invalid_json"}
        with patch("custom_components.rclone.async_setup_entry", return_value=True):
            result = await hass.config_entries.flow.async_configure(
                result["flow_id"], USER_INPUT
            )
            await hass.async_block_till_done()

    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["data"] == USER_INPUT


async def test_user_first_form_and_default_args(
    hass: HomeAssistant, enable_custom_integrations: None
) -> None:
    """The first form is unchanged, and its command_args default is valid."""
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )

    assert result["errors"] == {}
    shown = shown_values(result)
    assert shown[CONF_FRIENDLY_NAME] == "Bisync"
    assert shown[CONF_COMMAND] == CHECK
    # A user who leaves it alone must not hit invalid_json.
    assert json.loads(shown[COMMAND_ARGS]) == {}


def test_schema_descriptions_are_dicts() -> None:
    """A marker description must be a dict.

    command_args once had a set here, which the frontend ignored, and which
    breaks any Home Assistant whose add_suggested_values_to_schema reads the
    description with .get().
    """
    for key in STEP_USER_DATA_SCHEMA.schema:
        assert key.description is None or isinstance(key.description, dict), key


# --- reconfigure -------------------------------------------------------------

RECONFIGURE_INPUT = {
    CONF_FRIENDLY_NAME: "Renamed",
    CONF_HOST: "10.0.0.10:5572",
    CONF_USERNAME: "bas",
    CONF_PASSWORD: "new-secret",
}


async def submit_reconfigure(
    hass: HomeAssistant, entry: MockConfigEntry, connect_error=None
):
    """Start a reconfigure flow and submit RECONFIGURE_INPUT."""
    result = await entry.start_reconfigure_flow(hass)
    with (
        rclone(connect_error),
        patch("custom_components.rclone.async_setup_entry", return_value=True),
    ):
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], dict(RECONFIGURE_INPUT)
        )
        # A successful reconfigure reloads the entry in the background.
        await hass.async_block_till_done()
    return result


@pytest.mark.parametrize(("connect_error", "expected"), CONNECT_ERRORS)
async def test_reconfigure_error_keeps_input(
    hass: HomeAssistant,
    enable_custom_integrations: None,
    config_entry: MockConfigEntry,
    connect_error,
    expected,
) -> None:
    """A failed reconfigure shows the edits, not the saved values, and saves nothing."""
    config_entry.add_to_hass(hass)
    saved = dict(config_entry.data)

    result = await submit_reconfigure(hass, config_entry, connect_error)

    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"base": expected}
    assert shown_values(result) == RECONFIGURE_INPUT
    assert dict(config_entry.data) == saved


async def test_reconfigure_first_form_shows_saved_values(
    hass: HomeAssistant,
    enable_custom_integrations: None,
    config_entry: MockConfigEntry,
) -> None:
    """Before any error, the form starts from the saved entry, password blank."""
    config_entry.add_to_hass(hass)
    result = await config_entry.start_reconfigure_flow(hass)

    assert shown_values(result) == {
        CONF_FRIENDLY_NAME: "Bisync",
        CONF_HOST: "192.168.0.2:5572",
        CONF_USERNAME: "test",
    }


async def test_reconfigure_not_blocked_by_stored_bad_args(
    hass: HomeAssistant, enable_custom_integrations: None
) -> None:
    """Bad stored command_args, which this form cannot edit, do not block it.

    Before the options flow checked command_args, it could save bad JSON, and
    reconfigure then failed with invalid_auth on every attempt.
    """
    entry = MockConfigEntry(
        domain=DOMAIN,
        title="Bisync",
        unique_id="Bisync",
        data={
            CONF_FRIENDLY_NAME: "Bisync",
            CONF_HOST: "192.168.0.2:5572",
            CONF_USERNAME: "test",
            CONF_PASSWORD: "1234",
            CONF_SCAN_INTERVAL: 60,
            CONF_COMMAND: CHECK,
            COMMAND_ARGS: ",{}",
        },
    )
    entry.add_to_hass(hass)

    result = await submit_reconfigure(hass, entry)

    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "reconfigure_successful"
    assert entry.data[CONF_HOST] == "10.0.0.10:5572"
    assert entry.data[COMMAND_ARGS] == ",{}"


# --- options -----------------------------------------------------------------

OPTIONS_INPUT = {
    CONF_SCAN_INTERVAL: 90,
    CONF_COMMAND: SYNC,
    COMMAND_ARGS: '{"srcFs": "a:", "dstFs": "b:"}',
    COUNT_ERRORS_AS_FAILURE: True,
}


async def submit_options(hass: HomeAssistant, entry: MockConfigEntry, user_input):
    """Open the options flow on a set-up entry and submit user_input."""
    result = await hass.config_entries.options.async_init(entry.entry_id)
    # A save reloads the entry, which talks to rclone again.
    with rclone():
        result = await hass.config_entries.options.async_configure(
            result["flow_id"], dict(user_input)
        )
        await hass.async_block_till_done()
    return result


@pytest.mark.parametrize("bad_args", BAD_ARGS)
async def test_options_bad_command_args(
    hass: HomeAssistant, setup_integration, bad_args: str
) -> None:
    """The options flow rejects bad JSON instead of saving it, and keeps the input."""
    entry = await setup_integration()
    saved = dict(entry.data)
    user_input = {**OPTIONS_INPUT, COMMAND_ARGS: bad_args}

    result = await submit_options(hass, entry, user_input)

    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {COMMAND_ARGS: "invalid_json"}
    assert shown_values(result) == user_input
    assert dict(entry.data) == saved


async def test_options_saves_valid_input(
    hass: HomeAssistant, setup_integration
) -> None:
    """Valid options are saved to data, with the connection settings kept."""
    entry = await setup_integration()
    saved = dict(entry.data)

    result = await submit_options(hass, entry, OPTIONS_INPUT)

    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert dict(entry.data) == {
        **OPTIONS_INPUT,
        CONF_HOST: saved[CONF_HOST],
        CONF_USERNAME: saved[CONF_USERNAME],
        CONF_PASSWORD: saved[CONF_PASSWORD],
        CONF_FRIENDLY_NAME: saved[CONF_FRIENDLY_NAME],
    }
    await hass.config_entries.async_unload(entry.entry_id)
    await hass.async_block_till_done()


# --- strings -----------------------------------------------------------------


@pytest.mark.parametrize("name", ["strings.json", "translations/en.json"])
@pytest.mark.parametrize("flow", ["config", "options"])
def test_invalid_json_is_translated(name: str, flow: str) -> None:
    """The new error has text in both files, or the UI shows a raw key."""
    strings = json.loads((COMPONENT / name).read_text())
    assert strings[flow]["error"]["invalid_json"]


def step_placeholders(name: str, flow: str, step: str) -> set[str]:
    """Return the {placeholders} a step's strings in the named file use."""
    strings = json.loads((COMPONENT / name).read_text())[flow]["step"][step]
    text = json.dumps(
        [strings.get("description", ""), strings.get("data_description", {})]
    )
    return set(re.findall(r"\{(\w+)\}", text))


async def test_user_form_fills_its_placeholders(
    hass: HomeAssistant, enable_custom_integrations: None
) -> None:
    """Every {placeholder} in the add form's strings is filled, before and after an error.

    One that is not shows up in the UI as raw text, such as {rc_docs_url}.
    """
    first = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    after_error, _ = await submit_user(hass, USER_INPUT, APIAuthError("401"))

    for name in ("strings.json", "translations/en.json"):
        used = step_placeholders(name, "config", "user")
        assert "rc_docs_url" in used
        for result in (first, after_error):
            assert used <= set(result["description_placeholders"] or {})


async def test_options_form_fills_its_placeholders(
    hass: HomeAssistant, setup_integration
) -> None:
    """Every {placeholder} in the options form's strings is filled, before and after an error."""
    entry = await setup_integration()
    first = await hass.config_entries.options.async_init(entry.entry_id)
    after_error = await submit_options(
        hass, entry, {**OPTIONS_INPUT, COMMAND_ARGS: ",{}"}
    )

    for name in ("strings.json", "translations/en.json"):
        used = step_placeholders(name, "options", "init")
        assert "rc_docs_url" in used
        for result in (first, after_error):
            assert used <= set(result["description_placeholders"] or {})
