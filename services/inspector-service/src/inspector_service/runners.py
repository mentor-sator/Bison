from __future__ import annotations

import hashlib
import socket
import sqlite3
from contextlib import closing
from dataclasses import dataclass
from pathlib import Path
from typing import Final, Literal
from urllib.parse import urlsplit

import httpx

from inspector_service.checks import (
    CheckSpec,
    FileExists,
    FileHash,
    HttpStatus,
    PortOpen,
    SqlResult,
    Unobserved,
)

Verdict = Literal["verified", "failed", "inconclusive"]
EvidenceKind = Literal["file_hash", "http_response", "sql_result"]

WORKSPACE_PLACEHOLDER: Final[str] = "<workspace>"
LOCAL_HOSTS: Final[frozenset[str]] = frozenset({"localhost", "127.0.0.1", "::1"})
RESERVED_PORT_LOW: Final[int] = 8000
RESERVED_PORT_HIGH: Final[int] = 9000
MAX_EXCERPT_CHARS: Final[int] = 300
HASH_CHUNK_BYTES: Final[int] = 1 << 20
DEFAULT_PORTS: Final[dict[str, int]] = {"http": 80, "https": 443}

NEEDS: Final[dict[str, str]] = {
    "process_exit": "the exit code of a finished step",
    "window_title": "the window list from the screen observer",
    "text_on_screen": "a screenshot and OCR from the screen observer",
}


@dataclass(frozen=True)
class Finding:
    verdict: Verdict
    reason: str
    evidence_kind: EvidenceKind | None = None
    excerpt: str | None = None


def verified(reason: str, kind: EvidenceKind | None = None, excerpt: str | None = None) -> Finding:
    return Finding("verified", reason, kind, clipped(excerpt))


def failed(reason: str, kind: EvidenceKind | None = None, excerpt: str | None = None) -> Finding:
    return Finding("failed", reason, kind, clipped(excerpt))


def inconclusive(reason: str) -> Finding:
    return Finding("inconclusive", reason)


def clipped(value: str | None) -> str | None:
    if value is None or len(value) <= MAX_EXCERPT_CHARS:
        return value

    return f"{value[:MAX_EXCERPT_CHARS]}..."


def located(reference: str, workspace: Path) -> Path | None:
    stripped = reference.strip()
    lowered = stripped.lower()

    if lowered.startswith(WORKSPACE_PLACEHOLDER):
        remainder = stripped[len(WORKSPACE_PLACEHOLDER) :].lstrip("/\\")
        candidate = workspace / remainder if remainder else workspace
    else:
        given = Path(stripped)
        candidate = given if given.is_absolute() else workspace / given

    root = workspace.resolve()
    target = candidate.resolve()

    return target if target == root or target.is_relative_to(root) else None


def reserved(port: int) -> bool:
    return RESERVED_PORT_LOW <= port <= RESERVED_PORT_HIGH


def unobservable_port(host: str, port: int) -> Finding | None:
    if host.strip("[]").lower() not in LOCAL_HOSTS:
        return inconclusive(f"{host} is not this machine, and the inspector only probes this one")

    if reserved(port):
        return inconclusive(
            f"port {port} belongs to BISON's own services, so an answer there proves nothing "
            "about this project; the criterion needs a port above 9000"
        )

    return None


def sha256_of(path: Path) -> str:
    digest = hashlib.sha256()

    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(HASH_CHUNK_BYTES), b""):
            digest.update(chunk)

    return digest.hexdigest()


def outside(reference: str) -> Finding:
    return inconclusive(f"{reference} is outside the project workspace, which is all it reads")


def check_file_exists(spec: FileExists, workspace: Path) -> Finding:
    target = located(spec.path, workspace)

    if target is None:
        return outside(spec.path)

    if target.is_file():
        return verified(f"{target} exists", "file_hash", f"sha256 {sha256_of(target)}")

    if target.is_dir():
        return verified(f"{target} exists as a folder")

    return failed(f"{target} does not exist")


def check_file_hash(spec: FileHash, workspace: Path) -> Finding:
    target = located(spec.path, workspace)

    if target is None:
        return outside(spec.path)

    if not target.is_file():
        return failed(f"{target} does not exist, so it has no digest")

    actual = sha256_of(target)

    if actual == spec.expected_sha256:
        return verified(f"{target} has the expected digest", "file_hash", f"sha256 {actual}")

    return failed(
        f"{target} has digest {actual}, not the expected {spec.expected_sha256}",
        "file_hash",
        f"sha256 {actual}",
    )


def check_port_open(spec: PortOpen, probe_seconds: float) -> Finding:
    blocked = unobservable_port(spec.host, spec.port)

    if blocked is not None:
        return blocked

    try:
        with socket.create_connection((spec.host.strip("[]"), spec.port), timeout=probe_seconds):
            return verified(f"something is listening on {spec.host}:{spec.port}")
    except OSError:
        return failed(f"nothing is listening on {spec.host}:{spec.port}")


def check_http_status(spec: HttpStatus) -> Finding:
    parts = urlsplit(spec.url)

    if parts.scheme not in DEFAULT_PORTS or not parts.hostname:
        return inconclusive(f"{spec.url} is not an http or https address")

    try:
        port = parts.port or DEFAULT_PORTS[parts.scheme]
    except ValueError:
        return inconclusive(f"{spec.url} names a port that is not a number")

    blocked = unobservable_port(parts.hostname, port)

    if blocked is not None:
        return blocked

    try:
        with httpx.Client(trust_env=False, timeout=spec.timeout_ms / 1000) as client:
            response = client.get(spec.url)
    except httpx.HTTPError:
        return failed(f"nothing answered at {spec.url}")

    excerpt = f"HTTP {response.status_code}"

    if response.status_code == spec.expected_status:
        return verified(f"{spec.url} answered {response.status_code}", "http_response", excerpt)

    return failed(
        f"{spec.url} answered {response.status_code}, not {spec.expected_status}",
        "http_response",
        excerpt,
    )


def check_sql_result(spec: SqlResult, workspace: Path, probe_seconds: float) -> Finding:
    if "://" in spec.connection_ref:
        return inconclusive(f"{spec.connection_ref} is not a SQLite file, the only database read")

    target = located(spec.connection_ref, workspace)

    if target is None:
        return outside(spec.connection_ref)

    if not target.is_file():
        return failed(f"the database {target} does not exist")

    try:
        with closing(
            sqlite3.connect(f"{target.as_uri()}?mode=ro", uri=True, timeout=probe_seconds)
        ) as link:
            row = link.execute(spec.query).fetchone()
    except sqlite3.Error as error:
        return inconclusive(f"the stored query could not run: {error}")

    actual = "" if row is None or row[0] is None else str(row[0]).strip()
    excerpt = f"{spec.query} -> {actual or 'no rows'}"

    if actual == spec.expect:
        return verified(f"the query returned {actual}", "sql_result", excerpt)

    return failed(
        f"the query returned {actual or 'no rows'}, not {spec.expect}", "sql_result", excerpt
    )


def check_unobserved(spec: Unobserved) -> Finding:
    needed = NEEDS.get(spec.kind, "evidence the inspector does not collect")

    return inconclusive(f"a {spec.kind} check needs {needed}, which the inspector cannot read yet")


def run(spec: CheckSpec, workspace: Path, probe_seconds: float) -> Finding:
    if isinstance(spec, FileExists):
        return check_file_exists(spec, workspace)

    if isinstance(spec, FileHash):
        return check_file_hash(spec, workspace)

    if isinstance(spec, PortOpen):
        return check_port_open(spec, probe_seconds)

    if isinstance(spec, HttpStatus):
        return check_http_status(spec)

    if isinstance(spec, SqlResult):
        return check_sql_result(spec, workspace, probe_seconds)

    return check_unobserved(spec)
