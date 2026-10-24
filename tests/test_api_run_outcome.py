"""Tests for how a finished run is judged, and what that drives.

These exercise api.py directly: it holds all of the success/failure logic and
imports nothing from Home Assistant, so no test harness is needed here.
"""

from typing import Any

import pytest

from custom_components.rclone.api import API, Device, DeviceType

JOBID = 7
EXECUTE_ID = "6f1c0f5e-3a38-4a40-9d0b-7c3d1f0e2a11"
CLEAN_END = "2026-09-03T04:20:11.123456-04:00"
LATER_END = "2026-09-04T04:20:11.123456-04:00"


def make_api(count_errors_as_failure: bool = False) -> API:
    """Build an API instance without touching the network."""
    return API(
        host="192.168.0.2:5572",
        user="test",
        pwd="1234",
        friendly_name="Bisync",
        count_errors_as_failure=count_errors_as_failure,
    )


def status(
    finished: bool = True,
    error: str = "",
    end_time: str = CLEAN_END,
    execute_id: str | None = None,
) -> dict[str, Any]:
    """Build a job/status response.

    ``executeId`` is left out unless given, as from rclone versions before it.
    """
    resp: dict[str, Any] = {
        "duration": 12.5,
        "endTime": end_time if finished else "0001-01-01T00:00:00Z",
        "error": error,
        "finished": finished,
        "group": f"job/{JOBID}",
        "id": JOBID,
        "output": {},
        "startTime": "2026-09-03T04:19:58.000000-04:00",
        "success": finished and error == "",
    }
    if execute_id is not None:
        resp["executeId"] = execute_id
    return resp


def stats(errors: int = 0, **overrides: Any) -> dict[str, Any]:
    """Build a core/stats response.

    rclone only includes ``lastError`` when there has been one, so it is added
    only alongside a nonzero error count -- last_error_state keys off presence.
    """
    resp: dict[str, Any] = {
        "bytes": 1024,
        "checks": 3,
        "deletedDirs": 0,
        "deletes": 0,
        "elapsedTime": 12.5,
        "errors": errors,
        "eta": 0,
        "listed": 9,
        "renames": 0,
        "serverSideCopies": 0,
        "serverSideMoves": 0,
        "speed": 512.0,
        "totalBytes": 1024,
        "totalChecks": 3,
        "totalTransfers": 1,
        "transfers": 1,
    }
    if errors:
        resp["lastError"] = "directory not found"
    resp.update(overrides)
    return resp


def poll(api: API, devices: list[Device], resp, statsresp) -> list[Device]:
    """Run one coordinator poll against canned rclone responses."""
    api.jobstatus_call = lambda jobid: resp  # type: ignore[method-assign]
    api.jobstats_call = lambda jobid: statsresp  # type: ignore[method-assign]
    return api.get_jobstatus(devices)


def start(
    devices: list[Device], jobid: int = JOBID, execute_id: str | None = None
) -> list[Device]:
    """Attach a job id the way coordinator.start_job does -- parent only."""
    for device in devices:
        if device.device_type == DeviceType.JOB_SWITCH:
            device.rclonejobid = jobid
            device.execute_id = execute_id
    return devices


def state_of(devices: list[Device], device_type: DeviceType) -> Any:
    """Return the state of a single device type."""
    return next(d for d in devices if d.device_type == device_type).state


@pytest.fixture(name="devices")
def devices_fixture() -> list[Device]:
    """Return a fresh set of devices with a job in flight."""
    return start(make_api().get_devices())


def test_last_success_starts_unknown() -> None:
    """A fresh install has seen no runs, so it cannot know the last success."""
    devices = make_api().get_devices()
    assert state_of(devices, DeviceType.LAST_SUCCESS_SENSOR) is None


class TestHealthUnchanged:
    """Health still reports job/status error, and only that."""

    def test_stays_ok_while_running_despite_errors(self, devices) -> None:
        """A run with errors in flight is not yet a Problem."""
        poll(make_api(), devices, status(finished=False), stats(errors=4))
        assert state_of(devices, DeviceType.HEALTH_SENSOR) is False

    def test_problem_once_a_run_ends_badly(self, devices) -> None:
        """A completed run with an error is a Problem."""
        poll(make_api(), devices, status(error="boom"), stats(errors=1))
        assert state_of(devices, DeviceType.HEALTH_SENSOR) is True

    def test_ignores_the_nonfatal_errors_option(self, devices) -> None:
        """The new option must not change what Health reports.

        It redefines failure for Last Success Time only -- Health keeps
        agreeing with rclone so existing automations that watch it behave
        exactly as before.
        """
        result = poll(
            make_api(count_errors_as_failure=True), devices, status(), stats(errors=4)
        )
        assert state_of(result, DeviceType.HEALTH_SENSOR) is False
        # ...even though the same run was counted as a failure elsewhere.
        assert state_of(result, DeviceType.LAST_SUCCESS_SENSOR) is None


class TestLastSuccessTime:
    """Last Success Time only ever moves forward on a clean completion."""

    def test_not_set_while_running(self, devices) -> None:
        """An in-flight run has no outcome yet."""
        poll(make_api(), devices, status(finished=False), stats())
        assert state_of(devices, DeviceType.LAST_SUCCESS_SENSOR) is None

    def test_set_on_clean_completion(self, devices) -> None:
        """A clean completion records rclone's own endTime, verbatim."""
        poll(make_api(), devices, status(), stats())
        assert state_of(devices, DeviceType.LAST_SUCCESS_SENSOR) == CLEAN_END

    def test_not_set_on_failed_completion(self, devices) -> None:
        """A failed run leaves it alone, unlike Last End Time."""
        poll(make_api(), devices, status(error="boom"), stats(errors=1))
        assert state_of(devices, DeviceType.LAST_SUCCESS_SENSOR) is None
        assert state_of(devices, DeviceType.END_SENSOR) == CLEAN_END

    def test_survives_a_later_failure(self, devices) -> None:
        """The point of the sensor: it keeps pointing at the good run."""
        api = make_api()
        poll(api, devices, status(end_time=CLEAN_END), stats())
        poll(
            api,
            start(devices),
            status(error="boom", end_time=LATER_END),
            stats(errors=1),
        )
        assert state_of(devices, DeviceType.LAST_SUCCESS_SENSOR) == CLEAN_END
        assert state_of(devices, DeviceType.END_SENSOR) == LATER_END


class TestNonfatalErrorsOption:
    """The option flips a clean-exit run with errors into a failure."""

    RESP = status()
    STATS = stats(errors=4)

    def test_off_by_default_run_counts_as_success(self, devices) -> None:
        """Rclone exited 0, so by default the run succeeded."""
        result = poll(make_api(), devices, self.RESP, self.STATS)
        assert state_of(result, DeviceType.LAST_SUCCESS_SENSOR) == CLEAN_END

    def test_on_run_counts_as_failure(self, devices) -> None:
        """With the option on, the same run is held to a stricter standard."""
        result = poll(
            make_api(count_errors_as_failure=True), devices, self.RESP, self.STATS
        )
        assert state_of(result, DeviceType.LAST_SUCCESS_SENSOR) is None

    def test_on_a_genuinely_clean_run_still_succeeds(self, devices) -> None:
        """The option must not make every run look like a failure."""
        result = poll(
            make_api(count_errors_as_failure=True), devices, self.RESP, stats()
        )
        assert state_of(result, DeviceType.LAST_SUCCESS_SENSOR) == CLEAN_END


NOT_FOUND = {"error": "job not found"}


class TestJobLost:
    """A job rclone can no longer report on ends the run, as a failure.

    Two ways in: rclone answers "job not found" (the rcd restarted, or the job
    expired before we polled it), or the jobid now belongs to a different rcd.
    """

    def test_not_found_counts_as_a_failure(self, devices) -> None:
        """We cannot get a verdict, so we assume the worst but keep the good one."""
        api = make_api()
        poll(api, devices, status(), stats())  # a good run first
        poll(api, start(devices), NOT_FOUND, stats())
        assert state_of(devices, DeviceType.HEALTH_SENSOR) is True
        assert state_of(devices, DeviceType.LAST_SUCCESS_SENSOR) == CLEAN_END
        assert "job not found" in state_of(devices, DeviceType.LAST_ERROR_SENSOR)

    def test_not_found_turns_the_switch_off(self, devices) -> None:
        """The switch used to stay on forever, claiming a dead job was running."""
        api = make_api()
        poll(api, devices, status(finished=False), stats())
        assert state_of(devices, DeviceType.JOB_SWITCH) is True
        poll(api, devices, NOT_FOUND, stats())
        assert state_of(devices, DeviceType.JOB_SWITCH) is False

    def test_not_found_is_only_processed_once(self, devices) -> None:
        """Like a finished run, a lost one clears the jobid and is not re-polled."""
        api = make_api()
        poll(api, devices, NOT_FOUND, stats())
        assert all(d.rclonejobid == 0 and d.execute_id is None for d in devices)
        assert polls_after_the_run_ended(api, devices) == []

    def test_jobid_from_another_rcd_is_not_a_success(self, devices) -> None:
        """A restarted rcd reuses low jobids; that finished job is not ours."""
        api = make_api()
        start(devices, execute_id=EXECUTE_ID)
        poll(api, devices, status(execute_id="a-later-rcd"), stats())
        assert state_of(devices, DeviceType.JOB_SWITCH) is False
        assert state_of(devices, DeviceType.HEALTH_SENSOR) is True
        assert state_of(devices, DeviceType.LAST_SUCCESS_SENSOR) is None
        assert state_of(devices, DeviceType.LAST_ERROR_SENSOR) == (
            "job lost: rclone restarted"
        )

    def test_matching_execute_id_is_processed_normally(self, devices) -> None:
        """The check must not reject our own job."""
        start(devices, execute_id=EXECUTE_ID)
        poll(make_api(), devices, status(execute_id=EXECUTE_ID), stats())
        assert state_of(devices, DeviceType.LAST_SUCCESS_SENSOR) == CLEAN_END

    def test_rclone_without_execute_id_is_trusted(self, devices) -> None:
        """Older rclone versions report no executeId; fall back to the jobid."""
        start(devices, execute_id=EXECUTE_ID)
        poll(make_api(), devices, status(), stats())
        assert state_of(devices, DeviceType.LAST_SUCCESS_SENSOR) == CLEAN_END

    def test_finishing_clears_the_execute_id(self, devices) -> None:
        """A finished run leaves nothing behind for the store to resume."""
        start(devices, execute_id=EXECUTE_ID)
        poll(make_api(), devices, status(execute_id=EXECUTE_ID), stats())
        assert all(d.rclonejobid == 0 and d.execute_id is None for d in devices)


def polls_after_the_run_ended(api: API, devices: list[Device]) -> list[int]:
    """Poll three more times and return the jobids rclone was asked about.

    The canned answer is a failure, so a poll that slipped through would also
    show up as Health flipping to Problem.
    """
    asked: list[int] = []

    def jobstatus(jobid: int) -> dict[str, Any]:
        asked.append(jobid)
        return status(error="boom", end_time=LATER_END)

    api.jobstatus_call = jobstatus  # type: ignore[method-assign]
    api.jobstats_call = lambda jobid: stats(errors=1)  # type: ignore[method-assign]
    for _ in range(3):
        api.get_jobstatus(devices)
    return asked


def test_completion_is_only_processed_once(devices) -> None:
    """Polling after a run has finished must not ask rclone about it again.

    get_jobstatus clears the job id on the finished transition and returns
    early thereafter. If that ever stopped holding, each scan interval would
    redo the run's bookkeeping -- and, since a restarted rcd reuses jobids, a
    later unrelated call could overwrite the verdict.
    """
    api = make_api()
    poll(api, devices, status(), stats())
    assert polls_after_the_run_ended(api, devices) == []
    assert state_of(devices, DeviceType.HEALTH_SENSOR) is False
    assert state_of(devices, DeviceType.LAST_SUCCESS_SENSOR) == CLEAN_END


# Written out rather than derived, so that a change to the defaults has to be
# made here too. "case A, B:" is a sequence pattern and silently matches no
# scalar DeviceType, which is how every one of these came to be 0.
EXPECTED_DEFAULTS = {
    DeviceType.JOB_SWITCH: False,
    DeviceType.HEALTH_SENSOR: None,
    DeviceType.DURATION_SENSOR: 0,
    DeviceType.ETA_SENSOR: 0,
    DeviceType.OTHER: 0,
    DeviceType.BYTES_SENSOR: None,
    DeviceType.TOTAL_BYTES_SENSOR: None,
    DeviceType.START_SENSOR: None,
    DeviceType.END_SENSOR: None,
    DeviceType.LAST_ERROR_SENSOR: None,
    DeviceType.SPEED_SENSOR: None,
    DeviceType.LAST_SUCCESS_SENSOR: None,
    DeviceType.CHECKS_SENSOR: None,
    DeviceType.TRANSFERS_SENSOR: None,
    DeviceType.DELETEDDIRS_SENSOR: None,
    DeviceType.DELETES_SENSOR: None,
    DeviceType.ERRORS_SENSOR: None,
    DeviceType.LISTED_SENSOR: None,
    DeviceType.RENAMES_SENSOR: None,
    DeviceType.SERVERSIDECOPIES_SENSOR: None,
    DeviceType.SERVERSIDEMOVES_SENSOR: None,
    DeviceType.TOTALCHECKS_SENSOR: None,
    DeviceType.TOTALTRANSFERS_SENSOR: None,
}


def test_every_device_type_has_an_expected_default() -> None:
    """Guards against a new DeviceType quietly defaulting to 0."""
    assert set(EXPECTED_DEFAULTS) == set(DeviceType)


@pytest.mark.parametrize(("device_type", "expected"), EXPECTED_DEFAULTS.items())
def test_default_values(device_type: DeviceType, expected: Any) -> None:
    """A sensor reports unknown until a run has given it a value."""
    default = make_api().get_device_default_value("1", device_type)
    assert default is expected if expected is None else default == expected
