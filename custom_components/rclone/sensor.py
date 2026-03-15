"""Interfaces with the Rclone api sensors."""

import datetime
import logging

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorStateClass,
)
from homeassistant.const import UnitOfDataRate, UnitOfInformation, UnitOfTime
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
    """Set up the Sensors."""
    # This gets the data update coordinator from the config entry runtime data as specified in the __init__.py
    coordinator: RcloneCoordinator = config_entry.runtime_data.coordinator

    # Enumerate all the sensors in the data value from the DataUpdateCoordinator and add an instance of the sensor class
    # to a list for each one.
    sensors: list[SensorEntity] = [
        BytesSensor(coordinator, device)
        for device in coordinator.data.devices
        if device.device_type
        in [DeviceType.BYTES_SENSOR, DeviceType.TOTAL_BYTES_SENSOR]
    ]
    sensors.extend(
        [
            DurationSensor(coordinator, device)
            for device in coordinator.data.devices
            if device.device_type in [DeviceType.DURATION_SENSOR, DeviceType.ETA_SENSOR]
        ]
    )
    sensors.extend(
        [
            TimestampSensor(coordinator, device)
            for device in coordinator.data.devices
            if device.device_type in [DeviceType.START_SENSOR, DeviceType.END_SENSOR]
        ]
    )
    sensors.extend(
        [
            DataRateSensor(coordinator, device)
            for device in coordinator.data.devices
            if device.device_type == DeviceType.SPEED_SENSOR
        ]
    )
    sensors.extend(
        [
            StringSensor(coordinator, device)
            for device in coordinator.data.devices
            if device.device_type == DeviceType.LAST_ERROR_SENSOR
        ]
    )
    sensors.extend(
        [
            CountSensor(coordinator, device)
            for device in coordinator.data.devices
            if device.device_type
            in [
                DeviceType.CHECKS_SENSOR,
                DeviceType.TRANSFERS_SENSOR,
                DeviceType.DELETEDDIRS_SENSOR,
                DeviceType.DELETES_SENSOR,
                DeviceType.ERRORS_SENSOR,
                DeviceType.LISTED_SENSOR,
                DeviceType.RENAMES_SENSOR,
                DeviceType.SERVERSIDECOPIES_SENSOR,
                DeviceType.SERVERSIDEMOVES_SENSOR,
                DeviceType.TOTALCHECKS_SENSOR,
                DeviceType.TOTALTRANSFERS_SENSOR,
            ]
        ]
    )

    # Create the sensors.
    async_add_entities(sensors)


class BytesSensor(CoordinatorEntity[RcloneCoordinator], SensorEntity):
    """Implementation of a sensor."""

    def __init__(self, coordinator: RcloneCoordinator, device: Device) -> None:
        """Initialise sensor."""
        super().__init__(coordinator)
        self.device = device
        self.device_id = device.device_id
        self.suggested_unit_of_measurement = UnitOfInformation.MEGABYTES

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
    def device_class(self) -> SensorDeviceClass | None:
        """Return device class."""
        # https://developers.home-assistant.io/docs/core/entity/sensor/#available-device-classes
        return SensorDeviceClass.DATA_SIZE

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
    def native_value(self) -> int | float | None:
        """Return the state of the entity."""
        if self.device.state is None:
            return None
        return float(self.device.state)

    @property
    def native_unit_of_measurement(self) -> str | None:
        """Return unit."""
        return UnitOfInformation.BYTES

    @property
    def state_class(self) -> SensorStateClass | None:
        """Return state class."""
        # https://developers.home-assistant.io/docs/core/entity/sensor/#available-state-classes
        return SensorStateClass.MEASUREMENT

    @property
    def unique_id(self) -> str:
        """Return unique id."""
        # All entities must have a unique id.
        # changing it later will cause HA to create new entities.
        return f"{DOMAIN}-{self.device.device_unique_id}"


class DurationSensor(CoordinatorEntity[RcloneCoordinator], SensorEntity):
    """Implementation of a sensor."""

    def __init__(self, coordinator: RcloneCoordinator, device: Device) -> None:
        """Initialise sensor."""
        super().__init__(coordinator)
        self.device = device
        self.device_id = device.device_id
        self.suggested_unit_of_measurement = UnitOfTime.MINUTES

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
    def device_class(self) -> SensorDeviceClass | None:
        """Return device class."""
        # https://developers.home-assistant.io/docs/core/entity/sensor/#available-device-classes
        return SensorDeviceClass.DURATION

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
    def native_value(self) -> int | float | None:
        """Return the state of the entity."""
        if self.device.state is None:
            return None
        return float(self.device.state)

    @property
    def native_unit_of_measurement(self) -> str | None:
        """Return unit."""
        return UnitOfTime.SECONDS

    @property
    def state_class(self) -> SensorStateClass | None:
        """Return state class."""
        # https://developers.home-assistant.io/docs/core/entity/sensor/#available-state-classes
        return SensorStateClass.MEASUREMENT

    @property
    def unique_id(self) -> str:
        """Return unique id."""
        # All entities must have a unique id.
        # changing it later will cause HA to create new entities.
        return f"{DOMAIN}-{self.device.device_unique_id}"

    @property
    def icon(self) -> str | None:
        """Icon to use in the frontend."""
        match self.device.device_type:
            case DeviceType.DURATION_SENSOR:
                return "mdi:timer-sync-outline"
        return None


class TimestampSensor(CoordinatorEntity[RcloneCoordinator], SensorEntity):
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
    def device_class(self) -> SensorDeviceClass | None:
        """Return device class."""
        # https://developers.home-assistant.io/docs/core/entity/sensor/#available-device-classes
        return SensorDeviceClass.TIMESTAMP

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
    def native_value(self) -> datetime.datetime | None:
        """Return the state of the entity."""
        if self.device.state == 0:
            return None
        return datetime.datetime.fromisoformat(str(self.device.state))

    @property
    def unique_id(self) -> str:
        """Return unique id."""
        # All entities must have a unique id.
        # changing it later will cause HA to create new entities.
        return f"{DOMAIN}-{self.device.device_unique_id}"

    @property
    def icon(self) -> str | None:
        """Icon to use in the frontend."""
        match self.device.device_type:
            case DeviceType.START_SENSOR:
                return "mdi:clock-start"
            case DeviceType.END_SENSOR:
                return "mdi:clock-end"
        return None


class CountSensor(CoordinatorEntity[RcloneCoordinator], SensorEntity):
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
    def native_value(self) -> int | None:
        """Return the state of the entity."""
        if self.device.state is None:
            return None
        return int(self.device.state)

    @property
    def state_class(self) -> SensorStateClass | None:
        """Return state class."""
        # https://developers.home-assistant.io/docs/core/entity/sensor/#available-state-classes
        return SensorStateClass.MEASUREMENT

    @property
    def unique_id(self) -> str:
        """Return unique id."""
        # All entities must have a unique id.
        # changing it later will cause HA to create new entities.
        return f"{DOMAIN}-{self.device.device_unique_id}"

    @property
    def icon(self) -> str | None:
        """Icon to use in the frontend."""
        match self.device.device_type:
            case DeviceType.CHECKS_SENSOR:
                return "mdi:equal"
            case DeviceType.DELETEDDIRS_SENSOR:
                return "mdi:folder-remove"
            case DeviceType.DELETES_SENSOR:
                return "mdi:delete"
            case DeviceType.ERRORS_SENSOR:
                return "mdi:alert-circle"
            case DeviceType.LISTED_SENSOR:
                return "mdi:format-list-bulleted"
            case DeviceType.RENAMES_SENSOR:
                return "mdi:rename"
            case DeviceType.SERVERSIDECOPIES_SENSOR:
                return "mdi:content-copy"
            case DeviceType.SERVERSIDEMOVES_SENSOR:
                return "mdi:file-move"
            case DeviceType.TOTALCHECKS_SENSOR:
                return "mdi:equal-box"
            case DeviceType.TRANSFERS_SENSOR:
                return "mdi:file-arrow-left-right-outline"
            case DeviceType.TOTALTRANSFERS_SENSOR:
                return "mdi:file-arrow-left-right"
            case DeviceType.BYTES_SENSOR:
                return "mdi:database-outline"
        return None


class DataRateSensor(CoordinatorEntity[RcloneCoordinator], SensorEntity):
    """Implementation of a sensor."""

    def __init__(self, coordinator: RcloneCoordinator, device: Device) -> None:
        """Initialise sensor."""
        super().__init__(coordinator)
        self.device = device
        self.device_id = device.device_id
        self.suggested_unit_of_measurement = UnitOfDataRate.MEGABYTES_PER_SECOND

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
    def device_class(self) -> SensorDeviceClass | None:
        """Return device class."""
        # https://developers.home-assistant.io/docs/core/entity/sensor/#available-device-classes
        return SensorDeviceClass.DATA_RATE

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
    def native_value(self) -> int | float | None:
        """Return the state of the entity."""
        if self.device.state is None:
            return None
        return int(self.device.state)

    @property
    def native_unit_of_measurement(self) -> str | None:
        """Return unit."""
        return UnitOfDataRate.BYTES_PER_SECOND

    @property
    def state_class(self) -> SensorStateClass | None:
        """Return state class."""
        # https://developers.home-assistant.io/docs/core/entity/sensor/#available-state-classes
        return SensorStateClass.MEASUREMENT

    @property
    def unique_id(self) -> str:
        """Return unique id."""
        # All entities must have a unique id.
        # changing it later will cause HA to create new entities.
        return f"{DOMAIN}-{self.device.device_unique_id}"


class StringSensor(CoordinatorEntity[RcloneCoordinator], SensorEntity):
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
    def native_value(self) -> str | None:
        """Return the state of the entity."""
        if self.device.state is None:
            return None
        return str(self.device.state)

    @property
    def unique_id(self) -> str:
        """Return unique id."""
        # All entities must have a unique id.
        # changing it later will cause HA to create new entities.
        return f"{DOMAIN}-{self.device.device_unique_id}"

    @property
    def icon(self) -> str:
        """Icon to use in the frontend."""
        return "mdi:comment-alert-outline"
