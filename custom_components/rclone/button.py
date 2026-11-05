"""Buttons that run the job once as a dry run or, for bisync, a resync."""

from collections.abc import Callable
from dataclasses import dataclass
import logging

from homeassistant.components.button import ButtonEntity, ButtonEntityDescription
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from . import RcloneConfigEntry
from .api import DeviceType
from .const import BISYNC, DOMAIN, READ_ONLY_COMMANDS
from .coordinator import RcloneCoordinator

_LOGGER = logging.getLogger(__name__)

PLATFORM = "button"


@dataclass(frozen=True, kw_only=True)
class RcloneButtonEntityDescription(ButtonEntityDescription):
    """Describes a button that starts one run of the job."""

    dry_run: bool = False
    resync: bool = False
    # Whether a job running this rc method gets the button.
    available_for: Callable[[str], bool]


BUTTONS: tuple[RcloneButtonEntityDescription, ...] = (
    RcloneButtonEntityDescription(
        key="dry_run",
        translation_key="dry_run",
        dry_run=True,
        # A command that only reads would do nothing different.
        available_for=lambda command: command not in READ_ONLY_COMMANDS,
    ),
    RcloneButtonEntityDescription(
        key="resync",
        translation_key="resync",
        resync=True,
        available_for=lambda command: command == BISYNC,
    ),
    RcloneButtonEntityDescription(
        key="resync_dry_run",
        translation_key="resync_dry_run",
        dry_run=True,
        resync=True,
        available_for=lambda command: command == BISYNC,
    ),
)


def button_unique_id(coordinator: RcloneCoordinator, key: str) -> str:
    """Return a button's unique id."""
    return f"{DOMAIN}-{coordinator.api.unfriendly_name}_{key}"


async def async_setup_entry(
    hass: HomeAssistant,
    config_entry: RcloneConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up the buttons that apply to this job's command."""
    coordinator: RcloneCoordinator = config_entry.runtime_data.coordinator
    command = coordinator.rclone_command
    parent = coordinator.api.get_parent(coordinator.data.devices)
    if parent is None:
        return

    registry = er.async_get(hass)
    buttons = []
    for description in BUTTONS:
        if description.available_for(command):
            buttons.append(RcloneJobButton(coordinator, parent.device_id, description))
            continue
        # The command can change in the options flow, which reloads the entry.
        # A button the new command does not get would otherwise stay behind in
        # the registry as unavailable.
        entity_id = registry.async_get_entity_id(
            PLATFORM, DOMAIN, button_unique_id(coordinator, description.key)
        )
        if entity_id:
            _LOGGER.debug("Removing %s, which %s does not use", entity_id, command)
            registry.async_remove(entity_id)

    async_add_entities(buttons)


class RcloneJobButton(CoordinatorEntity[RcloneCoordinator], ButtonEntity):
    """A button that starts one run of the job, as a dry run or a resync."""

    _attr_has_entity_name = True
    entity_description: RcloneButtonEntityDescription

    def __init__(
        self,
        coordinator: RcloneCoordinator,
        device_id: int,
        description: RcloneButtonEntityDescription,
    ) -> None:
        """Initialise the button."""
        super().__init__(coordinator)
        self.entity_description = description
        self.device_id = device_id
        self._attr_unique_id = button_unique_id(coordinator, description.key)

    @property
    def device_info(self) -> DeviceInfo:
        """Return device information."""
        return self.coordinator.job_device_info(self.device_id)

    async def async_press(self) -> None:
        """Start the run, unless one is already going."""
        # A button, unlike the switch, can be pressed while the job runs.
        # Starting another would replace the jobid being waited on, so the
        # run already going would never be reported.
        if self.coordinator.job_running():
            raise HomeAssistantError(
                translation_domain=DOMAIN, translation_key="job_running"
            )
        await self.coordinator.start_job(
            DeviceType.JOB_SWITCH,
            self.device_id,
            dry_run=self.entity_description.dry_run,
            resync=self.entity_description.resync,
        )
        self.coordinator.async_set_updated_data(self.coordinator.data)
        await self.coordinator.async_request_refresh()
