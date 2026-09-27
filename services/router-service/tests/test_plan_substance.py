from __future__ import annotations

import pytest

from router_service.actions import RunPythonModule, RunPythonScript, WriteFile
from router_service.gating import (
    Disk,
    PlanRejectedError,
    Presence,
    Reader,
    build,
    inert,
    placeholders,
)
from router_service.plan import Effects, ProposedStep, RouterDraft

SCOPE = r"C:\Users\dev\bison\projects\p-1\workspace"
DB = f"{SCOPE}\\db.py"
SEED = f"{SCOPE}\\seed.py"
REF = "c-1"

STUBS = (
    "def init_db():\n    pass\n\ndef add_task(title):\n    pass\n\ndef list_tasks():\n    pass\n"
)

WORKING_DB = (
    "import sqlite3\n\n\n"
    "def init_db():\n"
    "    sqlite3.connect('tasks.db').execute('CREATE TABLE IF NOT EXISTS tasks (title TEXT)')\n"
)

GUARDED_SEED = "import db\n\n\nif __name__ == '__main__':\n    db.init_db()\n"
ARGV_SEED = "import sys\n\n\nif __name__ == '__main__':\n    print(sys.argv[1])\n"
ARGPARSE_SEED = (
    "import argparse\n\n\nif __name__ == '__main__':\n    argparse.ArgumentParser().parse_args()\n"
)


def effects(
    writes: list[str] | None = None, reversible: bool = True, network: bool = False
) -> Effects:
    return Effects(
        writes_paths=writes or [],
        deletes_paths=[],
        network=network,
        installs_packages=False,
        needs_credentials=False,
        drives_input=False,
        reversible=reversible,
    )


def writes(path: str, content: str, reversible: bool = True, network: bool = False) -> ProposedStep:
    return ProposedStep(
        description=f"Write {path}",
        service="task-runner",
        action=WriteFile(path=path, content=content),
        effects=effects([path], reversible=reversible, network=network),
        on_failure="abort",
        criterion_refs=[REF],
    )


def runs(path: str, arguments: tuple[str, ...] = ()) -> ProposedStep:
    return ProposedStep(
        description=f"Run {path}",
        service="task-runner",
        action=RunPythonScript(script_path=path, arguments=arguments),
        effects=effects(),
        on_failure="abort",
        criterion_refs=[REF],
    )


def draft(*steps: ProposedStep) -> RouterDraft:
    return RouterDraft(intent="dev_task", rationale="the task asks for code", steps=list(steps))


def nothing(path: str) -> Presence:
    return "missing"


def unread(path: str) -> str | None:
    return None


def disk_with(*files: str) -> Disk:
    present = {entry.lower() for entry in files}

    def probe(path: str) -> Presence:
        return "file" if path.lower() in present else "missing"

    return probe


def reader_of(path: str, content: str) -> Reader:
    def read(candidate: str) -> str | None:
        return content if candidate.lower() == path.lower() else None

    return read


def planned(*steps: ProposedStep, disk: Disk = nothing, read: Reader = unread) -> list[bool]:
    plan = build(draft(*steps), SCOPE, [REF], disk, read=read)

    return [step.requires_confirmation for step in plan.steps]


def rejected(*steps: ProposedStep, disk: Disk = nothing, read: Reader = unread) -> str:
    with pytest.raises(PlanRejectedError) as raised:
        build(draft(*steps), SCOPE, [REF], disk, read=read)

    return raised.value.detail


def test_the_day_27_stub_db_goes_back_to_the_model() -> None:
    detail = rejected(writes(DB, STUBS))

    assert "init_db, add_task, list_tasks left as placeholders" in detail
    assert "every function must do the work it is named for" in detail


@pytest.mark.parametrize(
    "body",
    [
        "    pass\n",
        "    ...\n",
        '    """Initialise the database."""\n',
        "    raise NotImplementedError\n",
        "    raise NotImplementedError('later')\n",
        '    """Initialise."""\n    pass\n',
    ],
)
def test_every_kind_of_placeholder_body_is_found(body: str) -> None:
    assert placeholders(f"def init_db():\n{body}") == ["init_db"]


def test_a_method_left_as_a_placeholder_is_found() -> None:
    source = "class Store:\n    def save(self, row):\n        pass\n"

    assert placeholders(source) == ["save"]


def test_an_abstract_method_is_not_a_placeholder() -> None:
    source = (
        "from abc import abstractmethod\n\n\n"
        "class Store:\n    @abstractmethod\n    def save(self, row):\n        ...\n"
    )

    assert placeholders(source) == []


def test_a_protocol_is_not_a_placeholder() -> None:
    source = (
        "from typing import Protocol\n\n\nclass Store(Protocol):\n    def save(self) -> None: ...\n"
    )

    assert placeholders(source) == []


def test_working_code_is_accepted() -> None:
    assert planned(writes(DB, WORKING_DB)) == [False]


def test_running_a_module_that_only_defines_names_goes_back_to_the_model() -> None:
    detail = rejected(writes(DB, WORKING_DB), runs(DB))

    assert f"steps[1] runs {DB}, which only defines names" in detail
    assert "if __name__ == '__main__' block" in detail


def test_the_day_27_verify_step_is_caught_on_disk() -> None:
    detail = rejected(
        runs(DB, ("verify_table", "tasks.db", "tasks")),
        disk=disk_with(DB),
        read=reader_of(DB, WORKING_DB),
    )

    assert "which only defines names" in detail


def test_a_script_with_a_main_block_may_run() -> None:
    assert planned(writes(SEED, GUARDED_SEED), runs(SEED)) == [False, False]


@pytest.mark.parametrize(
    "source",
    [
        "print('seeded')\n",
        "import db\n\ndb.init_db()\n",
        "import db\n\nrows = db.init_db()\n",
        "for index in range(3):\n    print(index)\n",
    ],
)
def test_a_script_acting_at_its_top_level_may_run(source: str) -> None:
    assert inert(source) is False


@pytest.mark.parametrize(
    "source",
    [
        STUBS,
        WORKING_DB,
        'import sqlite3\n\nPATH = "tasks.db"\n',
        '"""Only a docstring."""\n',
    ],
)
def test_a_script_that_only_declares_is_inert(source: str) -> None:
    assert inert(source) is True


def test_arguments_a_script_never_reads_go_back_to_the_model() -> None:
    detail = rejected(writes(SEED, GUARDED_SEED), runs(SEED, ("--rows", "3")))

    assert f"passes --rows 3 to {SEED}, which never reads its arguments" in detail


@pytest.mark.parametrize("source", [ARGV_SEED, ARGPARSE_SEED])
def test_a_script_that_reads_its_arguments_may_receive_them(source: str) -> None:
    assert planned(writes(SEED, source), runs(SEED, ("3",))) == [False, False]


def test_the_latest_write_in_the_plan_is_the_script_that_runs() -> None:
    steps = (writes(SEED, WORKING_DB), writes(SEED, GUARDED_SEED), runs(SEED))

    assert planned(*steps) == [False, False, False]


def test_a_script_whose_source_cannot_be_read_is_left_to_run() -> None:
    assert planned(runs(SEED), disk=disk_with(SEED)) == [False]


def test_a_module_run_is_not_read() -> None:
    step = ProposedStep(
        description="Run the tests",
        service="task-runner",
        action=RunPythonModule(module="pytest", arguments=("-q",)),
        effects=effects(),
        on_failure="abort",
        criterion_refs=[REF],
    )

    assert planned(step) == [False]


def test_a_new_file_the_model_calls_irreversible_is_not_gated() -> None:
    plan = build(draft(writes(SEED, GUARDED_SEED, reversible=False)), SCOPE, [REF], nothing)

    assert plan.steps[0].requires_confirmation is False
    assert plan.steps[0].reversible is True


def test_overwriting_an_existing_file_keeps_the_declared_gate() -> None:
    plan = build(draft(writes(SEED, GUARDED_SEED, reversible=False)), SCOPE, [REF], disk_with(SEED))

    assert plan.steps[0].requires_confirmation is True
    assert plan.steps[0].confirmation_reason == "cannot be undone"


def test_a_new_file_outside_the_workspace_stays_irreversible() -> None:
    outside = r"C:\Users\dev\elsewhere\seed.py"
    plan = build(draft(writes(outside, GUARDED_SEED, reversible=False)), SCOPE, [REF], nothing)

    assert plan.steps[0].reversible is False
    assert "cannot be undone" in (plan.steps[0].confirmation_reason or "")


def test_a_new_file_that_also_reaches_the_network_keeps_its_declaration() -> None:
    plan = build(
        draft(writes(SEED, GUARDED_SEED, reversible=False, network=True)), SCOPE, [REF], nothing
    )

    assert plan.steps[0].reversible is False
    assert "reaches the network" in (plan.steps[0].confirmation_reason or "")


def test_a_second_write_to_the_same_new_file_keeps_its_declaration() -> None:
    second = writes(SEED, GUARDED_SEED, reversible=False)
    plan = build(draft(writes(SEED, GUARDED_SEED), second), SCOPE, [REF], nothing)

    assert plan.steps[1].reversible is False
