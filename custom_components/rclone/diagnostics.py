"""Diagnostics support for Rclone."""

from __future__ import annotations

from dataclasses import asdict
from typing import Any

from homeassistant.components.diagnostics import async_redact_data
from homeassistant.const import CONF_PASSWORD
from homeassistant.core import HomeAssistant

from . import RcloneConfigEntry

TO_REDACT = {CONF_PASSWORD}


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, config_entry: RcloneConfigEntry
) -> dict[str, Any]:
    """Return diagnostics for a config entry."""
    return async_redact_data(
        {
            "entry_data": dict(config_entry.data),
            "coordinator_data": asdict(config_entry.runtime_data.coordinator.data),
        },
        TO_REDACT,
    )
