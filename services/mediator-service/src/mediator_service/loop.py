from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Final

from bison_contracts.halt import HaltState

from mediator_service import events, sequencing
from mediator_service.events import Emitter
from mediator_service.execution import (
    AWAITING,
    COMPLETED,
    FAILED,
    HALTED,
    UPSTREAM_FAILURES,
    Clients,
    Resumption,
    TaskPass,
)
from mediator_service.sequencing import Node, Ordering, SequencingError
from mediator_service.upstream import Outcome, Task

DONE: Final[str] = "done"
SETTLED_STATES: Final[frozenset[str]] = frozenset({"done", "failed", "skipped", "ignored"})

SETTLED_ORDER: Final[tuple[str, ...]] = ("done", "failed", "skipped", "ignored")

DEFAULT_HALT_REASON: Final[str] = "user_stop"
NO_TASKS: Final[str] = "this project has no tasks to run"
RESET_HINT: Final[str] = "set a task back to ready to run it again"


def waiting_phrase(count: int) -> str:
    return "1 task waits" if count == 1 else f"{count} tasks wait"


def settled_phrase(states: list[str]) -> str:
    counts = [(state, states.count(state)) for state in SETTLED_ORDER]

    return ", ".join(f"{count} {state}" for state, count in counts if count)


def run_summary(ran: int, settled_before: list[str], waiting: int) -> str | None:
    if ran == 0 and waiting == 0:
        return (
            f"nothing to run: every task is already settled "
            f"({settled_phrase(settled_before)}); {RESET_HINT}"
        )

    if ran == 0:
        return f"nothing to run: {waiting_phrase(waiting)} on a task that did not finish"

    if waiting:
        return f"{waiting_phrase(waiting)} on a task that did not finish, so it did not run"

    return None


def nodes_of(tasks: tuple[Task, ...]) -> list[Node]:
    return [
        Node(
            id=task.id,
            parent_id=task.parent_id,
            depends_on=task.depends_on,
            position=task.position,
        )
        for task in tasks
    ]


class RunLoop:
    def __init__(
        self,
        clients: Clients,
        halt: HaltState,
        project_id: str,
        request_id: str,
        resumption: Resumption | None = None,
    ) -> None:
        self._clients = clients
        self._halt = halt
        self._project_id = project_id
        self._request_id = request_id
        self._resumption = resumption
        self._emitter = Emitter(request_id, project_id)
        self.tasks_completed = 0
        self.tasks_failed = 0
        self.tasks_total = 0
        self.awaiting_task_id: str | None = None
        self.halted_task_id: str | None = None

    async def stream(self) -> AsyncIterator[bytes]:
        try:
            tasks = await self._clients.project.tasks(self._project_id)
        except UPSTREAM_FAILURES as failure:
            yield self._emitter.emit(events.error(str(failure)))

            return

        try:
            ordering = sequencing.build(nodes_of(tasks))
        except SequencingError as failure:
            yield self._emitter.emit(events.error(failure.detail))

            return

        if not ordering.order:
            yield self._emitter.emit(events.error(NO_TASKS))

            return

        self.tasks_total = len(ordering.order)

        yield self._emitter.emit(events.run_started(ordering.order))

        async for chunk in self._walk(ordering, {task.id: task for task in tasks}):
            yield chunk

    async def _walk(self, ordering: Ordering, index: dict[str, Task]) -> AsyncIterator[bytes]:
        leaves = ordering.leaves
        succeeded = frozenset(
            task_id for task_id in leaves if task_id in index and index[task_id].state == DONE
        )
        attempted = {
            task_id
            for task_id in leaves
            if task_id in index and index[task_id].state in SETTLED_STATES
        }
        settled_before = [index[task_id].state for task_id in attempted]

        while True:
            if self._halt.halted:
                async for chunk in self._stop(None, ()):
                    yield chunk

                return

            task_id = self._next(ordering, succeeded, attempted, index)

            if task_id is None:
                break

            walker = TaskPass(
                self._clients,
                self._emitter,
                self._project_id,
                self._request_id,
                index[task_id],
                ordering.order.index(task_id),
                self.tasks_total,
                lambda: self._halt.halted,
                resumption=self._take(task_id),
            )

            async for chunk in walker.stream():
                yield chunk

            attempted.add(task_id)

            if walker.state == COMPLETED:
                succeeded = succeeded | {task_id}
                self.tasks_completed += 1

                continue

            if walker.state == FAILED:
                self.tasks_failed += 1

                continue

            if walker.state == AWAITING:
                self.awaiting_task_id = task_id

                break

            if walker.state == HALTED:
                async for chunk in self._stop(task_id, walker.outcomes):
                    yield chunk

                return

        summary = None

        if self.awaiting_task_id is None:
            summary = run_summary(
                self.tasks_completed + self.tasks_failed,
                settled_before,
                len(leaves - attempted),
            )

        yield self._emitter.emit(
            events.run_finished(
                self.tasks_completed,
                self.tasks_failed,
                self.tasks_total,
                await self._percentage(),
                summary,
            )
        )

    def _next(
        self,
        ordering: Ordering,
        succeeded: frozenset[str],
        attempted: set[str],
        index: dict[str, Task],
    ) -> str | None:
        resuming = self._resumption

        if resuming is not None:
            parked = resuming.plan.task_id

            if parked in index and parked not in attempted:
                return parked

            self._resumption = None

        for task_id in ordering.ready(succeeded):
            if task_id not in attempted:
                return task_id

        return None

    def _take(self, task_id: str) -> Resumption | None:
        pending = self._resumption

        if pending is None or pending.plan.task_id != task_id:
            return None

        self._resumption = None

        return pending

    async def _stop(
        self, task_id: str | None, outcomes: tuple[Outcome, ...]
    ) -> AsyncIterator[bytes]:
        self.halted_task_id = task_id
        record_id: str | None = None

        if task_id is not None:
            try:
                record_id = await self._clients.project.write_record(
                    task_id, self._request_id, self._reason(), outcomes
                )
            except UPSTREAM_FAILURES:
                record_id = None

        yield self._emitter.emit(events.halted(self._reason(), task_id, record_id))

    def _reason(self) -> str:
        signal = self._halt.status().signal

        return signal.reason if signal is not None else DEFAULT_HALT_REASON

    async def _percentage(self) -> float:
        try:
            snapshot = await self._clients.project.progress(self._project_id)
        except UPSTREAM_FAILURES:
            return 0.0

        return snapshot.overall.percentage
