from __future__ import annotations

import asyncio
import os
import re
import shutil
from collections.abc import AsyncGenerator, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Final

from task_runner_service import venvs

MAX_PACKAGES: Final[int] = 32
MAX_PACKAGE_CHARS: Final[int] = 200
INSTALL_TIMEOUT_SECONDS: Final[int] = 600
MAX_ERROR_CHARS: Final[int] = 500

NAME: Final[str] = r"[A-Za-z0-9](?:[A-Za-z0-9._-]*[A-Za-z0-9])?"
EXTRAS: Final[str] = rf"(?:\[{NAME}(?:,{NAME})*\])?"
CLAUSE: Final[str] = r"(?:===|==|!=|<=|>=|~=|<|>)[A-Za-z0-9.*+!_-]+"
SPECIFIER: Final[str] = rf"(?:{CLAUSE}(?:,{CLAUSE})*)?"
REQUIREMENT: Final[re.Pattern[str]] = re.compile(rf"{NAME}{EXTRAS}{SPECIFIER}")


class InstallRefusedError(RuntimeError):
    def __init__(self, detail: str) -> None:
        super().__init__(detail)
        self.detail = detail


class InstallerUnavailableError(RuntimeError):
    def __init__(self) -> None:
        super().__init__("uv is not on PATH; packages cannot be installed")


@dataclass(frozen=True)
class Line:
    stream: str
    text: str


@dataclass(frozen=True)
class Finished:
    exit_code: int | None
    terminated_by: str | None
    started_at: datetime
    ended_at: datetime
    tail: str


def requirements(declared: list[str]) -> list[str]:
    if not declared:
        raise InstallRefusedError("an install must name at least one package")

    if len(declared) > MAX_PACKAGES:
        raise InstallRefusedError(f"an install may name at most {MAX_PACKAGES} packages")

    accepted: list[str] = []

    for index, entry in enumerate(declared):
        candidate = entry.strip()

        if len(candidate) > MAX_PACKAGE_CHARS:
            raise InstallRefusedError(
                f"packages[{index}] is longer than {MAX_PACKAGE_CHARS} characters"
            )

        if not REQUIREMENT.fullmatch(candidate):
            raise InstallRefusedError(
                f"packages[{index}] {entry!r} is not a package name with an optional "
                "version; flags, paths and URLs are not accepted"
            )

        accepted.append(candidate)

    return accepted


def installer() -> str:
    found = shutil.which("uv")

    if found is None:
        raise InstallerUnavailableError()

    return found


def command(uv: str, venv: Path, packages: list[str]) -> list[str]:
    return [uv, "pip", "install", "--python", str(venvs.interpreter(venv)), *packages]


def environment(source: Mapping[str, str]) -> dict[str, str]:
    inherited = dict(source)
    inherited.pop("VIRTUAL_ENV", None)
    inherited["UV_NO_PROGRESS"] = "1"

    return inherited


def trimmed(text: str) -> str:
    flat = text.strip()

    return flat if len(flat) <= MAX_ERROR_CHARS else f"...{flat[-MAX_ERROR_CHARS:]}"


async def pump(
    stream: asyncio.StreamReader | None, name: str, lines: asyncio.Queue[Line | None]
) -> None:
    if stream is not None:
        while raw := await stream.readline():
            await lines.put(Line(name, raw.decode("utf-8", "replace").rstrip("\r\n")))

    await lines.put(None)


class Installer:
    def __init__(self) -> None:
        self._running: dict[str, asyncio.subprocess.Process] = {}
        self._stopped: dict[str, str] = {}

    @property
    def active(self) -> list[str]:
        return sorted(self._running)

    def terminate_all(self, reason: str) -> list[str]:
        stopped = sorted(self._running)

        for step_id in stopped:
            self._stopped[step_id] = reason

            if self._running[step_id].returncode is None:
                self._running[step_id].kill()

        return stopped

    async def run(
        self,
        step_id: str,
        arguments: list[str],
        timeout_seconds: int = INSTALL_TIMEOUT_SECONDS,
    ) -> AsyncGenerator[Line | Finished, None]:
        started = datetime.now(UTC)
        process = await asyncio.create_subprocess_exec(
            *arguments,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            env=environment(os.environ),
        )
        self._running[step_id] = process
        lines: asyncio.Queue[Line | None] = asyncio.Queue()
        readers = [
            asyncio.create_task(pump(process.stdout, "stdout", lines)),
            asyncio.create_task(pump(process.stderr, "stderr", lines)),
        ]
        loop = asyncio.get_running_loop()
        deadline = loop.time() + timeout_seconds
        open_streams = len(readers)
        errors: list[str] = []
        drained = False

        try:
            while open_streams:
                remaining = deadline - loop.time()

                if remaining <= 0:
                    self._stopped.setdefault(step_id, "wall_clock")
                    break

                try:
                    line = await asyncio.wait_for(lines.get(), remaining)
                except TimeoutError:
                    self._stopped.setdefault(step_id, "wall_clock")
                    break

                if line is None:
                    open_streams -= 1
                    continue

                if line.stream == "stderr":
                    errors.append(line.text)

                yield line

            drained = open_streams == 0
        finally:
            if not drained and process.returncode is None:
                process.kill()

            await process.wait()

            for reader in readers:
                reader.cancel()

            del self._running[step_id]
            stopped = self._stopped.pop(step_id, None)

        yield Finished(
            exit_code=None if stopped else process.returncode,
            terminated_by=stopped,
            started_at=started,
            ended_at=datetime.now(UTC),
            tail=trimmed("\n".join(errors)),
        )


def output_event(step_id: str, sequence: int, line: Line) -> dict[str, Any]:
    return {
        "event": "output",
        "step_id": step_id,
        "stream": line.stream,
        "sequence": sequence,
        "text": f"{line.text}\n",
    }


def failure_of(finished: Finished, timeout_seconds: int) -> str | None:
    if finished.terminated_by == "wall_clock":
        return f"the install did not finish within {timeout_seconds} seconds"

    if finished.terminated_by is not None:
        return f"the install was stopped by {finished.terminated_by}"

    if finished.exit_code == 0:
        return None

    code = f"uv exited {finished.exit_code}"

    return f"{code}: {finished.tail}" if finished.tail else code


def result_event(
    step_id: str, packages: list[str], finished: Finished, timeout_seconds: int
) -> dict[str, Any]:
    return {
        "event": "result",
        "step_id": step_id,
        "exit_code": finished.exit_code,
        "terminated_by": finished.terminated_by,
        "error_message": failure_of(finished, timeout_seconds),
        "packages": packages,
        "files_written": [],
        "files_deleted": [],
        "ports_opened": [],
        "started_at": finished.started_at.isoformat(),
        "ended_at": finished.ended_at.isoformat(),
    }
