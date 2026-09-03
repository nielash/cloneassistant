"""Tests for api.py that need no Home Assistant test harness.

api.py imports nothing from Home Assistant, so these run as plain sync tests.
"""

from typing import Any

import pytest

from custom_components.rclone.api import API, DeviceType


def make_api() -> API:
    """Build an API instance without touching the network."""
    return API(
        host="192.168.0.2:5572",
        user="test",
        pwd="1234",
        friendly_name="Bisync",
    )


# Written out rather than derived, so that a change to the defaults has to be
# made here too. "case A, B:" is a sequence pattern and silently matches no
# scalar DeviceType, which is how every one of these came to be 0.
EXPECTED_DEFAULTS = {
    DeviceType.JOB_SWITCH: False,
    DeviceType.HEALTH_SENSOR: False,
    DeviceType.DURATION_SENSOR: 0,
    DeviceType.ETA_SENSOR: 0,
    DeviceType.OTHER: 0,
    DeviceType.BYTES_SENSOR: None,
    DeviceType.TOTAL_BYTES_SENSOR: None,
    DeviceType.START_SENSOR: None,
    DeviceType.END_SENSOR: None,
    DeviceType.LAST_ERROR_SENSOR: None,
    DeviceType.SPEED_SENSOR: None,
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
