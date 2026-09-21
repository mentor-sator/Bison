from __future__ import annotations

import hashlib
import sqlite3
from contextlib import closing
from pathlib import Path

import pytest

from inspector_service.checks import FileExists, FileHash, SqlResult, Unobserved
from inspector_service.runners import located, run

PROBE_SECONDS = 1.0

SMOKE_QUERY = "SELECT name FROM sqlite_masterWHERE type='table' AND name='tasks';"


@pytest.fixture
def workspace(tmp_path: Path) -> Path:
    root = tmp_path / "workspace"
    root.mkdir()

    return root


def database(workspace: Path, name: str = "tasks.db") -> Path:
    path = workspace / name

    with closing(sqlite3.connect(path)) as link:
        link.execute("CREATE TABLE tasks (id INTEGER PRIMARY KEY, title TEXT)")
        link.execute("INSERT INTO tasks (title) VALUES ('Test Task')")
        link.commit()

    return path


def test_the_workspace_placeholder_resolves_to_the_workspace(workspace: Path) -> None:
    assert located("<workspace>/db_helper.py", workspace) == (workspace / "db_helper.py").resolve()


def test_the_placeholder_is_matched_whatever_its_case(workspace: Path) -> None:
    assert located("<WORKSPACE>\\run.py", workspace) == (workspace / "run.py").resolve()


def test_a_relative_path_resolves_inside_the_workspace(workspace: Path) -> None:
    assert located("src/api.py", workspace) == (workspace / "src" / "api.py").resolve()


def test_a_path_that_climbs_out_is_refused(workspace: Path) -> None:
    assert located("<workspace>/../secret.txt", workspace) is None


def test_an_absolute_path_elsewhere_is_refused(workspace: Path, tmp_path: Path) -> None:
    assert located(str(tmp_path / "elsewhere.txt"), workspace) is None


def test_an_existing_file_is_verified_with_its_digest(workspace: Path) -> None:
    (workspace / "main.py").write_bytes(b"print('hi')\n")
    digest = hashlib.sha256(b"print('hi')\n").hexdigest()
    finding = run(FileExists(path="<workspace>/main.py"), workspace, PROBE_SECONDS)

    assert finding.verdict == "verified"
    assert finding.evidence_kind == "file_hash"
    assert finding.excerpt == f"sha256 {digest}"


def test_an_existing_folder_is_verified(workspace: Path) -> None:
    (workspace / "static").mkdir()

    assert run(FileExists(path="static"), workspace, PROBE_SECONDS).verdict == "verified"


def test_a_missing_file_fails(workspace: Path) -> None:
    finding = run(FileExists(path="<workspace>/venv/Scripts/python.exe"), workspace, PROBE_SECONDS)

    assert finding.verdict == "failed"
    assert "does not exist" in finding.reason


def test_a_file_outside_the_workspace_is_inconclusive(workspace: Path, tmp_path: Path) -> None:
    (tmp_path / "elsewhere.txt").write_text("x", encoding="utf-8")
    finding = run(FileExists(path=str(tmp_path / "elsewhere.txt")), workspace, PROBE_SECONDS)

    assert finding.verdict == "inconclusive"
    assert "outside the project workspace" in finding.reason


def test_a_matching_digest_is_verified(workspace: Path) -> None:
    (workspace / "data.txt").write_bytes(b"payload")
    digest = hashlib.sha256(b"payload").hexdigest()
    finding = run(FileHash(path="data.txt", expected_sha256=digest), workspace, PROBE_SECONDS)

    assert finding.verdict == "verified"


def test_a_different_digest_fails_and_names_both(workspace: Path) -> None:
    (workspace / "data.txt").write_bytes(b"payload")
    finding = run(FileHash(path="data.txt", expected_sha256="0" * 64), workspace, PROBE_SECONDS)

    assert finding.verdict == "failed"
    assert "0" * 64 in finding.reason
    assert hashlib.sha256(b"payload").hexdigest() in finding.reason


def test_a_digest_of_a_missing_file_fails(workspace: Path) -> None:
    finding = run(FileHash(path="gone.txt", expected_sha256="0" * 64), workspace, PROBE_SECONDS)

    assert finding.verdict == "failed"


def test_a_query_returning_the_expected_value_is_verified(workspace: Path) -> None:
    database(workspace)
    spec = SqlResult(
        connection_ref="<workspace>/tasks.db",
        query="SELECT COUNT(*) FROM tasks WHERE title='Test Task';",
        expect="1",
    )
    finding = run(spec, workspace, PROBE_SECONDS)

    assert finding.verdict == "verified"
    assert finding.evidence_kind == "sql_result"


def test_a_query_returning_something_else_fails(workspace: Path) -> None:
    database(workspace)
    spec = SqlResult(connection_ref="tasks.db", query="SELECT COUNT(*) FROM tasks", expect="5")
    finding = run(spec, workspace, PROBE_SECONDS)

    assert finding.verdict == "failed"
    assert "returned 1, not 5" in finding.reason


def test_a_query_returning_no_rows_fails(workspace: Path) -> None:
    database(workspace)
    spec = SqlResult(
        connection_ref="tasks.db",
        query="SELECT name FROM sqlite_master WHERE name='absent'",
        expect="absent",
    )

    assert "no rows" in run(spec, workspace, PROBE_SECONDS).reason


def test_a_missing_database_fails_without_creating_one(workspace: Path) -> None:
    spec = SqlResult(connection_ref="<workspace>/tasks.db", query="SELECT 1", expect="1")
    finding = run(spec, workspace, PROBE_SECONDS)

    assert finding.verdict == "failed"
    assert not (workspace / "tasks.db").exists()


def test_a_query_that_cannot_run_is_inconclusive(workspace: Path) -> None:
    database(workspace)
    spec = SqlResult(connection_ref="<workspace>/tasks.db", query=SMOKE_QUERY, expect="tasks")
    finding = run(spec, workspace, PROBE_SECONDS)

    assert finding.verdict == "inconclusive"
    assert "could not run" in finding.reason


def test_the_database_is_opened_read_only(workspace: Path) -> None:
    path = database(workspace)
    spec = SqlResult(connection_ref="tasks.db", query="DELETE FROM tasks", expect="0")
    finding = run(spec, workspace, PROBE_SECONDS)

    with closing(sqlite3.connect(path)) as link:
        remaining = link.execute("SELECT COUNT(*) FROM tasks").fetchone()[0]

    assert finding.verdict == "inconclusive"
    assert remaining == 1


def test_a_database_server_reference_is_inconclusive(workspace: Path) -> None:
    spec = SqlResult(
        connection_ref="postgresql://127.0.0.1:5432/tasks", query="SELECT 1", expect="1"
    )

    assert run(spec, workspace, PROBE_SECONDS).verdict == "inconclusive"


@pytest.mark.parametrize("kind", ["process_exit", "window_title", "text_on_screen"])
def test_a_check_the_inspector_cannot_observe_is_inconclusive(kind: str, workspace: Path) -> None:
    finding = run(Unobserved(kind=kind), workspace, PROBE_SECONDS)

    assert finding.verdict == "inconclusive"
    assert kind in finding.reason
