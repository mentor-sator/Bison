from __future__ import annotations

from typing import Any

import pytest

from inspector_service.checks import (
    CheckSpecError,
    FileExists,
    FileHash,
    HttpStatus,
    PortOpen,
    SqlResult,
    Unobserved,
    parse,
)

DIGEST = "a" * 64


def test_a_file_exists_check_is_read() -> None:
    assert parse({"type": "file_exists", "path": "<workspace>/main.py"}) == FileExists(
        path="<workspace>/main.py"
    )


def test_a_file_hash_check_is_read_in_lower_case() -> None:
    spec = parse({"type": "file_hash", "path": "a.py", "expected_sha256": DIGEST.upper()})

    assert spec == FileHash(path="a.py", expected_sha256=DIGEST)


def test_a_port_open_check_is_read() -> None:
    assert parse({"type": "port_open", "host": "127.0.0.1", "port": 9101}) == PortOpen(
        host="127.0.0.1", port=9101
    )


def test_an_http_status_check_is_read() -> None:
    spec = parse(
        {
            "type": "http_status",
            "url": "http://127.0.0.1:9101/tasks",
            "expected_status": 200,
            "timeout_ms": 2000,
        }
    )

    assert spec == HttpStatus(
        url="http://127.0.0.1:9101/tasks", expected_status=200, timeout_ms=2000
    )


def test_a_sql_result_check_is_read() -> None:
    spec = parse(
        {
            "type": "sql_result",
            "connection_ref": "<workspace>/tasks.db",
            "query": "SELECT 1",
            "expect": "1",
        }
    )

    assert spec == SqlResult(connection_ref="<workspace>/tasks.db", query="SELECT 1", expect="1")


@pytest.mark.parametrize("kind", ["process_exit", "window_title", "text_on_screen"])
def test_a_check_the_inspector_cannot_observe_is_still_read(kind: str) -> None:
    assert parse({"type": kind}) == Unobserved(kind=kind)


@pytest.mark.parametrize(
    "entry",
    [
        None,
        [],
        {},
        {"type": "teleport"},
        {"type": "file_exists"},
        {"type": "file_exists", "path": "   "},
        {"type": "port_open", "host": "127.0.0.1", "port": 0},
        {"type": "port_open", "host": "127.0.0.1", "port": True},
        {"type": "http_status", "url": "http://x", "expected_status": 99, "timeout_ms": 10},
        {"type": "http_status", "url": "http://x", "expected_status": 200, "timeout_ms": 0},
        {"type": "sql_result", "connection_ref": "a.db", "query": "SELECT 1"},
    ],
)
def test_a_malformed_check_is_refused(entry: Any) -> None:
    with pytest.raises(CheckSpecError):
        parse(entry)


def test_a_missing_check_says_so() -> None:
    with pytest.raises(CheckSpecError) as caught:
        parse(None)

    assert "no check stored" in caught.value.detail
