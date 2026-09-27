from __future__ import annotations

from typing import Any

import pytest

from router_service.actions import OpenInEditor, RunPythonModule, RunPythonScript, WriteFile
from router_service.context import Criterion, WorkspaceFile, render_criterion
from router_service.gating import Disk, PlanRejectedError, Presence, anchored_path, build
from router_service.plan import Effects, ProposedStep, RouterDraft
from router_service.upstream import to_criterion

SCOPE = r"C:\Users\dev\bison\projects\p-1\workspace"
DB = f"{SCOPE}\\db.py"
SEED = f"{SCOPE}\\seed.py"
ROWS = "c-rows"
EXISTS = "c-exists"

DB_SOURCE = (
    "import sqlite3\n\n\n"
    "def init_db():\n    return None\n\n\n"
    "def add_task(title):\n    return title\n\n\n"
    "def list_tasks():\n    return []\n"
)

SEED_SOURCE = (
    "import db\n\n\n"
    "def seed_tasks():\n"
    "    if not db.list_tasks():\n"
    "        db.add_task('Task 1')\n\n\n"
    "if __name__ == '__main__':\n"
    "    seed_tasks()\n"
)

BROKEN_SEED = (
    "import db\n\ndef seed_tasks():\n    tasks = db.list_tasks()\n    if not tasks:\n"
    " db.add_task('Task 1')\n        db.add_task('Task 2')\n"
)


def effects(writes: list[str] | None = None) -> Effects:
    return Effects(
        writes_paths=writes or [],
        deletes_paths=[],
        network=False,
        installs_packages=False,
        needs_credentials=False,
        drives_input=False,
        reversible=True,
    )


def writes(path: str, content: str, refs: tuple[str, ...] = ()) -> ProposedStep:
    return ProposedStep(
        description=f"Write {path}",
        service="task-runner",
        action=WriteFile(path=path, content=content),
        effects=effects([path]),
        on_failure="abort",
        criterion_refs=list(refs),
    )


def runs(path: str, refs: tuple[str, ...] = ()) -> ProposedStep:
    return ProposedStep(
        description=f"Run {path}",
        service="task-runner",
        action=RunPythonScript(script_path=path, arguments=()),
        effects=effects(),
        on_failure="abort",
        criterion_refs=list(refs),
    )


def module_run(refs: tuple[str, ...]) -> ProposedStep:
    return ProposedStep(
        description="Run the tests",
        service="task-runner",
        action=RunPythonModule(module="pytest", arguments=("-q",)),
        effects=effects(),
        on_failure="abort",
        criterion_refs=list(refs),
    )


def opens(path: str) -> ProposedStep:
    return ProposedStep(
        description=f"Open {path}",
        service="dev-env",
        action=OpenInEditor(path=path, line=None),
        effects=effects(),
        on_failure="abort",
        criterion_refs=[],
    )


def draft(*steps: ProposedStep) -> RouterDraft:
    return RouterDraft(intent="dev_task", rationale="the task asks for a script", steps=list(steps))


def criterion(
    criterion_id: str,
    spec: dict[str, Any] | None,
    status: str = "unverified",
    check_kind: str = "deterministic",
) -> Criterion:
    return Criterion(
        criterion_id=criterion_id,
        statement=f"statement for {criterion_id}",
        check_kind=check_kind,
        status=status,
        check_spec=spec,
    )


ROWS_CHECK = {
    "type": "sql_result",
    "connection_ref": "tasks.db",
    "query": "SELECT COUNT(*) FROM tasks",
    "expect": "3",
}


def nothing(path: str) -> Presence:
    return "missing"


def disk_with(*files: str) -> Disk:
    present = {entry.lower() for entry in files}

    def probe(path: str) -> Presence:
        return "file" if path.lower() in present else "missing"

    return probe


def test_a_relative_write_is_anchored_to_the_scope_root() -> None:
    plan = build(draft(writes("seed.py", SEED_SOURCE, (EXISTS,))), SCOPE, [EXISTS], nothing)
    action = plan.steps[0].action

    assert isinstance(action, WriteFile)
    assert action.path == SEED
    assert plan.steps[0].effects.writes_paths == [SEED]
    assert plan.steps[0].requires_confirmation is False


def test_a_relative_script_is_anchored_and_still_follows_its_write() -> None:
    plan = build(
        draft(writes("seed.py", SEED_SOURCE), runs("seed.py", (ROWS,))),
        SCOPE,
        [ROWS],
        nothing,
        criteria=[criterion(ROWS, ROWS_CHECK)],
    )
    action = plan.steps[1].action

    assert isinstance(action, RunPythonScript)
    assert action.script_path == SEED


def test_a_relative_open_is_anchored() -> None:
    plan = build(
        draft(writes("seed.py", SEED_SOURCE, (EXISTS,)), opens("seed.py")),
        SCOPE,
        [EXISTS],
        nothing,
    )
    action = plan.steps[1].action

    assert isinstance(action, OpenInEditor)
    assert action.path == SEED


def test_an_absolute_path_is_left_as_written() -> None:
    assert anchored_path(DB, SCOPE) == DB


def test_a_relative_path_that_climbs_out_is_still_gated() -> None:
    plan = build(
        draft(writes(r"..\..\elsewhere\evil.py", "x = 1\n", (EXISTS,))), SCOPE, [EXISTS], nothing
    )

    assert plan.steps[0].requires_confirmation is True
    assert "outside the project directory" in (plan.steps[0].confirmation_reason or "")


def test_python_that_does_not_parse_goes_back_to_the_model() -> None:
    with pytest.raises(PlanRejectedError) as raised:
        build(draft(writes("seed.py", BROKEN_SEED, (EXISTS,))), SCOPE, [EXISTS], nothing)

    assert "is not valid Python" in raised.value.detail
    assert "on line" in raised.value.detail


def test_a_file_that_is_not_python_is_not_parsed() -> None:
    plan = build(draft(writes("notes.txt", "def (", (EXISTS,))), SCOPE, [EXISTS], nothing)

    assert len(plan.steps) == 1


def test_a_rewrite_that_drops_existing_names_goes_back_to_the_model() -> None:
    on_disk = [WorkspaceFile(path="db.py", size_bytes=300, names=["init_db", "add_task"])]
    only_list = "import sqlite3\n\n\ndef list_tasks():\n    return []\n"

    with pytest.raises(PlanRejectedError) as raised:
        build(
            draft(writes("db.py", only_list, (EXISTS,))),
            SCOPE,
            [EXISTS],
            nothing,
            workspace=on_disk,
        )

    assert "without init_db, add_task" in raised.value.detail
    assert "must keep every name the file already defines" in raised.value.detail


def test_a_rewrite_that_keeps_every_name_is_accepted() -> None:
    on_disk = [WorkspaceFile(path="db.py", size_bytes=300, names=["init_db", "add_task"])]

    plan = build(
        draft(writes("db.py", DB_SOURCE, (EXISTS,))),
        SCOPE,
        [EXISTS],
        nothing,
        workspace=on_disk,
    )

    assert len(plan.steps) == 1


def test_a_new_file_has_no_names_to_keep() -> None:
    on_disk = [WorkspaceFile(path="db.py", size_bytes=300, names=["init_db"])]

    plan = build(
        draft(writes("seed.py", SEED_SOURCE, (EXISTS,))),
        SCOPE,
        [EXISTS],
        nothing,
        workspace=on_disk,
    )

    assert len(plan.steps) == 1


def test_a_database_criterion_with_no_run_goes_back_to_the_model() -> None:
    with pytest.raises(PlanRejectedError) as raised:
        build(
            draft(writes("seed.py", SEED_SOURCE, (ROWS,))),
            SCOPE,
            [ROWS],
            nothing,
            criteria=[criterion(ROWS, ROWS_CHECK)],
        )

    assert f"criterion {ROWS} checks tasks.db" in raised.value.detail
    assert "list each of these criterion ids in that run step's criterion_refs" in (
        raised.value.detail
    )


def test_a_database_criterion_listed_on_a_run_step_is_accepted() -> None:
    plan = build(
        draft(writes("seed.py", SEED_SOURCE), runs("seed.py", (ROWS,))),
        SCOPE,
        [ROWS],
        nothing,
        criteria=[criterion(ROWS, ROWS_CHECK)],
    )

    assert [step.criterion_refs for step in plan.steps] == [[], [ROWS]]


def test_a_module_run_counts_as_running_the_program() -> None:
    plan = build(
        draft(module_run((ROWS,))),
        SCOPE,
        [ROWS],
        nothing,
        criteria=[criterion(ROWS, ROWS_CHECK)],
    )

    assert len(plan.steps) == 1


@pytest.mark.parametrize("status", ["verified", "ignored"])
def test_a_settled_database_criterion_needs_no_run(status: str) -> None:
    plan = build(
        draft(writes("seed.py", SEED_SOURCE, (EXISTS,))),
        SCOPE,
        [EXISTS, ROWS],
        nothing,
        criteria=[criterion(ROWS, ROWS_CHECK, status=status)],
    )

    assert len(plan.steps) == 1


def test_an_inspected_criterion_needs_no_run() -> None:
    plan = build(
        draft(writes("seed.py", SEED_SOURCE, (EXISTS,))),
        SCOPE,
        [EXISTS, ROWS],
        nothing,
        criteria=[criterion(ROWS, None, check_kind="inspected")],
    )

    assert len(plan.steps) == 1


def test_a_file_the_plan_writes_needs_no_run() -> None:
    check = {"type": "file_exists", "path": "seed.py"}

    plan = build(
        draft(writes("seed.py", SEED_SOURCE, (EXISTS,))),
        SCOPE,
        [EXISTS],
        nothing,
        criteria=[criterion(EXISTS, check)],
    )

    assert len(plan.steps) == 1


def test_a_file_only_a_program_can_produce_needs_a_run() -> None:
    check = {"type": "file_exists", "path": "report.txt"}

    with pytest.raises(PlanRejectedError) as raised:
        build(
            draft(writes("report.py", "x = 1\n", (EXISTS,))),
            SCOPE,
            [EXISTS],
            nothing,
            criteria=[criterion(EXISTS, check)],
        )

    assert f"criterion {EXISTS} checks report.txt, which no step writes" in raised.value.detail


def test_a_file_already_on_disk_needs_no_run() -> None:
    check = {"type": "file_exists", "path": "report.txt"}

    plan = build(
        draft(writes("report.py", "x = 1\n", (EXISTS,))),
        SCOPE,
        [EXISTS],
        disk_with(f"{SCOPE}\\report.txt"),
        criteria=[criterion(EXISTS, check)],
    )

    assert len(plan.steps) == 1


def test_the_criterion_line_names_how_it_is_checked() -> None:
    line = render_criterion(criterion(ROWS, ROWS_CHECK))

    assert line.endswith("(checked by sql_result on tasks.db)")
    assert "[unverified/deterministic]" in line


def test_an_inspected_criterion_line_names_no_check() -> None:
    line = render_criterion(criterion(ROWS, None, check_kind="inspected"))

    assert "checked by" not in line


def test_the_stored_check_spec_reaches_the_router() -> None:
    read = to_criterion(
        {
            "id": ROWS,
            "statement": "three rows",
            "check_kind": "deterministic",
            "status": "unverified",
            "check_spec": ROWS_CHECK,
        }
    )

    assert read.check_type == "sql_result"
    assert read.check_target == "tasks.db"
