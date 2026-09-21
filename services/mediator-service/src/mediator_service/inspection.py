from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Final

import httpx

from mediator_service.dispatch import reason
from mediator_service.upstream import text

VERIFIED: Final[str] = "verified"
FAILED: Final[str] = "failed"
INCONCLUSIVE: Final[str] = "inconclusive"


class InspectorError(RuntimeError):
    def __init__(self, status: int, detail: str) -> None:
        super().__init__(f"inspector-service responded {status}: {detail}")
        self.status = status
        self.detail = detail


class InspectorUnreachableError(RuntimeError):
    def __init__(self, base_url: str) -> None:
        super().__init__(f"inspector-service unreachable at {base_url}")
        self.base_url = base_url


INSPECTION_FAILURES: Final[tuple[type[Exception], ...]] = (
    InspectorError,
    InspectorUnreachableError,
)


@dataclass(frozen=True)
class Verdict:
    criterion_id: str
    statement: str
    verdict: str
    reasoning: str
    status_before: str
    status_after: str

    @property
    def changed(self) -> bool:
        return self.status_before != self.status_after

    def payload(self) -> dict[str, Any]:
        return {
            "criterion_id": self.criterion_id,
            "statement": self.statement,
            "verdict": self.verdict,
            "reasoning": self.reasoning,
            "status_before": self.status_before,
            "status_after": self.status_after,
        }


@dataclass(frozen=True)
class Inspection:
    task_id: str
    verdicts: tuple[Verdict, ...]

    def count(self, verdict: str) -> int:
        return sum(1 for entry in self.verdicts if entry.verdict == verdict)

    @property
    def verified(self) -> int:
        return self.count(VERIFIED)

    @property
    def failed(self) -> int:
        return self.count(FAILED)

    @property
    def inconclusive(self) -> int:
        return self.count(INCONCLUSIVE)

    @property
    def changed(self) -> int:
        return sum(1 for entry in self.verdicts if entry.changed)


def to_verdict(payload: dict[str, Any]) -> Verdict:
    return Verdict(
        criterion_id=text(payload, "criterion_id"),
        statement=text(payload, "statement"),
        verdict=text(payload, "verdict"),
        reasoning=text(payload, "reasoning"),
        status_before=text(payload, "status_before"),
        status_after=text(payload, "status_after"),
    )


def to_inspection(task_id: str, payload: dict[str, Any]) -> Inspection:
    entries = payload.get("results")
    listed = entries if isinstance(entries, list) else []

    return Inspection(
        task_id=task_id,
        verdicts=tuple(to_verdict(entry) for entry in listed if isinstance(entry, dict)),
    )


class InspectorClient:
    def __init__(
        self,
        base_url: str,
        timeout_seconds: float,
        connect_timeout: float,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._timeout = httpx.Timeout(timeout_seconds, connect=connect_timeout)
        self._client = httpx.AsyncClient(base_url=self._base_url, transport=transport)

    async def close(self) -> None:
        await self._client.aclose()

    async def inspect_task(self, project_id: str, task_id: str) -> Inspection:
        path = f"/projects/{project_id}/tasks/{task_id}/inspect"

        try:
            response = await self._client.post(path, timeout=self._timeout)
        except httpx.HTTPError as error:
            raise InspectorUnreachableError(self._base_url) from error

        if response.status_code >= httpx.codes.BAD_REQUEST:
            raise InspectorError(response.status_code, reason(response))

        try:
            parsed: Any = response.json()
        except ValueError as error:
            raise InspectorError(
                response.status_code, f"{path} returned a non-JSON body"
            ) from error

        if not isinstance(parsed, dict):
            raise InspectorError(response.status_code, f"{path} returned a non-object body")

        return to_inspection(task_id, parsed)
