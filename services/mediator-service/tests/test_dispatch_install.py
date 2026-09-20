from __future__ import annotations

import json
from typing import Any

import httpx
import pytest

from mediator_service.dispatch import (
    ABORTED,
    FAILED,
    SUCCEEDED,
    Output,
    Result,
    RunnerClient,
    Step,
    to_step,
)
from mediator_service.resolve import UnrunnableActionError

RUNNER_URL = "http://runner.test"
SCOPE_ROOT = "C:\\scope"
TASK_ID = "t-1"
STEP_ID = "s-1"


def install_step(**overrides: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "step_id": STEP_ID,
        "position": 0,
        "description": "install the web framework",
        "service": "task-runner",
        "action": {"type": "install_python_packages", "packages": ["fastapi", "uvicorn"]},
        "requires_confirmation": True,
        "confirmation_reason": "reaches the network; installs packages",
        "on_failure": "abort",
        "reversible": True,
        "criterion_refs": ["c-1"],
        "effects": {
            "writes_paths": [],
            "deletes_paths": [],
            "network": True,
            "installs_packages": True,
            "needs_credentials": False,
            "drives_input": False,
            "reversible": True,
        },
    }
    base.update(overrides)

    return base


def installer_result(**overrides: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "event": "result",
        "step_id": STEP_ID,
        "exit_code": 0,
        "terminated_by": None,
        "error_message": None,
        "packages": ["fastapi", "uvicorn"],
        "files_written": [],
        "files_deleted": [],
        "ports_opened": [],
        "started_at": "2026-09-19T12:00:00+00:00",
        "ended_at": "2026-09-19T12:00:09+00:00",
    }
    base.update(overrides)

    return base


def ndjson(*events: dict[str, Any]) -> bytes:
    return b"".join((json.dumps(event) + "\n").encode("utf-8") for event in events)


class Recorder:
    def __init__(self, payload: bytes) -> None:
        self._payload = payload
        self.requests: list[httpx.Request] = []

    def transport(self) -> httpx.MockTransport:
        return httpx.MockTransport(self._handle)

    def _handle(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)

        return httpx.Response(
            200, content=self._payload, headers={"content-type": "application/x-ndjson"}
        )

    def sent(self) -> dict[str, Any]:
        parsed: Any = json.loads(self.requests[-1].content.decode("utf-8"))

        assert isinstance(parsed, dict)

        return parsed


async def collect(client: RunnerClient, step: Step) -> list[Output | Result]:
    events: list[Output | Result] = []

    async for event in client.dispatch(step, SCOPE_ROOT, TASK_ID, True):
        events.append(event)

    return events


def test_an_install_step_is_recognised_as_an_install() -> None:
    step = to_step(install_step())

    assert step.installs
    assert not step.writes_file
    assert step.dispatchable


def test_a_script_step_is_not_an_install() -> None:
    step = to_step(
        install_step(action={"type": "run_python_script", "script_path": "a.py", "arguments": []})
    )

    assert not step.installs


async def test_the_install_body_carries_everything_the_runner_checks() -> None:
    recorder = Recorder(ndjson(installer_result()))
    client = RunnerClient(RUNNER_URL, 5.0, 1.0, transport=recorder.transport())
    step = to_step(install_step())

    await collect(client, step)

    assert recorder.sent() == {
        "scope_root": SCOPE_ROOT,
        "task_id": TASK_ID,
        "step": step.raw,
        "confirmed": True,
        "packages": ["fastapi", "uvicorn"],
    }

    await client.close()


async def test_installer_output_and_a_clean_result_read_as_success() -> None:
    output = {
        "event": "output",
        "step_id": STEP_ID,
        "stream": "stderr",
        "sequence": 0,
        "text": "Installed 2 packages\n",
    }
    recorder = Recorder(ndjson(output, installer_result()))
    client = RunnerClient(RUNNER_URL, 5.0, 1.0, transport=recorder.transport())

    events = await collect(client, to_step(install_step()))

    assert isinstance(events[0], Output)
    assert events[0].text == "Installed 2 packages\n"
    assert isinstance(events[-1], Result)
    assert events[-1].state == SUCCEEDED

    await client.close()


async def test_a_failed_install_carries_the_installer_reason() -> None:
    reason = "uv exited 1: No solution found when resolving fastapi"
    recorder = Recorder(ndjson(installer_result(exit_code=1, error_message=reason)))
    client = RunnerClient(RUNNER_URL, 5.0, 1.0, transport=recorder.transport())

    result = (await collect(client, to_step(install_step())))[-1]

    assert isinstance(result, Result)
    assert result.state == FAILED
    assert result.error_message == reason

    await client.close()


async def test_a_halted_install_reads_as_aborted() -> None:
    recorder = Recorder(
        ndjson(
            installer_result(
                exit_code=None,
                terminated_by="halt",
                error_message="the install was stopped by halt",
            )
        )
    )
    client = RunnerClient(RUNNER_URL, 5.0, 1.0, transport=recorder.transport())

    result = (await collect(client, to_step(install_step())))[-1]

    assert isinstance(result, Result)
    assert result.state == ABORTED

    await client.close()


async def test_an_install_naming_nothing_is_refused_before_it_is_sent() -> None:
    recorder = Recorder(ndjson(installer_result()))
    client = RunnerClient(RUNNER_URL, 5.0, 1.0, transport=recorder.transport())
    step = to_step(install_step(action={"type": "install_python_packages", "packages": []}))

    with pytest.raises(UnrunnableActionError, match="at least one package"):
        await collect(client, step)

    assert recorder.requests == []

    await client.close()
