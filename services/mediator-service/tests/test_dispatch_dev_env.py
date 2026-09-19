from __future__ import annotations

import json
from typing import Any

import httpx
import pytest

from mediator_service.dispatch import (
    DevEnvClient,
    DevEnvError,
    DevEnvUnreachableError,
    Output,
    Result,
    RunnerStreamError,
    Step,
    UnroutableStepError,
    to_step,
)
from mediator_service.resolve import UnrunnableActionError

DEV_ENV_URL = "http://dev-env.test"

TASK_ID = "t-1"
STEP_ID = "s-1"
SCOPE_ROOT = "C:\\scope"


def open_action(**overrides: Any) -> dict[str, Any]:
    base: dict[str, Any] = {"type": "open_in_editor", "path": "C:\\scope\\app.py", "line": 12}
    base.update(overrides)

    return base


def step_body(**overrides: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "step_id": STEP_ID,
        "position": 0,
        "description": "open the module in the editor",
        "service": "dev-env",
        "action": open_action(),
        "requires_confirmation": False,
        "confirmation_reason": None,
        "on_failure": "abort",
        "reversible": True,
        "criterion_refs": ["c-1"],
        "effects": {
            "writes_paths": [],
            "deletes_paths": [],
            "network": False,
            "installs_packages": False,
            "needs_credentials": False,
            "drives_input": False,
            "reversible": True,
        },
    }
    base.update(overrides)

    return base


def result_body(**overrides: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "event": "result",
        "step_id": STEP_ID,
        "exit_code": 0,
        "terminated_by": None,
        "error_message": None,
        "files_written": [],
        "files_deleted": [],
        "ports_opened": [],
        "started_at": "2026-09-19T11:53:41.759Z",
        "ended_at": "2026-09-19T11:53:42.902Z",
    }
    base.update(overrides)

    return base


def ndjson(*events: dict[str, Any]) -> bytes:
    return b"".join((json.dumps(event) + "\n").encode("utf-8") for event in events)


def stream_response(payload: bytes) -> httpx.Response:
    return httpx.Response(200, content=payload, headers={"content-type": "application/x-ndjson"})


class Recorder:
    def __init__(self, responses: list[httpx.Response]) -> None:
        self._responses = responses
        self.requests: list[httpx.Request] = []

    def transport(self) -> httpx.MockTransport:
        return httpx.MockTransport(self._handle)

    def _handle(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)

        return self._responses.pop(0) if self._responses else httpx.Response(200, json={})

    def sent(self) -> dict[str, Any]:
        parsed: Any = json.loads(self.requests[-1].content.decode("utf-8"))

        assert isinstance(parsed, dict)

        return parsed


def refuse_connection(request: httpx.Request) -> httpx.Response:
    raise httpx.ConnectError("no route to host", request=request)


def client_for(recorder: Recorder) -> DevEnvClient:
    return DevEnvClient(DEV_ENV_URL, 5.0, 1.0, transport=recorder.transport())


async def collect(
    client: DevEnvClient, step: Step, confirmed: bool = False
) -> list[Output | Result]:
    events: list[Output | Result] = []

    async for event in client.dispatch(step, SCOPE_ROOT, TASK_ID, confirmed):
        events.append(event)

    return events


def test_an_editor_step_is_dispatchable() -> None:
    step = to_step(step_body())

    assert step.opens_editor
    assert step.dispatchable
    assert not step.runnable
    assert not step.writes_file


def test_a_dev_env_step_carrying_a_runner_action_is_not_dispatchable() -> None:
    step = to_step(
        step_body(action={"type": "run_python_module", "module": "pytest", "arguments": []})
    )

    assert not step.opens_editor
    assert not step.dispatchable


def test_a_dev_env_step_with_no_action_is_not_dispatchable() -> None:
    assert not to_step(step_body(action=None)).dispatchable


def test_an_editor_action_on_the_runner_is_not_dispatchable() -> None:
    assert not to_step(step_body(service="task-runner")).dispatchable


async def test_the_step_is_posted_to_its_own_run_route() -> None:
    recorder = Recorder([stream_response(ndjson(result_body()))])
    client = client_for(recorder)

    await collect(client, to_step(step_body()))

    assert recorder.requests[-1].method == "POST"
    assert str(recorder.requests[-1].url) == f"{DEV_ENV_URL}/steps/{STEP_ID}/run"

    await client.close()


async def test_the_body_carries_the_action_exactly_as_the_router_wrote_it() -> None:
    recorder = Recorder([stream_response(ndjson(result_body()))])
    client = client_for(recorder)

    await collect(client, to_step(step_body()), confirmed=True)

    assert recorder.sent() == {
        "scope_root": SCOPE_ROOT,
        "task_id": TASK_ID,
        "confirmed": True,
        "action": open_action(),
    }

    await client.close()


async def test_a_null_line_reaches_dev_env_as_null() -> None:
    recorder = Recorder([stream_response(ndjson(result_body()))])
    client = client_for(recorder)

    await collect(client, to_step(step_body(action=open_action(line=None))))

    assert recorder.sent()["action"]["line"] is None

    await client.close()


async def test_a_clean_exit_reads_as_success() -> None:
    recorder = Recorder([stream_response(ndjson(result_body()))])
    client = client_for(recorder)

    events = await collect(client, to_step(step_body()))

    assert len(events) == 1
    assert isinstance(events[0], Result)
    assert events[0].ok
    assert events[0].touched_paths == ()

    await client.close()


async def test_a_missing_file_reads_as_a_failure_with_its_reason() -> None:
    reason = "C:\\scope\\app.py does not exist, so there is nothing to open"
    recorder = Recorder(
        [stream_response(ndjson(result_body(exit_code=None, error_message=reason)))]
    )
    client = client_for(recorder)

    events = await collect(client, to_step(step_body()))
    result = events[-1]

    assert isinstance(result, Result)
    assert not result.ok
    assert result.error_message == reason

    await client.close()


async def test_editor_output_arrives_before_the_result() -> None:
    output = {"event": "output", "step_id": STEP_ID, "stream": "stderr", "sequence": 0}
    recorder = Recorder([stream_response(ndjson({**output, "text": "warming up"}, result_body()))])
    client = client_for(recorder)

    events = await collect(client, to_step(step_body()))

    assert isinstance(events[0], Output)
    assert events[0].text == "warming up"
    assert isinstance(events[1], Result)

    await client.close()


@pytest.mark.parametrize("status", [403, 409, 422, 503])
async def test_a_refusal_raises_with_the_status_and_reason_intact(status: int) -> None:
    detail = "C:\\Windows\\win.ini is outside the project directory and the step was not confirmed"
    recorder = Recorder([httpx.Response(status, json={"detail": detail})])
    client = client_for(recorder)

    with pytest.raises(DevEnvError) as raised:
        await collect(client, to_step(step_body()))

    assert raised.value.status == status
    assert raised.value.detail == detail
    assert str(raised.value) == f"dev-env-service responded {status}: {detail}"

    await client.close()


async def test_a_line_that_is_not_json_stops_the_stream() -> None:
    recorder = Recorder([stream_response(b"not json\n")])
    client = client_for(recorder)

    with pytest.raises(RunnerStreamError):
        await collect(client, to_step(step_body()))

    await client.close()


async def test_dev_env_that_cannot_be_reached_is_named_with_its_address() -> None:
    client = DevEnvClient(DEV_ENV_URL, 5.0, 1.0, transport=httpx.MockTransport(refuse_connection))

    with pytest.raises(DevEnvUnreachableError) as raised:
        await collect(client, to_step(step_body()))

    assert str(raised.value) == f"dev-env-service unreachable at {DEV_ENV_URL}"

    await client.close()


async def test_a_step_for_another_service_is_never_sent() -> None:
    recorder = Recorder([])
    client = client_for(recorder)

    with pytest.raises(UnroutableStepError):
        await collect(client, to_step(step_body(service="task-runner")))

    assert recorder.requests == []

    await client.close()


async def test_a_step_without_an_editor_action_is_never_sent() -> None:
    recorder = Recorder([])
    client = client_for(recorder)

    with pytest.raises(UnrunnableActionError, match="open_in_editor"):
        await collect(client, to_step(step_body(action=None)))

    assert recorder.requests == []

    await client.close()
