"""Rclone integration using DataUpdateCoordinator."""

from dataclasses import dataclass
from datetime import timedelta
from functools import partial
import json
import logging
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import (
    CONF_COMMAND,
    CONF_FRIENDLY_NAME,
    CONF_HOST,
    CONF_PASSWORD,
    CONF_SCAN_INTERVAL,
    CONF_USERNAME,
)
from homeassistant.core import DOMAIN as HOMEASSISTANT_DOMAIN, HomeAssistant
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .api import API, APIAuthError, Device, DeviceType
from .const import COMMAND_ARGS

_LOGGER = logging.getLogger(__name__)


@dataclass
class RcloneAPIData:
    """Class to hold api data."""

    controller_name: str
    version_info: dict[str, Any]
    devices: list[Device]


class RcloneCoordinator(DataUpdateCoordinator[RcloneAPIData]):
    """Our coordinator."""

    data: RcloneAPIData

    def __init__(self, hass: HomeAssistant, config_entry: ConfigEntry) -> None:
        """Initialize coordinator."""

        # Set variables from values entered in config flow setup
        self.host = config_entry.data[CONF_HOST]
        self.user = config_entry.data[CONF_USERNAME]
        self.pwd = config_entry.data[CONF_PASSWORD]
        self.friendly_name = config_entry.data[CONF_FRIENDLY_NAME]
        self.rclone_command = config_entry.data[CONF_COMMAND]
        self.command_args = config_entry.data[COMMAND_ARGS]
        self.poll_interval = config_entry.data[CONF_SCAN_INTERVAL]

        # Initialise DataUpdateCoordinator
        super().__init__(
            hass,
            _LOGGER,
            config_entry=config_entry,
            name=f"{HOMEASSISTANT_DOMAIN} ({config_entry.unique_id})",
            # Method to call on every update interval.
            update_method=self.async_update_data,
            # Polling interval. Will only be polled if there are subscribers.
            # Using config option here but you can just use a value.
            update_interval=timedelta(seconds=self.poll_interval),
        )

        # Initialise the api here
        self.api = API(
            host=self.host,
            user=self.user,
            pwd=self.pwd,
            friendly_name=self.friendly_name,
        )

    async def async_update_data(self):
        """Fetch data from API endpoint.

        This is the place to pre-process the data to lookup tables
        so entities can quickly look up their data.
        """
        try:
            if not self.api.connected:
                await self.hass.async_add_executor_job(self.api.connect)
            devices = await self.hass.async_add_executor_job(self.api.get_devices)
            if self.data:
                devices = await self.hass.async_add_executor_job(
                    partial(self.api.get_jobstatus, self.data.devices)
                )
        except APIAuthError as err:
            _LOGGER.error(err)
            raise UpdateFailed(err) from err
        except Exception as err:
            # This will show entities as unavailable by raising UpdateFailed exception
            raise UpdateFailed(f"Error communicating with API: {err}") from err

        # What is returned here is stored in self.data by the DataUpdateCoordinator
        return RcloneAPIData(self.api.controller_name, self.api.version_info, devices)

    def get_device_by_id(
        self, device_type: DeviceType, device_id: int
    ) -> Device | None:
        """Return device by device id."""
        # Called by the binary sensors and sensors to get their updated data from self.data
        try:
            return [
                device
                for device in self.data.devices
                if device.device_type == device_type and device.device_id == device_id
            ][0]
        except IndexError:
            return None

    async def start_job(self, device_type: DeviceType, device_id: int) -> None:
        """Start the job."""
        try:
            payload = parse_json(self.command_args)
            if payload is not None:
                job_id = await self.api.async_job_call(
                    self.rclone_command,
                    payload,
                )
                device = self.get_device_by_id(device_type, device_id)
                if device and job_id > 0:
                    device.rclonejobid = job_id
                await self.hass.async_add_executor_job(
                    partial(self.api.get_jobstatus, self.data.devices)
                )
        except APIAuthError as err:
            _LOGGER.error(err)
            raise UpdateFailed(err) from err
        except Exception as err:
            # This will show entities as unavailable by raising UpdateFailed exception
            raise UpdateFailed(f"Error communicating with API: {err}") from err

    async def stop_job(self, device_type: DeviceType, device_id: int) -> None:
        """Attempt to stop the job."""
        device = self.get_device_by_id(device_type, device_id)
        if not device:
            _LOGGER.warning("Device %s not found", device_id)
            return
        jobid = device.rclonejobid
        if jobid == 0:
            _LOGGER.warning("No job to stop for device %s", device_id)
            return
        await self.api.async_stop_job_call(jobid)
        # the job_id returned is that of the stop job, not the job that was stopped


# Safe JSON parsing with error handling
def parse_json(json_string: str) -> dict[str, Any] | None:
    """Parse JSON string safely."""
    try:
        return json.loads(json_string)
    except json.JSONDecodeError as err:
        _LOGGER.error("Invalid JSON: %s", err)
        _LOGGER.debug(json_string)
        return None
