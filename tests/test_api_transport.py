"""Tests for how api.py reaches rclone: the URL it builds and how it authenticates.

Like test_api_run_outcome.py, these need no Home Assistant harness. The
round-trip tests run a throwaway HTTP server on 127.0.0.1 and record what
arrives, so they check both HTTP clients api.py uses (requests and aiohttp).
"""

import asyncio
import base64
from collections.abc import Iterator
from http.server import BaseHTTPRequestHandler, HTTPServer
import json
from threading import Thread
from typing import Any

import pytest

from custom_components.rclone.api import API

# Every character here would end the host part of a URL early, and the README's
# own example password ends in "#".
AWKWARD_PASSWORD = "pa/ss?wo#rd@:"


def make_api(host: str, pwd: str = "1234") -> API:
    """Build an API instance for a host."""
    return API(host=host, user="test", pwd=pwd, friendly_name="Bisync")


@pytest.mark.parametrize(
    ("host", "expected"),
    [
        ("192.168.0.2:5572", "http://192.168.0.2:5572/core/stats"),
        ("localhost:5572", "http://localhost:5572/core/stats"),
        ("http://192.168.0.2:5572", "http://192.168.0.2:5572/core/stats"),
        ("https://rclone.example.com", "https://rclone.example.com/core/stats"),
        ("https://rclone.example.com/", "https://rclone.example.com/core/stats"),
        (
            "https://example.com:5572/rclone",
            "https://example.com:5572/rclone/core/stats",
        ),
        (
            "https://example.com:5572/rclone/",
            "https://example.com:5572/rclone/core/stats",
        ),
    ],
)
def test_url(host: str, expected: str) -> None:
    """A bare host:port means http://, as it did before https was supported."""
    assert make_api(host)._url("core/stats") == expected


def test_url_has_no_credentials() -> None:
    """Credentials travel in the Authorization header, never in the URL."""
    url = make_api("192.168.0.2:5572", pwd=AWKWARD_PASSWORD)._url("core/stats")
    assert "test" not in url
    assert "pa/ss" not in url


class _Recorder(BaseHTTPRequestHandler):
    """Record each request, and answer like rcd does for the calls tested."""

    requests: list[dict[str, Any]]

    def do_POST(self) -> None:
        length = int(self.headers.get("Content-Length", 0))
        body = json.loads(self.rfile.read(length) or b"{}")
        self.requests.append(
            {
                "path": self.path,
                "authorization": self.headers.get("Authorization"),
                "body": body,
            }
        )
        reply = {**body, "jobid": 7, "executeId": "abc"}
        data = json.dumps(reply).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def log_message(self, *args: Any) -> None:
        """Keep the test output quiet."""


@pytest.fixture(name="rcd")
def rcd_fixture(socket_enabled: None) -> Iterator[tuple[str, list[dict[str, Any]]]]:
    """Serve on a free port and yield (host:port, recorded requests).

    pytest-socket, pulled in by the Home Assistant test plugin, blocks sockets
    unless a test asks for socket_enabled.
    """
    recorded: list[dict[str, Any]] = []
    handler = type("Handler", (_Recorder,), {"requests": recorded})
    server = HTTPServer(("127.0.0.1", 0), handler)
    thread = Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"127.0.0.1:{server.server_port}", recorded
    finally:
        server.shutdown()
        server.server_close()


def expected_auth(pwd: str) -> str:
    """Return the Basic auth header rcd should receive."""
    return "Basic " + base64.b64encode(f"test:{pwd}".encode()).decode()


@pytest.mark.parametrize("with_scheme", [False, True])
def test_requests_calls_authenticate(rcd, with_scheme: bool) -> None:
    """The synchronous calls (requests) reach rcd with the password intact."""
    host, recorded = rcd
    api = make_api(f"http://{host}" if with_scheme else host, pwd=AWKWARD_PASSWORD)

    assert api.noopauth_call()
    api.jobstatus_call(7)

    assert [r["path"] for r in recorded] == ["/rc/noopauth", "/job/status"]
    for request in recorded:
        assert request["authorization"] == expected_auth(AWKWARD_PASSWORD)


def test_aiohttp_calls_authenticate(rcd) -> None:
    """The asynchronous calls (aiohttp) reach rcd with the password intact."""
    host, recorded = rcd
    api = make_api(host, pwd=AWKWARD_PASSWORD)

    # Not asyncio.run(): it unsets the current event loop when it finishes, and
    # the Home Assistant fixtures in later test files fail without one.
    loop = asyncio.new_event_loop()
    try:
        assert loop.run_until_complete(api.async_job_call("sync/sync", {})) == (
            7,
            "abc",
        )
        loop.run_until_complete(api.async_stop_job_call(7))
    finally:
        loop.close()

    assert [r["path"] for r in recorded] == ["/sync/sync", "/job/stop"]
    for request in recorded:
        assert request["authorization"] == expected_auth(AWKWARD_PASSWORD)
