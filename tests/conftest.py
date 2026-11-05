"""Fixtures for the Rclone integration tests."""

from unittest.mock import patch

import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.rclone.const import CHECK, COMMAND_ARGS, DOMAIN
from homeassistant.const import (
    CONF_COMMAND,
    CONF_FRIENDLY_NAME,
    CONF_HOST,
    CONF_PASSWORD,
    CONF_SCAN_INTERVAL,
    CONF_USERNAME,
)
from homeassistant.core import HomeAssistant

VERSION_INFO = {
    "version": "v1.71.0",
    "osVersion": "14.5",
    "goVersion": "go1.24.0",
}


@pytest.fixture(name="rclone_command")
def rclone_command_fixture() -> str:
    """Return the rc method the job runs; parametrize to choose another."""
    return CHECK


@pytest.fixture(name="config_entry")
def config_entry_fixture(rclone_command: str) -> MockConfigEntry:
    """Return a config entry for a single rclone job."""
    return MockConfigEntry(
        domain=DOMAIN,
        title="Bisync",
        unique_id="Bisync",
        data={
            CONF_FRIENDLY_NAME: "Bisync",
            CONF_HOST: "192.168.0.2:5572",
            CONF_USERNAME: "test",
            CONF_PASSWORD: "1234",
            CONF_SCAN_INTERVAL: 60,
            CONF_COMMAND: rclone_command,
            COMMAND_ARGS: "{}",
        },
    )


@pytest.fixture(name="setup_integration")
def setup_integration_fixture(
    hass: HomeAssistant,
    config_entry: MockConfigEntry,
    enable_custom_integrations: None,
):
    """Return a callable that sets the integration up with rclone stubbed out.

    Not autouse: the api tests in this package are plain sync tests and must
    not drag in the Home Assistant harness.
    """

    async def _setup() -> MockConfigEntry:
        config_entry.add_to_hass(hass)
        with (
            patch("custom_components.rclone.api.API.noopauth_call", return_value=True),
            patch(
                "custom_components.rclone.api.API.version", return_value=VERSION_INFO
            ),
        ):
            await hass.config_entries.async_setup(config_entry.entry_id)
            await hass.async_block_till_done()
        return config_entry

    return _setup
