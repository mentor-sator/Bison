from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Final

import httpx

SERVICE: Final[str] = "project-service"
ACTOR: Final[str] = "inspector"


class UpstreamError(RuntimeError):
    def __init__(self, detail: str) -> None:
        super().__init__(f"{SERVICE}: {detail}")
        self.detail = detail


class ProjectNotFoundError(UpstreamError):
    def __init__(self, project_id: str) -> None:
        super().__init__(f"project {project_id} not found")


class TaskNotFoundError(UpstreamError):
    def __init__(self, task_id: str) -> None:
        super().__init__(f"task {task_id} is not in this project")


@dataclass(frozen=True)
class Task:
    id: str
    title: str
    state: str


@dataclass(frozen=True)
class Criterion:
    id: str
    task_id: str
    statement: str
    check_kind: str
    check_spec: dict[str, Any] | None
    status: str


def text(payload: dict[str, Any], key: str) -> str:
    value = payload.get(key)

    return value if isinstance(value, str) else ""


def to_task(payload: dict[str, Any]) -> Task:
    return Task(id=text(payload, "id"), title=text(payload, "title"), state=text(payload, "state"))


def to_criterion(payload: dict[str, Any]) -> Criterion:
    spec = payload.get("check_spec")

    return Criterion(
        id=text(payload, "id"),
        task_id=text(payload, "task_id"),
        statement=text(payload, "statement"),
        check_kind=text(payload, "check_kind"),
        check_spec=spec if isinstance(spec, dict) else None,
        status=text(payload, "status"),
    )


class ProjectClient:
    def __init__(self, base_url: str, timeout_seconds: float, connect_timeout: float) -> None:
        self._timeout = httpx.Timeout(timeout_seconds, connect=connect_timeout)
        self._client = httpx.AsyncClient(base_url=base_url.rstrip("/"))

    async def close(self) -> None:
        await self._client.aclose()

    async def tasks(self, project_id: str) -> list[Task]:
        path = f"/projects/{project_id}/tasks"
        response = await self._send("GET", path)

        if response.status_code == httpx.codes.NOT_FOUND:
            raise ProjectNotFoundError(project_id)

        return [to_task(entry) for entry in self._array(response, path)]

    async def criteria(self, task_id: str) -> list[Criterion]:
        path = f"/tasks/{task_id}/criteria"
        response = await self._send("GET", path)

        if response.status_code == httpx.codes.NOT_FOUND:
            raise TaskNotFoundError(task_id)

        return [to_criterion(entry) for entry in self._array(response, path)]

    async def settle(self, criterion_id: str, status: str, reason: str) -> None:
        path = f"/criteria/{criterion_id}/status"
        body = {"status": status, "reason": reason, "actor": ACTOR}
        response = await self._send("POST", path, body)

        if response.status_code >= httpx.codes.BAD_REQUEST:
            raise UpstreamError(f"{path} responded {response.status_code}")

    async def _send(
        self, method: str, path: str, body: dict[str, Any] | None = None
    ) -> httpx.Response:
        try:
            return await self._client.request(method, path, json=body, timeout=self._timeout)
        except httpx.HTTPError as error:
            raise UpstreamError(f"{path} unreachable") from error

    @staticmethod
    def _array(response: httpx.Response, path: str) -> list[dict[str, Any]]:
        if response.status_code >= httpx.codes.BAD_REQUEST:
            raise UpstreamError(f"{path} responded {response.status_code}")

        parsed: Any = response.json()

        if not isinstance(parsed, list):
            raise UpstreamError(f"{path} returned a non-array body")

        return [entry for entry in parsed if isinstance(entry, dict)]
