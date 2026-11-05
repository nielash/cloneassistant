"""Tests for the Dry Run, Resync and Resync Dry Run buttons."""

from datetime import datetime
from typing import Any
from unittest.mock import AsyncMock, patch

import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.rclone.const import BISYNC, CHECK, SYNC
from homeassistant.const import CONF_COMMAND
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import entity_registry as er

from .conftest import VERSION_INFO
from .test_api_run_outcome import EXECUTE_ID, JOBID, LATER_END, status
from .test_entities import (
    LAST_SUCCESS,
    SUCCEEDED_AT,
    rclone_reports,
    restore_last_success,
    store_key,
    stored_job,
)

DRY_RUN = "button.bisync_dry_run"
RESYNC = "button.bisync_resync"
RESYNC_DRY_RUN = "button.bisync_resync_dry_run"


def buttons(hass: HomeAssistant, entry: MockConfigEntry) -> set[str]:
    """Return the entity ids of the entry's registered buttons."""
    return {
        e.entity_id
        for e in er.async_entries_for_config_entry(er.async_get(hass), entry.entry_id)
        if e.domain == "button"
    }


async def press(hass: HomeAssistant, entity_id: str) -> None:
    """Press a button the way the UI or an automation does."""
    await hass.services.async_call(
        "button", "press", {"entity_id": entity_id}, blocking=True
    )
    await hass.async_block_till_done()


def job_call(jobid: int = JOBID) -> AsyncMock:
    """Stand in for the _async rc call that starts a job."""
    return AsyncMock(return_value=(jobid, EXECUTE_ID))


@pytest.mark.parametrize(
    ("rclone_command", "expected"),
    [
        pytest.param(BISYNC, {DRY_RUN, RESYNC, RESYNC_DRY_RUN}, id="bisync"),
        pytest.param(SYNC, {DRY_RUN}, id="sync"),
        # A command that only reads would do nothing different as a dry run.
        pytest.param(CHECK, set(), id="check"),
    ],
)
async def test_which_buttons_a_job_gets(
    hass: HomeAssistant, setup_integration, expected: set[str]
) -> None:
    """Resync is offered only for bisync, Dry Run only for what changes files."""
    entry = await setup_integration()
    assert buttons(hass, entry) == expected


@pytest.mark.parametrize("rclone_command", [BISYNC])
async def test_buttons_join_the_jobs_device(
    hass: HomeAssistant, setup_integration
) -> None:
    """The buttons sit on the same device as the job's switch."""
    await setup_integration()
    registry = er.async_get(hass)
    switch_device = registry.async_get("switch.bisync").device_id
    assert switch_device is not None
    for entity_id in (DRY_RUN, RESYNC, RESYNC_DRY_RUN):
        assert registry.async_get(entity_id).device_id == switch_device


@pytest.mark.parametrize("rclone_command", [BISYNC])
async def test_unique_ids(hass: HomeAssistant, setup_integration) -> None:
    """Pinned: changing a unique_id would orphan the entity and duplicate it."""
    await setup_integration()
    registry = er.async_get(hass)
    assert {
        registry.async_get(entity_id).unique_id
        for entity_id in (DRY_RUN, RESYNC, RESYNC_DRY_RUN)
    } == {
        "rclone-bisync_dry_run",
        "rclone-bisync_resync",
        "rclone-bisync_resync_dry_run",
    }


@pytest.mark.parametrize("rclone_command", [BISYNC])
async def test_changing_the_command_removes_buttons_it_does_not_use(
    hass: HomeAssistant, setup_integration
) -> None:
    """Switching a job from bisync to sync takes its Resync buttons away.

    Left in the registry, they would show as unavailable for good.
    """
    entry = await setup_integration()
    with (
        patch("custom_components.rclone.api.API.noopauth_call", return_value=True),
        patch("custom_components.rclone.api.API.version", return_value=VERSION_INFO),
    ):
        hass.config_entries.async_update_entry(
            entry, data={**entry.data, CONF_COMMAND: SYNC}
        )
        await hass.async_block_till_done()

    assert buttons(hass, entry) == {DRY_RUN}


@pytest.mark.parametrize(
    ("rclone_command", "entity_id", "payload", "stored"),
    [
        pytest.param(
            BISYNC,
            DRY_RUN,
            {"dryRun": True, "_config": {"DryRun": True}},
            {"dry_run_requested": True},
            id="bisync-dry-run",
        ),
        pytest.param(
            BISYNC,
            RESYNC,
            {"resync": True},
            {"resync_requested": True},
            id="bisync-resync",
        ),
        pytest.param(
            BISYNC,
            RESYNC_DRY_RUN,
            {"dryRun": True, "_config": {"DryRun": True}, "resync": True},
            {"dry_run_requested": True, "resync_requested": True},
            id="bisync-resync-dry-run",
        ),
        pytest.param(
            SYNC,
            DRY_RUN,
            {"_config": {"DryRun": True}},
            {"dry_run_requested": True},
            id="sync-dry-run",
        ),
    ],
)
async def test_pressing_starts_the_run_it_names(
    hass: HomeAssistant,
    setup_integration,
    hass_storage,
    rclone_command: str,
    entity_id: str,
    payload: dict[str, Any],
    stored: dict[str, Any],
) -> None:
    """The press reaches rclone, and what it asked for is stored with the job.

    Stored so that a dry run still going when HA restarts is not mistaken
    for a real run once it finishes.
    """
    entry = await setup_integration()
    call = job_call()
    with (
        patch("custom_components.rclone.api.API.async_job_call", call),
        rclone_reports(status(finished=False, execute_id=EXECUTE_ID)),
    ):
        await press(hass, entity_id)

    call.assert_awaited_once_with(rclone_command, payload)
    assert hass.states.get("switch.bisync").state == "on"
    assert hass_storage[store_key(entry)]["data"] == {
        "jobid": JOBID,
        "execute_id": EXECUTE_ID,
        **stored,
    }
    attributes = hass.states.get("switch.bisync").attributes
    for key in stored:
        assert attributes[key] is True


@pytest.mark.parametrize("rclone_command", [BISYNC])
async def test_pressing_while_a_run_is_going_is_refused(
    hass: HomeAssistant, setup_integration, config_entry, hass_storage
) -> None:
    """A second run would replace the jobid, so the first would go unreported."""
    hass_storage[store_key(config_entry)] = stored_job()
    with rclone_reports(status(finished=False, execute_id=EXECUTE_ID)):
        entry = await setup_integration()

    call = job_call(JOBID + 1)
    with (
        patch("custom_components.rclone.api.API.async_job_call", call),
        pytest.raises(HomeAssistantError) as err,
    ):
        await press(hass, RESYNC)

    assert err.value.translation_key == "job_running"
    call.assert_not_awaited()
    assert hass_storage[store_key(entry)]["data"] == stored_job()["data"]


async def test_a_dry_run_that_finished_while_down_is_not_a_success(
    hass: HomeAssistant, setup_integration, config_entry, hass_storage
) -> None:
    """The stored flag survives the restart, so Last Success Time holds."""
    restore_last_success(hass)
    job = stored_job()
    job["data"]["dry_run_requested"] = True
    hass_storage[store_key(config_entry)] = job
    with rclone_reports(status(end_time=LATER_END, execute_id=EXECUTE_ID)):
        await setup_integration()

    assert hass.states.get(LAST_SUCCESS).state == SUCCEEDED_AT.isoformat()
    assert datetime.fromisoformat(
        hass.states.get("sensor.bisync_last_end_time").state
    ) == datetime.fromisoformat(LATER_END).replace(microsecond=0)


@pytest.mark.parametrize("rclone_command", [BISYNC])
async def test_a_switch_start_records_nothing_asked_for(
    hass: HomeAssistant, setup_integration
) -> None:
    """A plain run leaves the flags unknown, not False.

    HA cannot tell that a run is not a dry run: the rcd may have been started
    with --dry-run, or command_args may ask for one.
    """
    entry = await setup_integration()
    with (
        patch("custom_components.rclone.api.API.async_job_call", job_call()),
        rclone_reports(status(finished=False, execute_id=EXECUTE_ID)),
    ):
        await hass.services.async_call(
            "switch", "turn_on", {"entity_id": "switch.bisync"}, blocking=True
        )
        await hass.async_block_till_done()

    coordinator = entry.runtime_data.coordinator
    parent = coordinator.api.get_parent(coordinator.data.devices)
    assert parent is not None
    assert parent.rclonejobid == JOBID
    assert parent.dry_run_requested is None
    assert parent.resync_requested is None
