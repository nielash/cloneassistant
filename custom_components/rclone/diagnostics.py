"""Diagnostics support for Rclone."""

from __future__ import annotations

from dataclasses import asdict
from typing import Any

from homeassistant.components.diagnostics import async_redact_data
from homeassistant.const import CONF_PASSWORD
from homeassistant.core import HomeAssistant

from . import RcloneConfigEntry
from .const import COUNT_ERRORS_AS_FAILURE

TO_REDACT = {CONF_PASSWORD}


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, config_entry: RcloneConfigEntry
) -> dict[str, Any]:
    """Return diagnostics for a config entry."""
    coordinator = config_entry.runtime_data.coordinator
    return async_redact_data(
        {
            "entry_data": dict(config_entry.data),
            # The verdict this option produces is what drives Last Success Time,
            # so surface it next to its value.
            "options": {COUNT_ERRORS_AS_FAILURE: coordinator.count_errors_as_failure},
            # asdict below already carries every device, but it is a long list to
            # read through -- this is the same data keyed by the name shown in
            # the UI, so a report can be skimmed for "why is this sensor wrong?".
            "sensor_states": {
                device.name: device.state for device in coordinator.data.devices
            },
            "coordinator_data": asdict(coordinator.data),
        },
        TO_REDACT,
    )
