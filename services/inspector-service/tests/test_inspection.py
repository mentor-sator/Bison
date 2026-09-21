from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from inspector_service.inspection import inspect_task
from inspector_service.upstream import Criterion

PROBE_SECONDS = 1.0
TASK = "t1"


class Projects:
    def __init__(self, criteria: list[Criterion]) -> None:
        self._criteria = criteria
        self.settled: list[tuple[str, str, str]] = []

    async def criteria(self, task_id: str) -> list[Criterion]:
        return [criterion for criterion in self._criteria if criterion.task_id == task_id]

    async def settle(self, criterion_id: str, status: str, reason: str) -> None:
        self.settled.append((criterion_id, status, reason))


def criterion(
    identity: str,
    spec: dict[str, Any] | None,
    status: str = "unverified",
    check_kind: str = "deterministic",
) -> Criterion:
    return Criterion(
        id=identity,
        task_id=TASK,
        statement=f"statement {identity}",
        check_kind=check_kind,
        check_spec=spec,
        status=status,
    )


def exists(path: str) -> dict[str, Any]:
    return {"type": "file_exists", "path": path}


@pytest.fixture
def workspace(tmp_path: Path) -> Path:
    root = tmp_path / "workspace"
    root.mkdir()
    (root / "db_helper.py").write_text("def create_task() -> None: ...\n", encoding="utf-8")

    return root


async def test_a_verified_criterion_is_written_back(workspace: Path) -> None:
    projects = Projects([criterion("c1", exists("<workspace>/db_helper.py"))])
    outcomes = await inspect_task(projects, TASK, workspace, PROBE_SECONDS)

    assert outcomes[0].status_after == "verified"
    assert projects.settled[0][:2] == ("c1", "verified")


async def test_a_failed_criterion_is_written_back_with_its_reason(workspace: Path) -> None:
    projects = Projects([criterion("c1", exists("<workspace>/venv/Scripts/python.exe"))])
    await inspect_task(projects, TASK, workspace, PROBE_SECONDS)

    identity, status, reason = projects.settled[0]

    assert (identity, status) == ("c1", "failed")
    assert "does not exist" in reason


async def test_an_inconclusive_verdict_leaves_the_status_alone(workspace: Path) -> None:
    projects = Projects([criterion("c1", {"type": "window_title", "pattern": "x"})])
    outcomes = await inspect_task(projects, TASK, workspace, PROBE_SECONDS)

    assert outcomes[0].verdict == "inconclusive"
    assert outcomes[0].status_after == "unverified"
    assert projects.settled == []


async def test_a_criterion_already_in_that_state_is_not_rewritten(workspace: Path) -> None:
    projects = Projects([criterion("c1", exists("db_helper.py"), status="verified")])
    outcomes = await inspect_task(projects, TASK, workspace, PROBE_SECONDS)

    assert projects.settled == []
    assert outcomes[0].changed is False


async def test_a_verified_criterion_that_broke_flips_to_failed(workspace: Path) -> None:
    projects = Projects([criterion("c1", exists("gone.py"), status="verified")])
    outcomes = await inspect_task(projects, TASK, workspace, PROBE_SECONDS)

    assert outcomes[0].status_after == "failed"
    assert outcomes[0].changed is True


async def test_an_inconclusive_verdict_never_takes_back_a_verified_one(workspace: Path) -> None:
    projects = Projects(
        [criterion("c1", {"type": "port_open", "host": "127.0.0.1", "port": 8000}, "verified")]
    )
    outcomes = await inspect_task(projects, TASK, workspace, PROBE_SECONDS)

    assert outcomes[0].status_after == "verified"
    assert projects.settled == []


async def test_an_ignored_criterion_is_not_inspected(workspace: Path) -> None:
    projects = Projects([criterion("c1", exists("gone.py"), status="ignored")])
    outcomes = await inspect_task(projects, TASK, workspace, PROBE_SECONDS)

    assert outcomes[0].verdict == "inconclusive"
    assert projects.settled == []


async def test_an_inspected_criterion_waits_for_the_model(workspace: Path) -> None:
    projects = Projects([criterion("c1", None, check_kind="inspected")])
    outcomes = await inspect_task(projects, TASK, workspace, PROBE_SECONDS)

    assert outcomes[0].verdict == "inconclusive"
    assert "inspector model" in outcomes[0].reason


async def test_a_deterministic_criterion_with_no_check_is_inconclusive(workspace: Path) -> None:
    projects = Projects([criterion("c1", None)])
    outcomes = await inspect_task(projects, TASK, workspace, PROBE_SECONDS)

    assert outcomes[0].verdict == "inconclusive"
    assert "could not be read" in outcomes[0].reason


async def test_every_criterion_of_the_task_is_inspected_in_order(workspace: Path) -> None:
    projects = Projects(
        [
            criterion("c1", exists("db_helper.py")),
            criterion("c2", exists("main.py")),
            criterion("c3", {"type": "text_on_screen", "text": "hi", "region": None}),
        ]
    )
    outcomes = await inspect_task(projects, TASK, workspace, PROBE_SECONDS)

    assert [outcome.verdict for outcome in outcomes] == ["verified", "failed", "inconclusive"]
