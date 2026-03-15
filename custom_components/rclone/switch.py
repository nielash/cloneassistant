"""Interfaces with the Rclone api sensors."""

from collections.abc import Mapping
import logging
from typing import Any

from homeassistant.components.switch import SwitchDeviceClass, SwitchEntity
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from . import RcloneConfigEntry
from .api import Device, DeviceType
from .const import COMMAND_ARGS, DOMAIN
from .coordinator import RcloneCoordinator

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: RcloneConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up the Switches."""
    # This gets the data update coordinator from the config entry runtime data as specified in __init__.py
    coordinator: RcloneCoordinator = config_entry.runtime_data.coordinator

    # Enumerate all the sensors in the data value from the DataUpdateCoordinator and add an instance of the switch class
    # to a list for each one.
    switches = [
        RcloneJobSwitch(coordinator, device)
        for device in coordinator.data.devices
        if device.device_type == DeviceType.JOB_SWITCH
    ]

    # Create the switches.
    async_add_entities(switches)


class RcloneJobSwitch(CoordinatorEntity[RcloneCoordinator], SwitchEntity):
    """Implementation of a sensor."""

    def __init__(self, coordinator: RcloneCoordinator, device: Device) -> None:
        """Initialise sensor."""
        super().__init__(coordinator)
        self.device = device
        self.device_id = device.device_id

    @callback
    def _handle_coordinator_update(self) -> None:
        """Update sensor with latest data from coordinator."""
        # This method is called by the DataUpdateCoordinator when a successful update runs.
        device = self.coordinator.get_device_by_id(
            self.device.device_type, self.device_id
        )
        if device:
            self.device = device
            _LOGGER.debug("Device: %s", self.device)
            self.async_write_ha_state()

    @property
    def device_class(self) -> SwitchDeviceClass:
        """Return device class."""
        # https://developers.home-assistant.io/docs/core/entity/switch#available-device-classes
        return SwitchDeviceClass.SWITCH

    @property
    def device_info(self) -> DeviceInfo:
        """Return device information."""
        # Identifiers are what group entities into the same device.
        title = ""
        sw_version = "0"
        hw_version = "0"
        model_id = "0"
        if self.coordinator.config_entry:
            title = self.coordinator.config_entry.title
        if self.coordinator.data.version_info["version"]:
            sw_version = self.coordinator.data.version_info["version"]
            hw_version = self.coordinator.data.version_info["osVersion"]
            model_id = self.coordinator.data.version_info["goVersion"]
        return DeviceInfo(
            name=f"{title}",
            manufacturer="Rclone",
            model="rc",
            sw_version=sw_version,
            hw_version=hw_version,
            model_id=model_id,
            identifiers={
                (
                    DOMAIN,
                    f"{self.coordinator.data.controller_name}-{self.device.device_id}",
                )
            },
        )

    @property
    def name(self) -> str:
        """Return the name of the sensor."""
        return self.device.name

    @property
    def is_on(self) -> bool | None:
        """Return if the switch is on."""
        # This needs to enumerate to true or false
        return bool(self.device.state) if self.device.state is not None else None

    @property
    def unique_id(self) -> str:
        """Return unique id."""
        # All entities must have a unique id.
        # changing it later will cause HA to create new entities.
        return f"{DOMAIN}-{self.device.device_unique_id}"

    @property
    def extra_state_attributes(self) -> Mapping[str, Any]:
        """Return the extra state attributes."""
        attrs = {}
        entry = self.coordinator.config_entry
        if entry:
            attrs["command"] = entry.options.get("command")
            attrs["args"] = entry.options.get(COMMAND_ARGS)
        if self.device.atts is not None:
            attrs["jobid"] = self.device.atts["jobid"]
            attrs["output"] = self.device.atts["output"]
        return attrs

    # These methods allow HA to tell the actual device what to do.
    async def async_turn_on(self, **kwargs: Any) -> None:
        """Start the job."""
        await self.coordinator.start_job(self.device.device_type, self.device_id)
        self.async_write_ha_state()
        self.coordinator.async_set_updated_data(self.coordinator.data)
        await self.coordinator.async_request_refresh()

    async def async_turn_off(self, **kwargs: Any) -> None:
        """Attempt to stop the job."""
        await self.coordinator.stop_job(self.device.device_type, self.device_id)
