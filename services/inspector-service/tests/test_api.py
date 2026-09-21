from __future__ import annotations

from collections.abc import AsyncIterator
from pathlib import Path

import httpx
import pytest

import inspector_service
from inspector_service.api import app
from inspector_service.config import Settings, settings
from inspector_service.upstream import Criterion, ProjectNotFoundError, Task

PROJECT = "p1"
SOURCE = Path(inspector_service.__file__).parent


class Projects:
    def __init__(self) -> None:
        self.settled: list[tuple[str, str]] = []

    async def tasks(self, project_id: str) -> list[Task]:
        if project_id != PROJECT:
            raise ProjectNotFoundError(project_id)

        return [
            Task(id="t1", title="Helper", state="done"),
            Task(id="t2", title="API", state="done"),
        ]

    async def criteria(self, task_id: str) -> list[Criterion]:
        spec = {"type": "file_exists", "path": f"<workspace>/{task_id}.py"}

        return [
            Criterion(
                id=f"{task_id}-c1",
                task_id=task_id,
                statement=f"{task_id}.py exists",
                check_kind="deterministic",
                check_spec=spec,
                status="unverified",
            )
        ]

    async def settle(self, criterion_id: str, status: str, reason: str) -> None:
        self.settled.append((criterion_id, status))

    async def close(self) -> None:
        return None


@pytest.fixture
def workspace(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    monkeypatch.setattr(settings(), "workspace_root", tmp_path)
    root = tmp_path / PROJECT / "workspace"
    root.mkdir(parents=True)
    (root / "t1.py").write_text("x = 1\n", encoding="utf-8")

    return root


@pytest.fixture
async def client(workspace: Path) -> AsyncIterator[tuple[httpx.AsyncClient, Projects]]:
    fake = Projects()
    app.state.projects = fake
    transport = httpx.ASGITransport(app=app)

    async with httpx.AsyncClient(transport=transport, base_url="http://inspector") as running:
        yield running, fake


async def test_health_names_the_service(client: tuple[httpx.AsyncClient, Projects]) -> None:
    running, _ = client
    body = (await running.get("/health")).json()

    assert body["service"] == "inspector-service"
    assert body["status"] == "ok"


def test_the_default_port_is_8450() -> None:
    assert Settings().port == 8450


async def test_a_project_is_inspected_task_by_task(
    client: tuple[httpx.AsyncClient, Projects],
) -> None:
    running, fake = client
    body = (await running.post(f"/projects/{PROJECT}/inspect")).json()

    assert (body["verified"], body["failed"], body["inconclusive"]) == (1, 1, 0)
    assert body["changed"] == 2
    assert fake.settled == [("t1-c1", "verified"), ("t2-c1", "failed")]


async def test_a_result_carries_its_reasoning_and_evidence(
    client: tuple[httpx.AsyncClient, Projects],
) -> None:
    running, _ = client
    first = (await running.post(f"/projects/{PROJECT}/inspect")).json()["results"][0]

    assert first["verdict"] == "verified"
    assert first["status_before"] == "unverified"
    assert first["status_after"] == "verified"
    assert first["evidence"][0]["kind"] == "file_hash"
    assert first["reasoning"].endswith("exists")


async def test_one_task_is_inspected_alone(client: tuple[httpx.AsyncClient, Projects]) -> None:
    running, fake = client
    body = (await running.post(f"/projects/{PROJECT}/tasks/t2/inspect")).json()

    assert [result["criterion_id"] for result in body["results"]] == ["t2-c1"]
    assert fake.settled == [("t2-c1", "failed")]


async def test_the_report_names_the_workspace_it_read(
    client: tuple[httpx.AsyncClient, Projects], workspace: Path
) -> None:
    running, _ = client
    body = (await running.post(f"/projects/{PROJECT}/inspect")).json()

    assert body["workspace"] == str(workspace)


async def test_a_task_from_another_project_is_not_found(
    client: tuple[httpx.AsyncClient, Projects],
) -> None:
    running, _ = client
    response = await running.post(f"/projects/{PROJECT}/tasks/t9/inspect")

    assert response.status_code == 404
    assert response.json()["error"] == "task_not_found"


async def test_an_unknown_project_is_not_found(client: tuple[httpx.AsyncClient, Projects]) -> None:
    running, _ = client
    response = await running.post("/projects/absent/inspect")

    assert response.status_code == 404
    assert response.json()["error"] == "project_not_found"


def test_the_inspector_has_no_way_to_reach_the_router() -> None:
    assert not [name for name in Settings.model_fields if "router" in name]


@pytest.mark.parametrize("marker", ["router", "8600", "confirm"])
def test_no_source_file_mentions_an_authorization_surface(marker: str) -> None:
    offending = [
        path.name
        for path in SOURCE.glob("*.py")
        if marker in path.read_text(encoding="utf-8").lower()
    ]

    assert offending == []


def test_the_inspector_offers_no_route_that_approves_anything() -> None:
    paths = [getattr(route, "path", "") for route in app.routes]

    assert not [path for path in paths if "confirm" in path or "approve" in path]
