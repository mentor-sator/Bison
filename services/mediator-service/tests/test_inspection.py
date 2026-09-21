from __future__ import annotations

import json
from typing import Any

import httpx
import pytest

from mediator_service import api
from mediator_service.inspection import (
    Inspection,
    InspectorClient,
    InspectorError,
    InspectorUnreachableError,
    Verdict,
    to_inspection,
)

PROJECT_ID = "p-1"
TASK_ID = "t-1"
BASE_URL = "http://127.0.0.1:8450"


def result(
    criterion_id: str,
    verdict: str,
    status_before: str = "unverified",
    status_after: str | None = None,
) -> dict[str, Any]:
    return {
        "criterion_id": criterion_id,
        "task_id": TASK_ID,
        "statement": f"criterion {criterion_id} holds",
        "check_kind": "deterministic",
        "verdict": verdict,
        "reasoning": f"{criterion_id} was checked",
        "evidence": [],
        "status_before": status_before,
        "status_after": status_after if status_after is not None else status_before,
    }


def report(*results: dict[str, Any]) -> dict[str, Any]:
    return {
        "project_id": PROJECT_ID,
        "workspace": "C:\\workspace",
        "inspected_at": "2026-09-21T10:00:00+00:00",
        "verified": sum(1 for entry in results if entry["verdict"] == "verified"),
        "failed": sum(1 for entry in results if entry["verdict"] == "failed"),
        "inconclusive": sum(1 for entry in results if entry["verdict"] == "inconclusive"),
        "changed": sum(1 for entry in results if entry["status_before"] != entry["status_after"]),
        "results": list(results),
    }


class Inspector:
    def __init__(self, status: int = 200, body: Any = None, raw: bytes | None = None) -> None:
        self._status = status
        self._body = body if body is not None else report()
        self._raw = raw
        self.seen: list[tuple[str, str]] = []

    def handler(self, request: httpx.Request) -> httpx.Response:
        self.seen.append((request.method, request.url.path))

        if self._raw is not None:
            return httpx.Response(self._status, content=self._raw)

        return httpx.Response(self._status, content=json.dumps(self._body).encode("utf-8"))


async def inspect(inspector: Inspector) -> Inspection:
    client = InspectorClient(BASE_URL, 5.0, 1.0, transport=httpx.MockTransport(inspector.handler))

    try:
        return await client.inspect_task(PROJECT_ID, TASK_ID)
    finally:
        await client.close()


def unreachable(request: httpx.Request) -> httpx.Response:
    raise httpx.ConnectError("connection refused", request=request)


async def test_the_task_route_is_posted_to() -> None:
    inspector = Inspector()

    await inspect(inspector)

    assert inspector.seen == [("POST", f"/projects/{PROJECT_ID}/tasks/{TASK_ID}/inspect")]


async def test_every_result_becomes_a_verdict_in_order() -> None:
    inspection = await inspect(
        Inspector(
            body=report(
                result("c-1", "verified", "unverified", "verified"), result("c-2", "inconclusive")
            )
        )
    )

    assert [entry.criterion_id for entry in inspection.verdicts] == ["c-1", "c-2"]
    assert inspection.verdicts[0] == Verdict(
        criterion_id="c-1",
        statement="criterion c-1 holds",
        verdict="verified",
        reasoning="c-1 was checked",
        status_before="unverified",
        status_after="verified",
    )


async def test_counts_come_from_the_verdicts_themselves() -> None:
    inspection = await inspect(
        Inspector(
            body=report(
                result("c-1", "verified", "unverified", "verified"),
                result("c-2", "failed", "verified", "failed"),
                result("c-3", "failed", "failed", "failed"),
                result("c-4", "inconclusive"),
            )
        )
    )

    assert (inspection.verified, inspection.failed, inspection.inconclusive) == (1, 2, 1)
    assert inspection.changed == 2


async def test_an_empty_report_is_an_inspection_of_nothing() -> None:
    inspection = await inspect(Inspector())

    assert inspection.verdicts == ()
    assert inspection.changed == 0


def test_entries_that_are_not_objects_are_dropped() -> None:
    inspection = to_inspection(TASK_ID, {"results": ["noise", 3, result("c-1", "verified")]})

    assert [entry.criterion_id for entry in inspection.verdicts] == ["c-1"]


def test_a_report_without_results_reads_as_empty() -> None:
    assert to_inspection(TASK_ID, {"results": "nope"}).verdicts == ()


def test_a_verdict_payload_round_trips() -> None:
    verdict = to_inspection(
        TASK_ID, report(result("c-1", "failed", "verified", "failed"))
    ).verdicts[0]

    assert verdict.payload() == {
        "criterion_id": "c-1",
        "statement": "criterion c-1 holds",
        "verdict": "failed",
        "reasoning": "c-1 was checked",
        "status_before": "verified",
        "status_after": "failed",
    }


async def test_a_refusal_keeps_the_status_and_the_detail() -> None:
    with pytest.raises(InspectorError) as raised:
        await inspect(Inspector(status=404, body={"error": "task_not_found", "detail": "t-1"}))

    assert raised.value.status == 404
    assert raised.value.detail == "t-1"


async def test_a_body_that_is_not_json_is_refused() -> None:
    with pytest.raises(InspectorError, match="non-JSON"):
        await inspect(Inspector(raw=b"<html>"))


async def test_a_body_that_is_not_an_object_is_refused() -> None:
    with pytest.raises(InspectorError, match="non-object"):
        await inspect(Inspector(body=[1, 2]))


async def test_an_unreachable_inspector_names_where_it_looked() -> None:
    client = InspectorClient(BASE_URL, 5.0, 1.0, transport=httpx.MockTransport(unreachable))

    try:
        with pytest.raises(InspectorUnreachableError, match="8450"):
            await client.inspect_task(PROJECT_ID, TASK_ID)
    finally:
        await client.close()


async def test_a_run_is_wired_to_the_inspector() -> None:
    clients = api.clients_for_run()

    try:
        assert isinstance(clients.inspector, InspectorClient)
    finally:
        await clients.close()


async def test_health_names_the_inspector() -> None:
    transport = httpx.ASGITransport(app=api.app)

    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/health")

    assert response.json()["inspector"] == "http://127.0.0.1:8450"
