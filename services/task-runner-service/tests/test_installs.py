from __future__ import annotations

import asyncio
import sys
from datetime import UTC, datetime
from pathlib import Path

import pytest

from task_runner_service import venvs
from task_runner_service.installs import (
    Finished,
    Installer,
    InstallRefusedError,
    Line,
    command,
    environment,
    failure_of,
    requirements,
    result_event,
)

STARTED = datetime(2026, 9, 19, 12, 0, tzinfo=UTC)


def program(body: str) -> list[str]:
    return [sys.executable, "-c", body]


async def collect(
    installer: Installer, step_id: str, arguments: list[str], limit: int = 30
) -> tuple[list[Line], Finished]:
    lines: list[Line] = []
    finished: Finished | None = None

    async for item in installer.run(step_id, arguments, limit):
        if isinstance(item, Finished):
            finished = item
        else:
            lines.append(item)

    assert finished is not None

    return lines, finished


def finished(**overrides: object) -> Finished:
    declared: dict[str, object] = {
        "exit_code": 0,
        "terminated_by": None,
        "started_at": STARTED,
        "ended_at": STARTED,
        "tail": "",
    }
    declared.update(overrides)

    return Finished(**declared)  # type: ignore[arg-type]


@pytest.mark.parametrize(
    "package",
    [
        "fastapi",
        "uvicorn[standard]",
        "pydantic==2.9.2",
        "httpx>=0.27,<1",
        "SQLAlchemy~=2.0",
        "zope.interface",
        "types-requests",
    ],
)
def test_a_package_name_with_an_optional_version_is_accepted(package: str) -> None:
    assert requirements([package]) == [package]


def test_surrounding_whitespace_is_trimmed() -> None:
    assert requirements(["  fastapi  "]) == ["fastapi"]


@pytest.mark.parametrize(
    "package",
    [
        "-r requirements.txt",
        "--index-url=https://evil.example/simple",
        "https://evil.example/pkg.whl",
        r"C:\Users\dev\wheels\pkg.whl",
        "./local",
        "fastapi; rm -rf /",
        "fastapi && calc",
        "fast api",
        "",
    ],
)
def test_flags_paths_urls_and_command_fragments_are_refused(package: str) -> None:
    with pytest.raises(InstallRefusedError, match=r"packages\[0\]"):
        requirements([package])


def test_an_empty_install_is_refused() -> None:
    with pytest.raises(InstallRefusedError, match="at least one package"):
        requirements([])


def test_too_many_packages_are_refused() -> None:
    with pytest.raises(InstallRefusedError, match="at most 32"):
        requirements([f"package{index}" for index in range(33)])


def test_the_refusal_names_the_offending_entry() -> None:
    with pytest.raises(InstallRefusedError, match=r"packages\[1\] '-e \.'"):
        requirements(["fastapi", "-e ."])


def test_the_command_targets_the_task_interpreter_explicitly(tmp_path: Path) -> None:
    venv = tmp_path / "envs" / "task-1"

    assert command("uv", venv, ["fastapi", "uvicorn"]) == [
        "uv",
        "pip",
        "install",
        "--python",
        str(venvs.interpreter(venv)),
        "fastapi",
        "uvicorn",
    ]


def test_the_installer_keeps_the_machine_certificate_settings() -> None:
    inherited = environment(
        {
            "SSL_CERT_FILE": r"C:\certs\corporate-roots.pem",
            "UV_NATIVE_TLS": "1",
            "VIRTUAL_ENV": r"C:\elsewhere",
        }
    )

    assert inherited["SSL_CERT_FILE"] == r"C:\certs\corporate-roots.pem"
    assert inherited["UV_NATIVE_TLS"] == "1"
    assert "VIRTUAL_ENV" not in inherited
    assert inherited["UV_NO_PROGRESS"] == "1"


async def test_output_is_streamed_line_by_line_before_the_finish() -> None:
    body = "import sys; print('resolved 3 packages'); sys.stderr.write('installed fastapi\\n')"

    lines, done = await collect(Installer(), "s-1", program(body))

    assert Line("stdout", "resolved 3 packages") in lines
    assert Line("stderr", "installed fastapi") in lines
    assert done.exit_code == 0
    assert done.terminated_by is None


async def test_a_failed_install_keeps_the_end_of_what_it_said() -> None:
    body = (
        "import sys; sys.stderr.write('No solution found when resolving fastapi\\n'); sys.exit(1)"
    )

    _lines, done = await collect(Installer(), "s-1", program(body))

    assert done.exit_code == 1
    assert done.tail == "No solution found when resolving fastapi"


async def test_an_install_that_runs_too_long_is_stopped() -> None:
    _lines, done = await collect(
        Installer(), "s-1", program("import time; time.sleep(30)"), limit=1
    )

    assert done.terminated_by == "wall_clock"
    assert done.exit_code is None


async def test_a_halt_stops_a_running_install_and_says_so() -> None:
    installer = Installer()
    body = "import time; print('started', flush=True); time.sleep(30)"
    stream = installer.run("s-1", program(body), 30)

    first = await anext(stream)

    assert first == Line("stdout", "started")
    assert installer.active == ["s-1"]
    assert installer.terminate_all("halt") == ["s-1"]

    remaining = [item async for item in stream]
    done = remaining[-1]

    assert isinstance(done, Finished)
    assert done.terminated_by == "halt"
    assert installer.active == []


async def test_an_abandoned_install_does_not_outlive_its_stream() -> None:
    installer = Installer()
    stream = installer.run("s-1", program("import time; print('x', flush=True); time.sleep(30)"))

    await anext(stream)
    await asyncio.wait_for(stream.aclose(), 10)

    assert installer.active == []


def test_a_clean_install_reports_no_failure() -> None:
    assert failure_of(finished(), 600) is None


def test_a_failed_install_reports_the_exit_code_and_the_reason() -> None:
    reason = failure_of(finished(exit_code=2, tail="network unreachable"), 600)

    assert reason == "uv exited 2: network unreachable"


def test_a_timed_out_install_says_how_long_it_was_given() -> None:
    reason = failure_of(finished(exit_code=None, terminated_by="wall_clock"), 600)

    assert reason == "the install did not finish within 600 seconds"


def test_a_halted_install_says_what_stopped_it() -> None:
    reason = failure_of(finished(exit_code=None, terminated_by="halt"), 600)

    assert reason == "the install was stopped by halt"


def test_the_result_event_reads_like_a_run_result() -> None:
    event = result_event("s-1", ["fastapi"], finished(), 600)

    assert event == {
        "event": "result",
        "step_id": "s-1",
        "exit_code": 0,
        "terminated_by": None,
        "error_message": None,
        "packages": ["fastapi"],
        "files_written": [],
        "files_deleted": [],
        "ports_opened": [],
        "started_at": STARTED.isoformat(),
        "ended_at": STARTED.isoformat(),
    }
