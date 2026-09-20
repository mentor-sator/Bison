from __future__ import annotations

import json
import sys
from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest
from httpx import ASGITransport, AsyncClient

from task_runner_service import api, installs, venvs
from task_runner_service.installs import InstallerUnavailableError

SCOPE = r"C:\Users\dev\bison\projects\demo\workspace"


def effects(**overrides: object) -> dict[str, Any]:
    declared: dict[str, Any] = {
        "writes_paths": [],
        "deletes_paths": [],
        "network": True,
        "installs_packages": True,
        "needs_credentials": False,
        "drives_input": False,
        "reversible": True,
    }
    declared.update(overrides)

    return declared


def body(**overrides: object) -> dict[str, Any]:
    declared: dict[str, Any] = {
        "scope_root": SCOPE,
        "task_id": "t-1",
        "step": {"service": "task-runner", "effects": effects()},
        "confirmed": True,
        "packages": ["fastapi", "uvicorn[standard]"],
    }
    declared.update(overrides)

    return declared


class Recorded:
    def __init__(self) -> None:
        self.commands: list[list[str]] = []
        self.keys: list[str] = []


@pytest.fixture(autouse=True)
def clean_halt() -> Iterator[None]:
    api.halt_state.resume("test-setup")

    yield

    api.halt_state.resume("test-teardown")


@pytest.fixture
def client() -> AsyncClient:
    return AsyncClient(transport=ASGITransport(app=api.app), base_url="http://runner")


def fake_uv(monkeypatch: pytest.MonkeyPatch, tmp_path: Path, script: str) -> Recorded:
    recorded = Recorded()
    venv = tmp_path.resolve() / "envs" / "t-1"

    async def ensure(root: Path, key: str) -> Path:
        recorded.keys.append(key)

        return venv

    def command(uv: str, target: Path, packages: list[str]) -> list[str]:
        recorded.commands.append([uv, str(target), *packages])

        return [sys.executable, "-c", script]

    monkeypatch.setattr(installs, "installer", lambda: "uv")
    monkeypatch.setattr(installs, "command", command)
    monkeypatch.setattr(venvs, "ensure", ensure)

    return recorded


def events(payload: str) -> list[dict[str, Any]]:
    return [json.loads(line) for line in payload.splitlines() if line.strip()]


async def test_a_confirmed_install_streams_uv_output_then_a_result(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    recorded = fake_uv(
        monkeypatch, tmp_path, "import sys; sys.stderr.write('Installed 2 packages\\n')"
    )

    async with client:
        response = await client.post("/steps/s-1/install", json=body())

    streamed = events(response.text)

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("application/x-ndjson")
    assert streamed[0] == {
        "event": "output",
        "step_id": "s-1",
        "stream": "stderr",
        "sequence": 0,
        "text": "Installed 2 packages\n",
    }
    assert streamed[-1]["event"] == "result"
    assert streamed[-1]["exit_code"] == 0
    assert streamed[-1]["error_message"] is None
    assert streamed[-1]["packages"] == ["fastapi", "uvicorn[standard]"]
    assert recorded.commands[0][2:] == ["fastapi", "uvicorn[standard]"]


async def test_the_install_goes_into_the_environment_of_its_project(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    recorded = fake_uv(monkeypatch, tmp_path, "pass")

    async with client:
        await client.post("/steps/s-1/install", json=body())
        await client.post("/steps/s-2/install", json=body(task_id="t-2"))

    assert recorded.keys == [venvs.project_key(SCOPE), venvs.project_key(SCOPE)]


async def test_a_failed_install_is_a_failed_result_not_an_http_error(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    fake_uv(
        monkeypatch,
        tmp_path,
        "import sys; sys.stderr.write('No solution found\\n'); sys.exit(1)",
    )

    async with client:
        response = await client.post("/steps/s-1/install", json=body())

    result = events(response.text)[-1]

    assert response.status_code == 200
    assert result["exit_code"] == 1
    assert result["error_message"] == "uv exited 1: No solution found"


async def test_an_unconfirmed_install_is_refused_before_anything_runs(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    recorded = fake_uv(monkeypatch, tmp_path, "pass")

    async with client:
        response = await client.post("/steps/s-1/install", json=body(confirmed=False))

    assert response.status_code == 403
    assert "installs packages" in response.json()["detail"]
    assert recorded.commands == []


async def test_a_package_that_is_really_a_flag_is_refused(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    recorded = fake_uv(monkeypatch, tmp_path, "pass")

    async with client:
        response = await client.post(
            "/steps/s-1/install", json=body(packages=["fastapi", "--index-url=https://x.test"])
        )

    assert response.status_code == 422
    assert response.json()["detail"].startswith("packages[1]")
    assert recorded.commands == []


async def test_a_halted_runner_installs_nothing(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    recorded = fake_uv(monkeypatch, tmp_path, "pass")
    signal = {"id": "h-1", "reason": "kill_switch", "issued_at": datetime.now(UTC).isoformat()}

    async with client:
        await client.post("/halt", json=signal)
        response = await client.post("/steps/s-1/install", json=body())

    assert response.status_code == 409
    assert recorded.commands == []


async def test_a_machine_without_uv_says_so(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    def missing() -> str:
        raise InstallerUnavailableError()

    monkeypatch.setattr(installs, "installer", missing)

    async with client:
        response = await client.post("/steps/s-1/install", json=body())

    assert response.status_code == 503
    assert response.json()["detail"] == "uv is not on PATH; packages cannot be installed"
