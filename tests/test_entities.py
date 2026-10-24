"""Tests for entity naming and for the state that has to survive a restart."""

from contextlib import contextmanager
from datetime import UTC, datetime
from typing import Any
from unittest.mock import AsyncMock, patch

from pytest_homeassistant_custom_component.common import (
    MockConfigEntry,
    mock_restore_cache,
    mock_restore_cache_with_extra_data,
)

from custom_components.rclone.api import DeviceType
from custom_components.rclone.const import DOMAIN
from custom_components.rclone.sensor import LastSuccessSensor
from homeassistant.components.sensor import SensorExtraStoredData
from homeassistant.const import STATE_UNKNOWN
from homeassistant.core import HomeAssistant, State
from homeassistant.helpers import entity_registry as er

from .test_api_run_outcome import EXECUTE_ID, JOBID, LATER_END, NOT_FOUND, stats, status

LAST_SUCCESS = "sensor.bisync_last_success_time"
HEALTH = "binary_sensor.bisync_health"
JOB_SWITCH = "switch.bisync"

SUCCEEDED_AT = datetime(2026, 9, 3, 8, 20, 11, tzinfo=UTC)


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


async def test_unique_ids_are_unchanged(hass: HomeAssistant, setup_integration) -> None:
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


async def test_health_is_not_restored(hass: HomeAssistant, setup_integration) -> None:
    """Health deliberately has no restore behavior.

    It describes the run rclone last reported on. Replaying a stale Problem
    across a restart would assert something we cannot currently verify, which
    is exactly what Last Success Time exists to answer instead.
    """
    mock_restore_cache(hass, (State(HEALTH, "on"),))
    await setup_integration()

    # No run has been polled yet, so there is nothing to report -- neither the
    # stale Problem nor a made-up OK.
    assert hass.states.get(HEALTH).state == STATE_UNKNOWN


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
    device = next(d for d in coordinator.data.devices if d.name == "Last Success Time")
    fresher = "2026-09-05T10:00:00+00:00"
    device.state = fresher

    entity = LastSuccessSensor(coordinator, device)

    async def _stored() -> SensorExtraStoredData:
        return SensorExtraStoredData(SUCCEEDED_AT, None)

    entity.async_get_last_sensor_data = _stored  # type: ignore[method-assign]
    await entity.async_restore_device_state()

    assert device.state == fresher


def store_key(entry: MockConfigEntry) -> str:
    """Return the storage key the coordinator keeps its running job under."""
    return f"rclone.job.{entry.entry_id}"


def stored_job(jobid: int = JOBID) -> dict[str, Any]:
    """Build the store's on-disk form, as left by a run HA was still waiting on."""
    return {
        "version": 1,
        "minor_version": 1,
        "key": "",
        "data": {"jobid": jobid, "execute_id": EXECUTE_ID},
    }


@contextmanager
def rclone_reports(resp: dict[str, Any], statsresp: dict[str, Any] | None = None):
    """Answer job/status and core/stats with canned responses."""
    with (
        patch("custom_components.rclone.api.API.jobstatus_call", return_value=resp),
        patch(
            "custom_components.rclone.api.API.jobstats_call",
            return_value=statsresp or stats(),
        ),
    ):
        yield


class TestJobSurvivesRestart:
    """The job HA is waiting on is stored, so a restart resumes polling it.

    It used to live only in memory: a restart (or a reload from an options
    change) forgot it, and a run that was still going was never reported.
    """

    async def test_starting_a_job_stores_it(
        self, hass: HomeAssistant, setup_integration, hass_storage
    ) -> None:
        """The jobid and the rcd's executeId are saved as soon as rclone answers."""
        entry = await setup_integration()
        with (
            patch(
                "custom_components.rclone.api.API.async_job_call",
                AsyncMock(return_value=(JOBID, EXECUTE_ID)),
            ),
            rclone_reports(status(finished=False, execute_id=EXECUTE_ID)),
        ):
            await hass.services.async_call(
                "switch", "turn_on", {"entity_id": JOB_SWITCH}, blocking=True
            )
            await hass.async_block_till_done()

        assert hass.states.get(JOB_SWITCH).state == "on"
        assert hass_storage[store_key(entry)]["data"] == {
            "jobid": JOBID,
            "execute_id": EXECUTE_ID,
        }

    async def test_start_job_stores_it_without_waiting_for_a_refresh(
        self, hass: HomeAssistant, setup_integration, hass_storage
    ) -> None:
        """start_job saves the job itself, rather than leaving it to a poll.

        The switch also asks for a refresh, which saves it too, but that is
        debounced: right after another refresh it can wait several seconds, and
        a restart in that window would forget the job all over again.
        """
        entry = await setup_integration()
        with (
            patch(
                "custom_components.rclone.api.API.async_job_call",
                AsyncMock(return_value=(JOBID, EXECUTE_ID)),
            ),
            rclone_reports(status(finished=False, execute_id=EXECUTE_ID)),
        ):
            await entry.runtime_data.coordinator.start_job(DeviceType.JOB_SWITCH, 1)

        assert hass_storage[store_key(entry)]["data"] == {
            "jobid": JOBID,
            "execute_id": EXECUTE_ID,
        }

    async def test_finishing_a_job_clears_it(
        self, hass: HomeAssistant, setup_integration, config_entry, hass_storage
    ) -> None:
        """Nothing is left to resume once the run has been reported."""
        hass_storage[store_key(config_entry)] = stored_job()
        with rclone_reports(status(finished=False, execute_id=EXECUTE_ID)):
            entry = await setup_integration()
        assert store_key(entry) in hass_storage

        with rclone_reports(status(execute_id=EXECUTE_ID)):
            await entry.runtime_data.coordinator.async_refresh()
            await hass.async_block_till_done()

        assert hass.states.get(JOB_SWITCH).state == "off"
        assert store_key(entry) not in hass_storage

    async def test_a_running_job_is_resumed(
        self, hass: HomeAssistant, setup_integration, config_entry, hass_storage
    ) -> None:
        """After a restart the switch is on again and polling continues."""
        hass_storage[store_key(config_entry)] = stored_job()
        with rclone_reports(status(finished=False, execute_id=EXECUTE_ID)):
            entry = await setup_integration()

        assert hass.states.get(JOB_SWITCH).state == "on"
        parent = next(
            d for d in entry.runtime_data.coordinator.data.devices if d.rclonejobid
        )
        assert (parent.rclonejobid, parent.execute_id) == (JOBID, EXECUTE_ID)

    async def test_a_success_while_down_is_recorded(
        self, hass: HomeAssistant, setup_integration, config_entry, hass_storage
    ) -> None:
        """A run that succeeded while HA was down moves Last Success Time on.

        Before the job was stored, nothing ever reported that run: the jobid
        was gone, so the restored value from before the restart stuck.
        """
        restore_last_success(hass)
        hass_storage[store_key(config_entry)] = stored_job()
        with rclone_reports(status(end_time=LATER_END, execute_id=EXECUTE_ID)):
            await setup_integration()

        assert datetime.fromisoformat(
            hass.states.get(LAST_SUCCESS).state
        ) == datetime.fromisoformat(LATER_END).replace(microsecond=0)
        assert hass.states.get(HEALTH).state == "off"

    async def test_a_failure_while_down_keeps_the_restored_success(
        self, hass: HomeAssistant, setup_integration, config_entry, hass_storage
    ) -> None:
        """A run that failed while HA was down is a Problem, not a new success."""
        restore_last_success(hass)
        hass_storage[store_key(config_entry)] = stored_job()
        with rclone_reports(
            status(error="boom", execute_id=EXECUTE_ID), stats(errors=1)
        ):
            await setup_integration()

        assert hass.states.get(LAST_SUCCESS).state == SUCCEEDED_AT.isoformat()
        assert hass.states.get(HEALTH).state == "on"

    async def test_a_job_lost_while_down_ends_the_run(
        self, hass: HomeAssistant, setup_integration, config_entry, hass_storage
    ) -> None:
        """If the rcd restarted too, the run is reported lost, not left running."""
        hass_storage[store_key(config_entry)] = stored_job()
        with rclone_reports(NOT_FOUND):
            entry = await setup_integration()

        assert hass.states.get(JOB_SWITCH).state == "off"
        assert hass.states.get(HEALTH).state == "on"
        assert store_key(entry) not in hass_storage

    async def test_nothing_stored_means_nothing_polled(
        self, hass: HomeAssistant, setup_integration
    ) -> None:
        """A fresh install must not go asking rclone about job 0."""
        with patch(
            "custom_components.rclone.api.API.jobstatus_call",
            side_effect=AssertionError("polled with no job"),
        ):
            await setup_integration()

        assert hass.states.get(JOB_SWITCH).state == "off"

    async def test_removing_the_entry_removes_the_store(
        self, hass: HomeAssistant, setup_integration, config_entry, hass_storage
    ) -> None:
        """No stored job outlives its config entry."""
        hass_storage[store_key(config_entry)] = stored_job()
        with rclone_reports(status(finished=False, execute_id=EXECUTE_ID)):
            entry = await setup_integration()
            await hass.config_entries.async_remove(entry.entry_id)
            await hass.async_block_till_done()

        assert store_key(entry) not in hass_storage
