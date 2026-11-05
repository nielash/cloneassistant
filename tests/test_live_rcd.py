"""End-to-end tests of the buttons against a real rclone rcd.

Skipped unless RCLONE_LIVE_BINS names one or more rclone binaries, separated
by the OS path separator (":" on macOS and Linux, ";" on Windows). Each test
runs once per binary, against a throwaway rcd that uses its own empty config,
cache and temp dirs, on a free localhost port:

    RCLONE_LIVE_BINS=/path/to/rclone-v1.75.2:/path/to/rclone-beta pytest tests/test_live_rcd.py

Worth running against a released rclone and a current beta: every release
through v1.75.2 ignores _config's DryRun for bisync and runs it for real, which
is why a bisync dry run also sends bisync's own dryRun.
"""

import asyncio
from collections.abc import Iterator
import json
import os
from pathlib import Path
import socket
import subprocess
import time
from typing import Any

import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry
import requests

from custom_components.rclone.const import BISYNC, COMMAND_ARGS, DOMAIN, SYNC
from homeassistant.const import (
    CONF_COMMAND,
    CONF_FRIENDLY_NAME,
    CONF_HOST,
    CONF_PASSWORD,
    CONF_SCAN_INTERVAL,
    CONF_USERNAME,
)
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import entity_registry as er

BINS = [b for b in os.environ.get("RCLONE_LIVE_BINS", "").split(os.pathsep) if b]
USER, PASSWORD = "u", "p"

pytestmark = pytest.mark.skipif(not BINS, reason="RCLONE_LIVE_BINS is not set")


class Rcd:
    """A throwaway rcd, and direct rc calls to it outside the integration."""

    def __init__(self, binary: str, root: Path) -> None:
        """Start the rcd and wait (bounded) until it answers."""
        self.root = root
        with socket.socket() as sock:
            sock.bind(("127.0.0.1", 0))
            self.port = sock.getsockname()[1]
        (root / "rclone.conf").touch()
        self.log = root / "rcd.log"
        self.proc = subprocess.Popen(
            [
                binary,
                "rcd",
                f"--rc-addr=127.0.0.1:{self.port}",
                f"--rc-user={USER}",
                f"--rc-pass={PASSWORD}",
                f"--config={root / 'rclone.conf'}",
                f"--cache-dir={root / 'cache'}",
                "--rc-job-expire-duration=1h",
                "-v",
                f"--log-file={self.log}",
            ]
        )
        deadline = time.monotonic() + 15
        while True:
            try:
                self.version = self.call("core/version")["version"]
                break
            except requests.ConnectionError:
                if time.monotonic() > deadline or self.proc.poll() is not None:
                    self.stop()
                    raise RuntimeError(f"rcd did not start; see {self.log}") from None
                time.sleep(0.2)

    def call(self, method: str, **params: Any) -> dict[str, Any]:
        """Make an rc call."""
        return requests.post(
            f"http://127.0.0.1:{self.port}/{method}",
            auth=(USER, PASSWORD),
            json=params,
            timeout=60,
        ).json()

    def files(self, fs: str) -> list[str]:
        """List a remote's files."""
        return sorted(
            e["Path"] for e in self.call("operations/list", fs=fs, remote="")["list"]
        )

    def stop(self) -> None:
        """Stop the rcd."""
        self.proc.terminate()
        self.proc.wait(timeout=10)


@pytest.fixture(name="rcd", params=BINS, ids=lambda b: Path(b).parent.name or b)
def rcd_fixture(request, tmp_path: Path, socket_enabled) -> Iterator[Rcd]:
    """Run a throwaway rcd from one of RCLONE_LIVE_BINS."""
    rcd = Rcd(request.param, tmp_path)
    try:
        yield rcd
    finally:
        rcd.stop()


async def add_job(
    hass: HomeAssistant, rcd: Rcd, title: str, command: str, args: dict[str, Any]
) -> MockConfigEntry:
    """Set up a job against the rcd, with Last Success Time enabled."""
    slug = title.lower()
    er.async_get(hass).async_get_or_create(
        "sensor",
        DOMAIN,
        f"rclone-{slug}_Last Success Time",
        suggested_object_id=f"{slug}_last_success_time",
    )
    entry = MockConfigEntry(
        domain=DOMAIN,
        title=title,
        unique_id=title,
        data={
            CONF_FRIENDLY_NAME: title,
            CONF_HOST: f"127.0.0.1:{rcd.port}",
            CONF_USERNAME: USER,
            CONF_PASSWORD: PASSWORD,
            # The tests poll for themselves.
            CONF_SCAN_INTERVAL: 3600,
            CONF_COMMAND: command,
            COMMAND_ARGS: json.dumps(args),
        },
    )
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    return entry


async def wait_until_done(hass: HomeAssistant, entry: MockConfigEntry) -> None:
    """Poll the way the coordinator does until the run is over (at most 30s)."""
    coordinator = entry.runtime_data.coordinator
    for _ in range(120):
        await coordinator.async_refresh()
        await hass.async_block_till_done()
        if not coordinator.job_running():
            return
        await asyncio.sleep(0.25)
    raise AssertionError("the run was still going after 30s")


async def press(hass: HomeAssistant, entity_id: str) -> None:
    """Press a button."""
    await hass.services.async_call(
        "button", "press", {"entity_id": entity_id}, blocking=True
    )


async def switch(hass: HomeAssistant, service: str, entity_id: str) -> None:
    """Turn a job's switch on or off."""
    await hass.services.async_call(
        "switch", service, {"entity_id": entity_id}, blocking=True
    )


def state(hass: HomeAssistant, entity_id: str) -> str:
    """Return an entity's state."""
    return hass.states.get(entity_id).state


def attributes(hass: HomeAssistant, entity_id: str) -> dict[str, Any]:
    """Return an entity's attributes."""
    return dict(hass.states.get(entity_id).attributes)


def real_listings(workdir: Path) -> dict[str, str]:
    """Return bisync's real listings, leaving out its dry-run ones."""
    return {p.name: p.read_text() for p in sorted(workdir.glob("*.lst"))}


async def test_bisync_buttons(
    hass: HomeAssistant, enable_custom_integrations: None, rcd: Rcd
) -> None:
    """Resync Dry Run, Resync, Dry Run, then a plain run, in that order."""
    path1, workdir = rcd.root / "path1", rcd.root / "work"
    # A memory Path2 keeps bisync's session name, built from both paths, under
    # the 255-byte file name limit however deep tmp_path is.
    path2 = ":memory:path2"
    path1.mkdir()
    workdir.mkdir()
    for name in ("a.txt", "b.txt"):
        (path1 / name).write_text(name * 100)
    rcd.call("operations/mkdir", fs=path2, remote="")
    entry = await add_job(
        hass,
        rcd,
        "Bisync",
        BISYNC,
        {"path1": str(path1), "path2": path2, "workdir": str(workdir)},
    )
    assert set(hass.states.async_entity_ids("button")) == {
        "button.bisync_dry_run",
        "button.bisync_resync",
        "button.bisync_resync_dry_run",
    }

    # Resync Dry Run: nothing is copied and no real listing is written.
    await press(hass, "button.bisync_resync_dry_run")
    await wait_until_done(hass, entry)
    attrs = attributes(hass, "switch.bisync")
    assert rcd.files(path2) == []
    assert real_listings(workdir) == {}
    assert state(hass, "binary_sensor.bisync_health") == "off"
    assert state(hass, "sensor.bisync_transfers") == "2"
    assert state(hass, "sensor.bisync_last_success_time") == "unknown"
    assert attrs["dry_run_requested"] is True
    assert attrs["resync_requested"] is True

    # Resync: a real run, and a success.
    await press(hass, "button.bisync_resync")
    await wait_until_done(hass, entry)
    attrs = attributes(hass, "switch.bisync")
    assert rcd.files(path2) == ["a.txt", "b.txt"]
    assert real_listings(workdir)
    first_success = state(hass, "sensor.bisync_last_success_time")
    assert first_success != "unknown"
    assert "dry_run_requested" not in attrs
    assert attrs["resync_requested"] is True

    # Dry Run: the new file is not copied, the real listings are untouched,
    # and Last Success Time stays where it was.
    (path1 / "new.txt").write_text("new" * 100)
    before = real_listings(workdir)
    await press(hass, "button.bisync_dry_run")
    await wait_until_done(hass, entry)
    attrs = attributes(hass, "switch.bisync")
    assert rcd.files(path2) == ["a.txt", "b.txt"]
    assert real_listings(workdir) == before
    assert state(hass, "sensor.bisync_transfers") == "1"
    assert state(hass, "sensor.bisync_last_success_time") == first_success
    assert attrs["dry_run_requested"] is True
    assert "resync_requested" not in attrs

    # A plain run copies it for real. End times are to the second, so wait
    # long enough for this success to be a later one.
    await asyncio.sleep(1.1)
    await switch(hass, "turn_on", "switch.bisync")
    await wait_until_done(hass, entry)
    attrs = attributes(hass, "switch.bisync")
    assert rcd.files(path2) == ["a.txt", "b.txt", "new.txt"]
    assert state(hass, "sensor.bisync_last_success_time") > first_success
    assert "dry_run_requested" not in attrs
    assert "resync_requested" not in attrs


async def test_sync_dry_run_and_a_press_while_running(
    hass: HomeAssistant, enable_custom_integrations: None, rcd: Rcd
) -> None:
    """Dry Run on sync, then a press during a real run is refused."""
    source, dest = rcd.root / "source", ":memory:dest"
    source.mkdir()
    for name in ("x.bin", "y.bin"):
        (source / name).write_bytes(os.urandom(64 * 1024))
    entry = await add_job(
        hass, rcd, "Sync", SYNC, {"srcFs": str(source), "dstFs": dest}
    )
    assert set(hass.states.async_entity_ids("button")) == {"button.sync_dry_run"}

    await press(hass, "button.sync_dry_run")
    await wait_until_done(hass, entry)
    assert rcd.call("operations/list", fs=dest, remote="").get("list", []) == []
    assert state(hass, "sensor.sync_transfers") == "2"
    assert state(hass, "sensor.sync_last_success_time") == "unknown"

    # Slow the real run down enough to press a button while it runs. The
    # rcd's limit is global; a per-call _config BwLimit did not slow it.
    rcd.call("core/bwlimit", rate="16k")
    await switch(hass, "turn_on", "switch.sync")
    assert state(hass, "switch.sync") == "on"
    with pytest.raises(HomeAssistantError, match="already in progress"):
        await press(hass, "button.sync_dry_run")

    await switch(hass, "turn_off", "switch.sync")
    await wait_until_done(hass, entry)
    assert state(hass, "switch.sync") == "off"
