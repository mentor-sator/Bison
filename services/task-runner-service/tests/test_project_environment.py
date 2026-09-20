from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from httpx import ASGITransport, AsyncClient

from task_runner_service import api, venvs
from task_runner_service.backends import Binding
from task_runner_service.execution import WorkspaceUnavailableError
from task_runner_service.sandbox import SandboxRequest
from task_runner_service.wasm import WasmSandbox

PROJECT = "c3e0f0fd-9222-436a-b673-5a6d8f6a4e52"
SCOPE = rf"C:\Users\dev\AppData\Local\BISON\projects\{PROJECT}\workspace"
OTHER = r"C:\Users\dev\AppData\Local\BISON\projects\0b1d6a2e-other\workspace"


def test_the_environment_is_named_after_the_project_that_owns_the_workspace() -> None:
    assert venvs.project_label(SCOPE) == PROJECT


def test_a_folder_that_is_not_a_bison_workspace_is_named_after_itself() -> None:
    assert venvs.project_label(r"D:\code\tracker") == "tracker"


def test_a_drive_root_still_gets_a_name() -> None:
    assert venvs.project_label("C:\\") == "project"


def test_every_task_of_a_project_shares_one_key() -> None:
    assert venvs.project_key(SCOPE) == venvs.project_key(SCOPE)


def test_two_projects_never_share_an_environment() -> None:
    assert venvs.project_key(SCOPE) != venvs.project_key(OTHER)


def test_the_same_workspace_written_differently_is_the_same_project() -> None:
    assert venvs.project_key(SCOPE) == venvs.project_key(SCOPE.upper() + "\\")


def test_the_environment_directory_is_readable_as_the_project(tmp_path: Path) -> None:
    folder = venvs.home(tmp_path, venvs.project_key(SCOPE))

    assert folder.name.startswith(PROJECT)
    assert folder.parent.name == venvs.VENV_DIRECTORY


@pytest.fixture(autouse=True)
def clean_halt() -> Iterator[None]:
    api.halt_state.resume("test-setup")

    yield

    api.halt_state.resume("test-teardown")


@pytest.fixture
def runs_dir(tmp_path: Path) -> Path:
    return tmp_path.resolve() / "runs"


@pytest.fixture
def client() -> AsyncClient:
    return AsyncClient(transport=ASGITransport(app=api.app), base_url="http://runner")


def run_body(task_id: str) -> dict[str, Any]:
    return {
        "scope_root": SCOPE,
        "task_id": task_id,
        "step": {
            "service": "task-runner",
            "effects": {
                "writes_paths": [],
                "deletes_paths": [],
                "network": False,
                "installs_packages": False,
                "needs_credentials": False,
                "drives_input": False,
                "reversible": True,
            },
        },
        "confirmed": False,
        "program": "python",
        "arguments": ["-c", "pass"],
    }


async def test_runs_from_different_tasks_are_given_the_project_environment(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch, runs_dir: Path
) -> None:
    sandbox = WasmSandbox(runtime_dir=runs_dir)
    binding = Binding(
        sandbox=sandbox, backend=sandbox.backend, preferred="wasm", degraded=False, reason=None
    )
    keys: list[str] = []

    def planned(request: SandboxRequest) -> Binding:
        return binding

    async def provision(request: SandboxRequest, key: str, chosen: Binding) -> SandboxRequest:
        keys.append(key)

        raise WorkspaceUnavailableError(request.working_directory, "stopped by the test")

    monkeypatch.setattr(api.runner, "plan", planned)
    monkeypatch.setattr(api.runner, "provision", provision)

    async with client:
        first = await client.post("/steps/s-1/run", json=run_body("task-0"))
        second = await client.post("/steps/s-2/run", json=run_body("task-2"))

    assert first.status_code == second.status_code == 503
    assert keys == [venvs.project_key(SCOPE), venvs.project_key(SCOPE)]
