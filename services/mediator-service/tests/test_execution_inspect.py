from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any

import httpx

from mediator_service.events import Emitter
from mediator_service.execution import AWAITING, COMPLETED, FAILED, HALTED, Clients, TaskPass
from mediator_service.inspection import InspectorClient
from tests.test_execution import (
    PROJECT_ID,
    REQUEST_ID,
    TASK_ID,
    FakeDevEnv,
    FakeProject,
    FakeRouter,
    FakeRunner,
    Halt,
    failed,
    plan_of,
    step_body,
    succeeded,
    task,
)

INSPECT_PATH = f"/projects/{PROJECT_ID}/tasks/{TASK_ID}/inspect"

REPORT: dict[str, Any] = {
    "project_id": PROJECT_ID,
    "workspace": "C:\\workspace",
    "inspected_at": "2026-09-21T10:00:00+00:00",
    "verified": 1,
    "failed": 1,
    "inconclusive": 1,
    "changed": 2,
    "results": [
        {
            "criterion_id": "c-1",
            "task_id": TASK_ID,
            "statement": "db_helper.py exists",
            "check_kind": "deterministic",
            "verdict": "verified",
            "reasoning": "the file is there",
            "evidence": [],
            "status_before": "unverified",
            "status_after": "verified",
        },
        {
            "criterion_id": "c-2",
            "task_id": TASK_ID,
            "statement": "tasks.db holds a tasks table",
            "check_kind": "deterministic",
            "verdict": "failed",
            "reasoning": "tasks.db does not exist",
            "evidence": [],
            "status_before": "unverified",
            "status_after": "failed",
        },
        {
            "criterion_id": "c-3",
            "task_id": TASK_ID,
            "statement": "the window shows the list",
            "check_kind": "inspected",
            "verdict": "inconclusive",
            "reasoning": "the inspector model is not built yet",
            "evidence": [],
            "status_before": "unverified",
            "status_after": "unverified",
        },
    ],
}


def refused(request: httpx.Request) -> httpx.Response:
    raise AssertionError(f"the inspector was not expected to be asked, but {request.url} was")


def unreachable(request: httpx.Request) -> httpx.Response:
    raise httpx.ConnectError("connection refused", request=request)


@dataclass
class Watch:
    project: FakeProject
    status: int = 200
    body: Any = field(default_factory=lambda: REPORT)
    calls: list[tuple[str, str]] = field(default_factory=list)
    states_when_asked: list[list[str]] = field(default_factory=list)

    def handler(self, request: httpx.Request) -> httpx.Response:
        self.calls.append((request.method, request.url.path))
        self.states_when_asked.append([state for _, state, _ in self.project.task_moves])

        return httpx.Response(self.status, content=json.dumps(self.body).encode("utf-8"))


@dataclass
class Inspected:
    run: TaskPass
    project: FakeProject
    watch: Watch
    emitted: list[dict[str, Any]]

    def names(self) -> list[str]:
        return [entry["event"] for entry in self.emitted]

    def one(self, name: str) -> dict[str, Any]:
        found = [entry for entry in self.emitted if entry["event"] == name]

        assert len(found) == 1

        return found[0]

    def task_states(self) -> list[str]:
        return [state for _, state, _ in self.project.task_moves]


async def inspected_pass(
    *,
    steps: tuple[dict[str, Any], ...] = (step_body(),),
    scripts: dict[str, list[Any]] | None = None,
    wired: bool = True,
    status: int = 200,
    body: Any = None,
    down: bool = False,
    untouched: bool = False,
    halt_after: int | None = None,
) -> Inspected:
    project = FakeProject()
    watch = Watch(project, status=status, body=body if body is not None else REPORT)
    handler = unreachable if down else refused if untouched else watch.handler
    inspector = (
        InspectorClient("http://127.0.0.1:8450", 5.0, 1.0, transport=httpx.MockTransport(handler))
        if wired
        else None
    )
    clients = Clients(
        FakeRouter((plan_of(*steps),)),
        FakeRunner(scripts if scripts is not None else {"s-1": [succeeded()]}),
        FakeDevEnv(),
        project,
        inspector,
    )
    walker = TaskPass(
        clients,
        Emitter(REQUEST_ID, PROJECT_ID),
        PROJECT_ID,
        REQUEST_ID,
        task(state="ready"),
        0,
        1,
        Halt(halt_after),
    )

    emitted = [json.loads(chunk.decode("utf-8")) async for chunk in walker.stream()]

    await clients.close()

    return Inspected(walker, project, watch, emitted)


async def test_a_completed_task_asks_the_inspector_about_itself() -> None:
    ran = await inspected_pass()

    assert ran.watch.calls == [("POST", INSPECT_PATH)]


async def test_the_inspector_is_asked_while_the_task_is_verifying() -> None:
    ran = await inspected_pass()

    assert ran.watch.states_when_asked == [["in_progress", "verifying"]]
    assert ran.task_states() == ["in_progress", "verifying", "done"]


async def test_the_verdict_counts_reach_the_stream() -> None:
    ran = await inspected_pass()
    event = ran.one("task_inspected")

    assert event["task_id"] == TASK_ID
    assert (event["verified"], event["failed"], event["inconclusive"]) == (1, 1, 1)
    assert event["changed"] == 2


async def test_every_verdict_reaches_the_stream_with_its_reasoning() -> None:
    ran = await inspected_pass()
    verdicts = ran.one("task_inspected")["verdicts"]

    assert [entry["criterion_id"] for entry in verdicts] == ["c-1", "c-2", "c-3"]
    assert verdicts[1] == {
        "criterion_id": "c-2",
        "statement": "tasks.db holds a tasks table",
        "verdict": "failed",
        "reasoning": "tasks.db does not exist",
        "status_before": "unverified",
        "status_after": "failed",
    }


async def test_the_inspection_lands_after_the_steps_and_before_the_finish() -> None:
    names = (await inspected_pass()).names()

    assert names.index("step_finished") < names.index("task_inspected")
    assert names.index("task_inspected") == names.index("task_finished") - 1


async def test_the_pass_keeps_the_inspection_it_received() -> None:
    ran = await inspected_pass()

    assert ran.run.inspection is not None
    assert ran.run.inspection.failed == 1
    assert ran.run.state == COMPLETED


async def test_an_unreachable_inspector_is_reported_and_the_task_still_finishes() -> None:
    ran = await inspected_pass(down=True)
    event = ran.one("inspection_unavailable")

    assert "8450" in event["detail"]
    assert "task_inspected" not in ran.names()
    assert ran.task_states()[-2:] == ["verifying", "done"]
    assert ran.run.state == COMPLETED
    assert ran.run.inspection is None


async def test_a_refusing_inspector_is_reported_with_its_detail() -> None:
    ran = await inspected_pass(status=503, body={"error": "upstream_unavailable", "detail": "8400"})

    assert "503" in ran.one("inspection_unavailable")["detail"]
    assert ran.one("task_finished")["state"] == COMPLETED


async def test_a_failed_task_is_never_inspected() -> None:
    ran = await inspected_pass(scripts={"s-1": [failed()]}, untouched=True)

    assert ran.run.state == FAILED
    assert "task_inspected" not in ran.names()
    assert "inspection_unavailable" not in ran.names()


async def test_a_task_parked_at_a_gate_is_never_inspected() -> None:
    ran = await inspected_pass(steps=(step_body(requires_confirmation=True),), untouched=True)

    assert ran.run.state == AWAITING
    assert "task_inspected" not in ran.names()


async def test_a_halted_task_is_never_inspected() -> None:
    ran = await inspected_pass(halt_after=0, untouched=True)

    assert ran.run.state == HALTED
    assert "task_inspected" not in ran.names()


async def test_a_pass_with_no_inspector_wired_finishes_as_before() -> None:
    ran = await inspected_pass(wired=False)

    assert "task_inspected" not in ran.names()
    assert "inspection_unavailable" not in ran.names()
    assert ran.task_states() == ["in_progress", "verifying", "done"]


class ClosingInspector(InspectorClient):
    closed = False

    async def close(self) -> None:
        ClosingInspector.closed = True

        await super().close()


async def test_closing_the_clients_closes_the_inspector() -> None:
    ClosingInspector.closed = False
    clients = Clients(
        FakeRouter(),
        FakeRunner(),
        FakeDevEnv(),
        FakeProject(),
        ClosingInspector("http://127.0.0.1:8450", 5.0, 1.0, transport=httpx.MockTransport(refused)),
    )

    await clients.close()

    assert ClosingInspector.closed
