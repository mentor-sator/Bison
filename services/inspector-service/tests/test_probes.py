from __future__ import annotations

import socket
import threading
from collections.abc import Iterator
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

from inspector_service.checks import HttpStatus, PortOpen
from inspector_service.runners import run

PROBE_SECONDS = 1.0


class Answer(BaseHTTPRequestHandler):
    def do_GET(self) -> None:
        status = 200 if self.path == "/tasks" else 404
        self.send_response(status)
        self.send_header("Content-Length", "0")
        self.end_headers()

    def log_message(self, format: str, *args: object) -> None:
        return None


@pytest.fixture
def listening() -> Iterator[int]:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as server:
        server.bind(("127.0.0.1", 0))
        server.listen()
        yield server.getsockname()[1]


@pytest.fixture
def closed() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
        probe.bind(("127.0.0.1", 0))
        port: int = probe.getsockname()[1]

    return port


@pytest.fixture
def api() -> Iterator[int]:
    server = ThreadingHTTPServer(("127.0.0.1", 0), Answer)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()

    try:
        yield server.server_address[1]
    finally:
        server.shutdown()
        server.server_close()


def test_a_listening_port_is_verified(listening: int, tmp_path: Path) -> None:
    finding = run(PortOpen(host="127.0.0.1", port=listening), tmp_path, PROBE_SECONDS)

    assert finding.verdict == "verified"


def test_a_closed_port_fails(closed: int, tmp_path: Path) -> None:
    finding = run(PortOpen(host="127.0.0.1", port=closed), tmp_path, PROBE_SECONDS)

    assert finding.verdict == "failed"
    assert "nothing is listening" in finding.reason


@pytest.mark.parametrize("port", [8000, 8450, 9000])
def test_a_bison_port_is_inconclusive_because_bison_answers_there(
    port: int, tmp_path: Path
) -> None:
    finding = run(PortOpen(host="127.0.0.1", port=port), tmp_path, PROBE_SECONDS)

    assert finding.verdict == "inconclusive"
    assert "belongs to BISON's own services" in finding.reason


def test_another_machine_is_inconclusive(tmp_path: Path) -> None:
    finding = run(PortOpen(host="example.com", port=443), tmp_path, PROBE_SECONDS)

    assert finding.verdict == "inconclusive"
    assert "not this machine" in finding.reason


def test_the_expected_status_is_verified(api: int, tmp_path: Path) -> None:
    spec = HttpStatus(url=f"http://127.0.0.1:{api}/tasks", expected_status=200, timeout_ms=2000)
    finding = run(spec, tmp_path, PROBE_SECONDS)

    assert finding.verdict == "verified"
    assert finding.evidence_kind == "http_response"
    assert finding.excerpt == "HTTP 200"


def test_a_different_status_fails_and_names_both(api: int, tmp_path: Path) -> None:
    spec = HttpStatus(url=f"http://localhost:{api}/absent", expected_status=200, timeout_ms=2000)
    finding = run(spec, tmp_path, PROBE_SECONDS)

    assert finding.verdict == "failed"
    assert "answered 404, not 200" in finding.reason


def test_nothing_answering_fails(closed: int, tmp_path: Path) -> None:
    spec = HttpStatus(url=f"http://127.0.0.1:{closed}/tasks", expected_status=200, timeout_ms=500)

    assert run(spec, tmp_path, PROBE_SECONDS).verdict == "failed"


def test_an_address_on_a_bison_port_is_inconclusive(tmp_path: Path) -> None:
    spec = HttpStatus(url="http://127.0.0.1:8000/tasks", expected_status=200, timeout_ms=2000)
    finding = run(spec, tmp_path, PROBE_SECONDS)

    assert finding.verdict == "inconclusive"
    assert "port 8000" in finding.reason


def test_an_address_on_another_machine_is_inconclusive(tmp_path: Path) -> None:
    spec = HttpStatus(url="http://example.com/", expected_status=200, timeout_ms=500)

    assert "not this machine" in run(spec, tmp_path, PROBE_SECONDS).reason


@pytest.mark.parametrize("url", ["ftp://127.0.0.1/file", "127.0.0.1:9101/tasks"])
def test_an_address_that_is_not_http_is_inconclusive(url: str, tmp_path: Path) -> None:
    spec = HttpStatus(url=url, expected_status=200, timeout_ms=500)

    assert run(spec, tmp_path, PROBE_SECONDS).verdict == "inconclusive"
