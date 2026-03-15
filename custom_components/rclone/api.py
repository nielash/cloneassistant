"""API Code.

Eventually it should be hosted on PYPI.
"""

from dataclasses import dataclass
from enum import StrEnum
import json
import logging
from typing import Any

import aiohttp
import requests

_LOGGER = logging.getLogger(__name__)


class DeviceType(StrEnum):
    """Device types."""

    JOB_SWITCH = "job_switch"
    BYTES_SENSOR = "bytes_sensor"
    HEALTH_SENSOR = "health_sensor"
    DURATION_SENSOR = "duration_sensor"
    START_SENSOR = "start_sensor"
    END_SENSOR = "end_sensor"

    CHECKS_SENSOR = "checks_sensor"
    TRANSFERS_SENSOR = "transfers_sensor"
    DELETEDDIRS_SENSOR = "deleteddirs_sensor"
    DELETES_SENSOR = "deletes_sensor"
    ERRORS_SENSOR = "errors_sensor"
    LISTED_SENSOR = "listed_sensor"
    RENAMES_SENSOR = "renames_sensor"
    SERVERSIDECOPIES_SENSOR = "serversidecopies_sensor"
    SERVERSIDEMOVES_SENSOR = "serversidemoves_sensor"
    TOTALCHECKS_SENSOR = "totalchecks_sensor"
    TOTALTRANSFERS_SENSOR = "totaltransfers_sensor"

    ETA_SENSOR = "eta_sensor"
    SPEED_SENSOR = "speed_sensor"
    LAST_ERROR_SENSOR = "last_error_sensor"
    TOTAL_BYTES_SENSOR = "total_bytes_sensor"

    OTHER = "other"


# DEVICES is kind of a misnomer, these really represent virtual entities like metrics.
# the IDs are generic defaults as we handle them dynamically elsewhere.
DEVICES: list[dict[str, int | str | DeviceType]] = [
    {"id": 1, "type": DeviceType.JOB_SWITCH, "rclonejobid": 0},
    {"id": 1, "type": DeviceType.BYTES_SENSOR, "rclonejobid": 0},
    {"id": 1, "type": DeviceType.HEALTH_SENSOR, "rclonejobid": 0},
    {"id": 1, "type": DeviceType.DURATION_SENSOR, "rclonejobid": 0},
    {"id": 1, "type": DeviceType.START_SENSOR, "rclonejobid": 0},
    {"id": 1, "type": DeviceType.END_SENSOR, "rclonejobid": 0},
    {"id": 1, "type": DeviceType.CHECKS_SENSOR, "rclonejobid": 0},
    {"id": 1, "type": DeviceType.TRANSFERS_SENSOR, "rclonejobid": 0},
    {"id": 1, "type": DeviceType.DELETEDDIRS_SENSOR, "rclonejobid": 0},
    {"id": 1, "type": DeviceType.DELETES_SENSOR, "rclonejobid": 0},
    {"id": 1, "type": DeviceType.ERRORS_SENSOR, "rclonejobid": 0},
    {"id": 1, "type": DeviceType.LISTED_SENSOR, "rclonejobid": 0},
    {"id": 1, "type": DeviceType.RENAMES_SENSOR, "rclonejobid": 0},
    {"id": 1, "type": DeviceType.SERVERSIDECOPIES_SENSOR, "rclonejobid": 0},
    {"id": 1, "type": DeviceType.SERVERSIDEMOVES_SENSOR, "rclonejobid": 0},
    {"id": 1, "type": DeviceType.TOTALCHECKS_SENSOR, "rclonejobid": 0},
    {"id": 1, "type": DeviceType.TOTALTRANSFERS_SENSOR, "rclonejobid": 0},
    {"id": 1, "type": DeviceType.ETA_SENSOR, "rclonejobid": 0},
    {"id": 1, "type": DeviceType.SPEED_SENSOR, "rclonejobid": 0},
    {"id": 1, "type": DeviceType.LAST_ERROR_SENSOR, "rclonejobid": 0},
    {"id": 1, "type": DeviceType.TOTAL_BYTES_SENSOR, "rclonejobid": 0},
]

counters = {
    DeviceType.CHECKS_SENSOR: "checks",
    DeviceType.TRANSFERS_SENSOR: "transfers",
    DeviceType.DELETEDDIRS_SENSOR: "deletedDirs",
    DeviceType.DELETES_SENSOR: "deletes",
    DeviceType.ERRORS_SENSOR: "errors",
    DeviceType.LISTED_SENSOR: "listed",
    DeviceType.RENAMES_SENSOR: "renames",
    DeviceType.SERVERSIDECOPIES_SENSOR: "serverSideCopies",
    DeviceType.SERVERSIDEMOVES_SENSOR: "serverSideMoves",
    DeviceType.TOTALCHECKS_SENSOR: "totalChecks",
    DeviceType.TOTALTRANSFERS_SENSOR: "totalTransfers",
}


@dataclass
class Device:
    """API device."""

    device_id: int
    device_unique_id: str
    device_type: DeviceType
    name: str
    parent_name: str
    state: int | float | bool | None
    rclonejobid: int
    atts: dict[str, Any] | None = None


class API:
    """Class for API."""

    def __init__(self, host: str, user: str, pwd: str, friendly_name: str) -> None:
        """Initialise."""
        self.host = host
        self.user = user
        self.pwd = pwd
        self.friendly_name = friendly_name
        self.unfriendly_name = friendly_name.replace(" ", "_").lower()
        self.connected: bool = False
        self.version_info: dict[str, Any]

    @property
    def controller_name(self) -> str:
        """Return the name of the controller."""
        return self.friendly_name.replace(" ", "_")

    def connect(self) -> bool:
        """Connect to api."""
        if self.noopauth_call():
            self.connected = True
            self.version_info = self.version()
            return True
        raise APIAuthError(
            "Error connecting to api. Invalid host, username, or password."
        )

    def disconnect(self) -> bool:
        """Disconnect from api."""
        self.connected = False
        return True

    def get_devices(self) -> list[Device]:
        """Get devices in default state."""
        return [
            Device(
                device_id=int(device.get("id", 0)),
                device_unique_id=self.get_device_unique_id(
                    str(device.get("id")), DeviceType(str(device.get("type")))
                ),
                device_type=DeviceType(str(device.get("type"))),
                name=self.get_device_name(
                    str(device.get("id")), DeviceType(str(device.get("type")))
                ),
                state=self.get_device_default_value(
                    str(device.get("id")), DeviceType(str(device.get("type")))
                ),
                parent_name=self.unfriendly_name,
                rclonejobid=int(device.get("rclonejobid", 0)),
            )
            for device in DEVICES
        ]

    def get_jobstatus(self, devices: list[Device]) -> list[Device]:
        """Get devices on api."""
        parent = self.get_parent(devices)
        if not parent or parent.rclonejobid == 0:
            return devices
        resp = self.jobstatus_call(parent.rclonejobid)

        if resp["error"] == "job not found":
            raise self.handle_job_not_found(devices)

        statsresp = self.jobstats_call(parent.rclonejobid)
        for device in devices:
            match device.device_type:
                case DeviceType.JOB_SWITCH:
                    device.state = not resp["finished"]
                    device.atts = {
                        "jobid": parent.rclonejobid,
                        "output": str(resp["output"])[
                            -1000:
                        ],  # include only the last 10000 characters of output,
                    }
                case DeviceType.HEALTH_SENSOR:
                    device.state = resp["error"] != ""
                case DeviceType.BYTES_SENSOR:
                    device.state = statsresp["bytes"]
                case DeviceType.DURATION_SENSOR:
                    device.state = resp["duration"]
                    if device.state in [0, "null", None]:
                        device.state = statsresp["elapsedTime"]
                case DeviceType.START_SENSOR:
                    device.state = resp[
                        "startTime"
                    ]  # we'll convert this to a datetime in the sensor
                case DeviceType.END_SENSOR:
                    if resp["finished"]:
                        device.state = resp[
                            "endTime"
                        ]  # we'll convert this to a datetime in the sensor
                case (
                    DeviceType.CHECKS_SENSOR
                    | DeviceType.TRANSFERS_SENSOR
                    | DeviceType.DELETEDDIRS_SENSOR
                    | DeviceType.DELETES_SENSOR
                    | DeviceType.ERRORS_SENSOR
                    | DeviceType.LISTED_SENSOR
                    | DeviceType.RENAMES_SENSOR
                    | DeviceType.SERVERSIDECOPIES_SENSOR
                    | DeviceType.SERVERSIDEMOVES_SENSOR
                    | DeviceType.TOTALCHECKS_SENSOR
                    | DeviceType.TOTALTRANSFERS_SENSOR
                ):
                    device.state = statsresp[counters[device.device_type]]
                case DeviceType.ETA_SENSOR:
                    device.state = statsresp["eta"]
                    if device.state in [0, "null", None]:
                        device.state = None
                case DeviceType.SPEED_SENSOR:
                    device.state = statsresp["speed"]
                case DeviceType.LAST_ERROR_SENSOR:
                    self.last_error_state(device, resp, statsresp)
                case DeviceType.TOTAL_BYTES_SENSOR:
                    device.state = statsresp["totalBytes"]

            if resp["finished"]:
                # clear jobid when job is finished
                device.rclonejobid = 0

        return devices

    def handle_job_not_found(self, devices) -> Exception:
        """Handle the case where we know the jobid but can't determine its status."""
        self.connected = False
        for device in devices:
            device.rclonejobid = 0
            if device.device_type == DeviceType.HEALTH_SENSOR:
                device.state = True
            if device.device_type == DeviceType.LAST_ERROR_SENSOR:
                device.state = "job not found"
        return APIConnectionError("job not found")

    def last_error_state(self, device, resp, statsresp) -> str | None:
        """Determine the state of the last error sensor."""
        if "lastError" in statsresp:
            device.state = statsresp["lastError"][:250]
        elif resp["error"] != "":
            device.state = resp["error"][:250]
        else:
            device.state = None
        return device.state

    def get_parent(self, devices: list[Device]) -> Device | None:
        """Return the parent device (JOB_SWITCH) from the list of devices."""
        for device in devices:
            if device.device_type == DeviceType.JOB_SWITCH:
                return device
        return None

    def get_device_unique_id(self, device_id: str, device_type: DeviceType) -> str:
        """Return a unique device id."""
        return f"{self.unfriendly_name}_{self.get_device_name(device_id, device_type)}"

    def get_device_name(self, device_id: str, device_type: DeviceType) -> str:
        """Return the device name."""
        match device_type:
            case DeviceType.JOB_SWITCH:
                return self.controller_name.replace("_", " ").title()
            case DeviceType.HEALTH_SENSOR:
                return "Health"
            case DeviceType.BYTES_SENSOR:
                return "Bytes"
            case DeviceType.DURATION_SENSOR:
                return "Duration"
            case DeviceType.START_SENSOR:
                return "Last Start Time"
            case DeviceType.END_SENSOR:
                return "Last End Time"
            case DeviceType.CHECKS_SENSOR:
                return "Checks"
            case DeviceType.TRANSFERS_SENSOR:
                return "Transfers"
            case DeviceType.DELETEDDIRS_SENSOR:
                return "Deleted Dirs"
            case DeviceType.DELETES_SENSOR:
                return "Deletes"
            case DeviceType.ERRORS_SENSOR:
                return "Errors"
            case DeviceType.LISTED_SENSOR:
                return "Listed"
            case DeviceType.RENAMES_SENSOR:
                return "Renames"
            case DeviceType.SERVERSIDECOPIES_SENSOR:
                return "ServerSide Copies"
            case DeviceType.SERVERSIDEMOVES_SENSOR:
                return "ServerSide Moves"
            case DeviceType.TOTALCHECKS_SENSOR:
                return "Total Checks"
            case DeviceType.TOTALTRANSFERS_SENSOR:
                return "Total Transfers"
            case DeviceType.ETA_SENSOR:
                return "ETA"
            case DeviceType.SPEED_SENSOR:
                return "Speed"
            case DeviceType.LAST_ERROR_SENSOR:
                return "Last Error"
            case DeviceType.TOTAL_BYTES_SENSOR:
                return "Total Bytes"
            case _:
                return f"OtherSensor{device_id}"

    def get_device_default_value(
        self, device_id: str, device_type: DeviceType
    ) -> int | bool:
        """Get device's default value."""
        match device_type:
            case DeviceType.JOB_SWITCH:
                return False
            case DeviceType.HEALTH_SENSOR:
                return False
            case DeviceType.BYTES_SENSOR, DeviceType.TOTAL_BYTES_SENSOR:
                return None
            case DeviceType.DURATION_SENSOR, DeviceType.ETA_SENSOR:
                return 0
            case (
                DeviceType.START_SENSOR,
                DeviceType.END_SENSOR,
                DeviceType.LAST_ERROR_SENSOR,
                DeviceType.SPEED_SENSOR,
            ):
                return None
            case (
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
            ):
                return None
            case _:
                return 0

    async def async_job_call(self, method: str, payload: dict[str, Any]) -> int:
        """Make an asynchronous API call to rclone and return the job ID."""
        payload["_async"] = True
        url = f"http://{self.user}:{self.pwd}@{self.host}/{method}"
        self.connected = True  # if we can make a successful call, we are connected. If not, an exception will be raised.
        try:
            async with (
                aiohttp.ClientSession(
                    timeout=aiohttp.ClientTimeout(total=10), raise_for_status=True
                ) as session,
                session.post(url, json=payload) as response,
            ):
                _LOGGER.debug("Status: %s", response.status)
                response_json = await response.json()
                _LOGGER.info(response_json)
                return response_json["jobid"]
        except Exception as err:
            self.connected = False
            raise APIConnectionError("Error connecting to API.") from err
        return 0

    async def async_stop_job_call(self, job_id: int):
        """Make an asynchronous API call to attempt to stop an rclone job."""
        method = "job/stop"
        payload = {
            "jobid": job_id,
        }
        if job_id in [0, None]:
            _LOGGER.warning("No job to stop for jobid %s", job_id)
            return 0
        _LOGGER.debug(payload)
        url = f"http://{self.user}:{self.pwd}@{self.host}/{method}"
        async with (
            aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=10)) as session,
            session.post(url, json=payload) as response,
        ):
            _LOGGER.info("Status: %s", response.status)
            response_json = await response.json()
            _LOGGER.info(json.dumps(response_json, indent=4))
            return response_json

    def jobstatus_call(self, jobid: int) -> dict[str, Any]:
        """Get job status from API."""
        method = "job/status"
        payload = {
            "jobid": jobid,
        }
        url = f"http://{self.user}:{self.pwd}@{self.host}/{method}"

        resp = requests.post(url, json=payload, auth=(self.user, self.pwd), timeout=10)
        response_json = resp.json()
        _LOGGER.info(json.dumps(response_json, indent=4))
        return response_json

    def jobstats_call(self, jobid: int) -> dict[str, Any]:
        """Get job statistics from API."""
        method = "core/stats"
        payload = {
            "group": f"job/{jobid}",
        }
        url = f"http://{self.user}:{self.pwd}@{self.host}/{method}"

        resp = requests.post(url, json=payload, auth=(self.user, self.pwd), timeout=10)
        response_json = resp.json()
        _LOGGER.info(json.dumps(response_json, indent=4))
        return response_json

    def noopauth_call(self) -> bool:
        """Perform authentication check with API."""
        method = "rc/noopauth"
        payload = {
            "hello": "world",
        }
        url = f"http://{self.user}:{self.pwd}@{self.host}/{method}"

        resp = requests.post(url, json=payload, auth=(self.user, self.pwd), timeout=10)
        response_json = resp.json()
        _LOGGER.debug(json.dumps(response_json, indent=4))
        return response_json["hello"] == "world"

    def version(self) -> dict[str, Any]:
        """Retrieve rclone version info."""
        method = "core/version"
        payload: dict[str, str] = {}
        url = f"http://{self.user}:{self.pwd}@{self.host}/{method}"

        resp = requests.post(url, json=payload, auth=(self.user, self.pwd), timeout=10)
        response_json = resp.json()
        _LOGGER.debug(json.dumps(response_json, indent=4))
        return response_json


class APIAuthError(Exception):
    """Exception class for auth error."""


class APIConnectionError(Exception):
    """Exception class for connection error."""
