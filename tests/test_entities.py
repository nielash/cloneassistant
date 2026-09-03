"""Tests for entity naming and for the state that has to survive a restart."""

from datetime import datetime, timezone

from homeassistant.components.sensor import SensorExtraStoredData
from homeassistant.const import STATE_UNKNOWN
from homeassistant.core import HomeAssistant, State
from homeassistant.helpers import entity_registry as er

from custom_components.rclone.const import DOMAIN
from custom_components.rclone.sensor import LastSuccessSensor

from pytest_homeassistant_custom_component.common import (
    mock_restore_cache,
    mock_restore_cache_with_extra_data,
)

LAST_SUCCESS = "sensor.bisync_last_success_time"
HEALTH = "binary_sensor.bisync_health"
JOB_SWITCH = "switch.bisync"

SUCCEEDED_AT = datetime(2026, 9, 3, 8, 20, 11, tzinfo=timezone.utc)


def enable_last_success(hass: HomeAssistant) -> None:
    """Register Last Success Time as enabled, as a user who turned it on has it.

    It is disabled by default, and that default only applies when the entity
    is first registered, so an entry that already exists keeps its setting.
    """
    er.async_get(hass).async_get_or_create(
        "sensor",
        DOMAIN,
        "rclone-bisync_Last Success Time",
        suggested_object_id="bisync_last_success_time",
    )


def restore_last_success(hass: HomeAssistant) -> None:
    """Leave an enabled Last Success Time of SUCCEEDED_AT, as a restart would."""
    enable_last_success(hass)
    mock_restore_cache_with_extra_data(
        hass,
        (
            (
                State(LAST_SUCCESS, SUCCEEDED_AT.isoformat()),
                {
                    "native_value": {
                        "__type": "<class 'datetime.datetime'>",
                        "isoformat": SUCCEEDED_AT.isoformat(),
                    },
                    "native_unit_of_measurement": None,
                },
            ),
        ),
    )


async def test_entity_ids_are_prefixed_with_the_device(
    hass: HomeAssistant, setup_integration
) -> None:
    """has_entity_name composes "<device> <role>" instead of a bare role.

    Without it a second job produced binary_sensor.health_2, and there was no
    way to tell from the entity id which job it belonged to.
    """
    await setup_integration()

    registry = er.async_get(hass)
    for entity_id in (LAST_SUCCESS, HEALTH, JOB_SWITCH):
        assert registry.async_get(entity_id) is not None, f"missing {entity_id}"

    # The role is the entity's own name; the device supplies the rest.
    assert registry.async_get(HEALTH).original_name == "Health"
    assert hass.states.get(HEALTH).attributes["friendly_name"] == "Bisync Health"

    # The switch is the job itself, so it takes the device name outright.
    assert registry.async_get(JOB_SWITCH).original_name is None
    assert hass.states.get(JOB_SWITCH).attributes["friendly_name"] == "Bisync"


async def test_unique_ids_are_unchanged(
    hass: HomeAssistant, setup_integration
) -> None:
    """Renaming must not orphan the entities of an existing install."""
    await setup_integration()

    registry = er.async_get(hass)
    assert registry.async_get(HEALTH).unique_id == "rclone-bisync_Health"
    assert registry.async_get(JOB_SWITCH).unique_id == "rclone-bisync_Bisync"


async def test_last_success_time_is_restored(
    hass: HomeAssistant, setup_integration
) -> None:
    """Rclone forgets finished jobs, so this must survive a restart."""
    restore_last_success(hass)
    entry = await setup_integration()

    assert hass.states.get(LAST_SUCCESS).state == SUCCEEDED_AT.isoformat()

    # Restored onto the shared device object, not just the entity: that is what
    # the API mutates, so the next completed run compares against the real value.
    coordinator = entry.runtime_data.coordinator
    device = coordinator.get_device_by_id(
        next(
            d.device_type
            for d in coordinator.data.devices
            if d.name == "Last Success Time"
        ),
        1,
    )
    assert device.state == SUCCEEDED_AT.isoformat()


async def test_health_is_not_restored(
    hass: HomeAssistant, setup_integration
) -> None:
    """Health deliberately has no restore behavior.

    It describes the run rclone last reported on. Replaying a stale Problem
    across a restart would assert something we cannot currently verify, which
    is exactly what Last Success Time exists to answer instead.
    """
    mock_restore_cache(hass, (State(HEALTH, "on"),))
    await setup_integration()

    # No job has been polled yet, so the device is at its default of False.
    assert hass.states.get(HEALTH).state != STATE_UNKNOWN
    assert hass.states.get(HEALTH).state == "off"


async def test_last_success_is_unknown_on_a_fresh_install(
    hass: HomeAssistant, setup_integration
) -> None:
    """With nothing to restore, it reports unknown rather than a fake time."""
    enable_last_success(hass)
    await setup_integration()

    assert hass.states.get(LAST_SUCCESS).state == STATE_UNKNOWN


async def test_last_success_is_disabled_by_default(
    hass: HomeAssistant, setup_integration
) -> None:
    """It is history this integration keeps, and most users do not need it."""
    await setup_integration()

    entry = er.async_get(hass).async_get(LAST_SUCCESS)
    assert entry is not None
    assert entry.disabled_by is er.RegistryEntryDisabler.INTEGRATION
    assert hass.states.get(LAST_SUCCESS) is None


async def test_restore_never_clobbers_a_known_value(
    hass: HomeAssistant, setup_integration
) -> None:
    """Restoring is a fallback, not an override.

    Nothing in the current setup order can hand the entity a device that
    already has a value, but the guard is what keeps a stale stored value from
    overwriting a fresher one if that order ever changes.
    """
    entry = await setup_integration()
    coordinator = entry.runtime_data.coordinator
    device = next(
        d for d in coordinator.data.devices if d.name == "Last Success Time"
    )
    fresher = "2026-09-05T10:00:00+00:00"
    device.state = fresher

    entity = LastSuccessSensor(coordinator, device)

    async def _stored() -> SensorExtraStoredData:
        return SensorExtraStoredData(SUCCEEDED_AT, None)

    entity.async_get_last_sensor_data = _stored  # type: ignore[method-assign]
    await entity.async_restore_device_state()

    assert device.state == fresher
