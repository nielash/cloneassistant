"""Interfaces with the Rclone api sensors."""

import logging

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
)
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from . import RcloneConfigEntry
from .api import Device, DeviceType
from .const import DOMAIN
from .coordinator import RcloneCoordinator

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: RcloneConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up the Binary Sensors."""
    # This gets the data update coordinator from the config entry runtime data as specified in __init__.py
    coordinator: RcloneCoordinator = config_entry.runtime_data.coordinator

    # Enumerate all the sensors in the data value from the DataUpdateCoordinator and add an instance of the binary sensor class
    # to a list for each one.
    binary_sensors = [
        HealthBinarySensor(coordinator, device)
        for device in coordinator.data.devices
        if device.device_type == DeviceType.HEALTH_SENSOR
    ]

    # Create the binary sensors.
    async_add_entities(binary_sensors)


class HealthBinarySensor(CoordinatorEntity[RcloneCoordinator], BinarySensorEntity):
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
    def device_class(self) -> BinarySensorDeviceClass:
        """Return device class."""
        # https://developers.home-assistant.io/docs/core/entity/binary-sensor#available-device-classes
        return BinarySensorDeviceClass.PROBLEM

    @property
    def device_info(self) -> DeviceInfo:
        """Return device information."""
        # Identifiers are what group entities into the same device.
        return DeviceInfo(
            manufacturer="Rclone",
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
        """Return if the binary sensor is on."""
        # This needs to enumerate to true or false
        return bool(self.device.state) if self.device.state is not None else None

    @property
    def unique_id(self) -> str:
        """Return unique id."""
        # All entities must have a unique id.
        # changing it later will cause HA to create new entities.
        return f"{DOMAIN}-{self.device.device_unique_id}"
