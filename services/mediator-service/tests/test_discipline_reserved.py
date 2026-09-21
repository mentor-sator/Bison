from __future__ import annotations

import pytest

from mediator_service.checks import CheckSpec, FileExists, FileHash, HttpStatus, PortOpen, SqlResult
from mediator_service.discipline import (
    SUGGESTED_PORT,
    TreeRejectedError,
    assert_disciplined,
    review,
)
from mediator_service.tree import DraftCriterion, DraftTask, TreeDraft


def checked(spec: CheckSpec, statement: str = "The result is observable") -> DraftCriterion:
    return DraftCriterion(
        statement=statement, check_kind="deterministic", check_spec=spec, weight=1
    )


def tree(*criteria: DraftCriterion) -> TreeDraft:
    return TreeDraft(
        approach_summary="Serve the task API",
        tasks=(
            DraftTask(
                ref="api",
                parent_ref=None,
                title="Serve the API",
                description="",
                kind="code",
                assigned_role="engine",
                depends_on=(),
                criteria=criteria,
                position=0,
            ),
        ),
    )


def http(url: str) -> HttpStatus:
    return HttpStatus(url=url, expected_status=200, timeout_ms=2000)


@pytest.mark.parametrize("port", [8000, 8450, 8700, 9000])
def test_a_port_check_in_bison_s_range_is_rejected(port: int) -> None:
    findings = review(tree(checked(PortOpen(host="127.0.0.1", port=port))))

    assert len(findings) == 1
    assert f"checks port {port}, which belongs to BISON's own services" in findings[0]


@pytest.mark.parametrize("port", [5432, 7999, 9001, 9101])
def test_a_port_check_outside_the_range_is_accepted(port: int) -> None:
    assert review(tree(checked(PortOpen(host="127.0.0.1", port=port)))) == ()


def test_the_finding_names_a_port_the_model_may_use() -> None:
    findings = review(tree(checked(PortOpen(host="127.0.0.1", port=8000))))

    assert f"such as {SUGGESTED_PORT}" in findings[0]
    assert "above 9000" in findings[0]


def test_an_address_on_a_bison_port_is_rejected() -> None:
    findings = review(tree(checked(http("http://127.0.0.1:8000/tasks"))))

    assert "checks port 8000" in findings[0]


@pytest.mark.parametrize(
    "url",
    ["http://127.0.0.1:9101/tasks", "http://localhost/health", "https://example.com/"],
)
def test_an_address_outside_the_range_is_accepted(url: str) -> None:
    assert review(tree(checked(http(url)))) == ()


def test_an_address_whose_port_cannot_be_read_is_left_to_the_inspector() -> None:
    assert review(tree(checked(http("http://127.0.0.1:port/tasks")))) == ()


@pytest.mark.parametrize(
    "spec",
    [
        FileExists(path="<workspace>/venv/Scripts/python.exe"),
        FileExists(path="venv/Lib/site-packages/fastapi/__init__.py"),
        FileExists(path=".venv\\Scripts\\python.exe"),
        FileHash(path="C:\\work\\virtualenv\\pyvenv.cfg", expected_sha256="a" * 64),
        SqlResult(connection_ref="venv/data.db", query="SELECT 1", expect="1"),
    ],
)
def test_a_check_inside_a_virtual_environment_is_rejected(spec: CheckSpec) -> None:
    findings = review(tree(checked(spec)))

    assert len(findings) == 1
    assert "inside a virtual environment" in findings[0]


@pytest.mark.parametrize(
    "path", ["main.py", "data/tasks.db", "inventory.py", "venv_notes.md", "docs/env/setup.md"]
)
def test_a_path_that_only_resembles_an_environment_is_accepted(path: str) -> None:
    assert review(tree(checked(FileExists(path=path)))) == ()


def test_the_day_24_smoke_tree_is_sent_back_with_every_unsatisfiable_criterion() -> None:
    venv = "<workspace>/venv"
    smoke = tree(
        checked(FileExists(path=f"{venv}/Scripts/python.exe"), "Python executable exists"),
        checked(
            FileExists(path=f"{venv}/Lib/site-packages/fastapi/__init__.py"), "FastAPI present"
        ),
        checked(
            FileExists(path=f"{venv}/Lib/site-packages/uvicorn/__init__.py"), "Uvicorn present"
        ),
        checked(
            FileExists(path=f"{venv}/Lib/site-packages/pydantic/__init__.py"), "Pydantic present"
        ),
        checked(FileExists(path="<workspace>/db_helper.py"), "Helper module file exists"),
        checked(PortOpen(host="127.0.0.1", port=8000), "API binds to port 8000 on localhost"),
        checked(http("http://127.0.0.1:8000/tasks"), "GET /tasks returns 200 OK"),
    )

    with pytest.raises(TreeRejectedError) as caught:
        assert_disciplined(smoke)

    assert len(caught.value.findings) == 6
