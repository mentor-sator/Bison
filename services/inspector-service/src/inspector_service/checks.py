from __future__ import annotations

from dataclasses import dataclass
from typing import Any, ClassVar, Final

MIN_PORT: Final[int] = 1
MAX_PORT: Final[int] = 65535
MIN_STATUS: Final[int] = 100
MAX_STATUS: Final[int] = 599

CHECK_TYPES: Final[frozenset[str]] = frozenset(
    {
        "file_exists",
        "file_hash",
        "port_open",
        "http_status",
        "sql_result",
        "process_exit",
        "window_title",
        "text_on_screen",
    }
)


class CheckSpecError(RuntimeError):
    def __init__(self, detail: str) -> None:
        super().__init__(detail)
        self.detail = detail


@dataclass(frozen=True)
class FileExists:
    path: str
    TYPE: ClassVar[str] = "file_exists"


@dataclass(frozen=True)
class FileHash:
    path: str
    expected_sha256: str
    TYPE: ClassVar[str] = "file_hash"


@dataclass(frozen=True)
class PortOpen:
    host: str
    port: int
    TYPE: ClassVar[str] = "port_open"


@dataclass(frozen=True)
class HttpStatus:
    url: str
    expected_status: int
    timeout_ms: int
    TYPE: ClassVar[str] = "http_status"


@dataclass(frozen=True)
class SqlResult:
    connection_ref: str
    query: str
    expect: str
    TYPE: ClassVar[str] = "sql_result"


@dataclass(frozen=True)
class Unobserved:
    kind: str
    TYPE: ClassVar[str] = "unobserved"


CheckSpec = FileExists | FileHash | PortOpen | HttpStatus | SqlResult | Unobserved


def text(source: dict[str, Any], key: str) -> str:
    value = source.get(key)

    if not isinstance(value, str) or not value.strip():
        raise CheckSpecError(f"{key} must be a non-empty string")

    return value.strip()


def bounded(source: dict[str, Any], key: str, low: int, high: int) -> int:
    value = source.get(key)

    if isinstance(value, bool) or not isinstance(value, int):
        raise CheckSpecError(f"{key} must be a whole number")

    if value < low or value > high:
        raise CheckSpecError(f"{key} must be between {low} and {high}")

    return value


def parse(entry: Any) -> CheckSpec:
    if not isinstance(entry, dict):
        raise CheckSpecError("there is no check stored for this criterion")

    kind = entry.get("type")

    if not isinstance(kind, str) or kind not in CHECK_TYPES:
        raise CheckSpecError(f"{kind!r} is not a check BISON can run")

    if kind == "file_exists":
        return FileExists(path=text(entry, "path"))

    if kind == "file_hash":
        return FileHash(
            path=text(entry, "path"),
            expected_sha256=text(entry, "expected_sha256").lower(),
        )

    if kind == "port_open":
        return PortOpen(host=text(entry, "host"), port=bounded(entry, "port", MIN_PORT, MAX_PORT))

    if kind == "http_status":
        return HttpStatus(
            url=text(entry, "url"),
            expected_status=bounded(entry, "expected_status", MIN_STATUS, MAX_STATUS),
            timeout_ms=bounded(entry, "timeout_ms", 1, 600_000),
        )

    if kind == "sql_result":
        return SqlResult(
            connection_ref=text(entry, "connection_ref"),
            query=text(entry, "query"),
            expect=text(entry, "expect"),
        )

    return Unobserved(kind=kind)
