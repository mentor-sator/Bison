from __future__ import annotations

import pytest

from router_service.actions import (
    InstallPythonPackages,
    OpenInEditor,
    RunPythonModule,
    RunPythonScript,
    WriteFile,
    required_paths,
)
from router_service.gating import Disk, PlanRejectedError, Presence, build, out_of_order
from router_service.plan import Effects, ProposedStep, RouterDraft

SCOPE = r"C:\Users\dev\bison\projects\p-1\workspace"
CRITERION = "c1"
REQUIREMENTS = SCOPE + r"\requirements.txt"
SCRIPT = SCOPE + r"\create_db.py"
ROOT = ["c:\\", "users", "dev", "bison", "projects", "p-1", "workspace"]


def effects(
    writes_paths: list[str] | None = None, network: bool = False, installs_packages: bool = False
) -> Effects:
    return Effects(
        writes_paths=writes_paths or [],
        deletes_paths=[],
        network=network,
        installs_packages=installs_packages,
        needs_credentials=False,
        drives_input=False,
        reversible=True,
    )


def writes(path: str, content: str = "fastapi\n") -> ProposedStep:
    return ProposedStep(
        description=f"write {path}",
        service="task-runner",
        action=WriteFile(path=path, content=content),
        effects=effects(writes_paths=[path]),
        on_failure="abort",
        criterion_refs=[CRITERION],
    )


def opens(path: str) -> ProposedStep:
    return ProposedStep(
        description=f"open {path}",
        service="dev-env",
        action=OpenInEditor(path=path, line=None),
        effects=effects(),
        on_failure="abort",
        criterion_refs=[],
    )


def runs(path: str) -> ProposedStep:
    return ProposedStep(
        description=f"run {path}",
        service="task-runner",
        action=RunPythonScript(script_path=path, arguments=()),
        effects=effects(),
        on_failure="abort",
        criterion_refs=[],
    )


def installs() -> ProposedStep:
    return ProposedStep(
        description="install the packages",
        service="task-runner",
        action=InstallPythonPackages(packages=("fastapi",)),
        effects=effects(network=True, installs_packages=True),
        on_failure="abort",
        criterion_refs=[CRITERION],
    )


def draft(*steps: ProposedStep) -> RouterDraft:
    return RouterDraft(intent="dev_task", rationale="the task asks for it", steps=list(steps))


def nothing(path: str) -> Presence:
    return "missing"


def disk_with(files: tuple[str, ...] = (), folders: tuple[str, ...] = ()) -> Disk:
    known_files = {entry.lower() for entry in files}
    known_folders = {entry.lower() for entry in folders}

    def look(path: str) -> Presence:
        if path.lower() in known_files:
            return "file"

        if path.lower() in known_folders:
            return "folder"

        return "missing"

    return look


def test_writing_then_opening_is_accepted() -> None:
    plan = build(draft(writes(REQUIREMENTS), opens(REQUIREMENTS)), SCOPE, [CRITERION], nothing)

    assert [step.service for step in plan.steps] == ["task-runner", "dev-env"]


def test_writing_then_running_is_accepted() -> None:
    plan = build(draft(writes(SCRIPT), runs(SCRIPT)), SCOPE, [CRITERION], nothing)

    assert len(plan.steps) == 2


def test_opening_before_the_write_is_refused_and_names_both_steps() -> None:
    with pytest.raises(PlanRejectedError) as raised:
        build(draft(opens(REQUIREMENTS), writes(REQUIREMENTS)), SCOPE, [CRITERION], nothing)

    assert raised.value.detail == (
        "the plan uses files out of order: "
        f"steps[0] opens {REQUIREMENTS} before steps[1] writes it; move the write earlier"
    )


def test_running_a_script_nothing_writes_is_refused() -> None:
    with pytest.raises(PlanRejectedError) as raised:
        build(draft(installs(), runs(SCRIPT)), SCOPE, [CRITERION], nothing)

    assert (
        f"steps[1] runs {SCRIPT}, which no earlier step writes and which does not exist"
        in raised.value.detail
    )


def test_a_file_already_on_disk_may_be_opened_without_being_written() -> None:
    disk = disk_with(files=(REQUIREMENTS,))
    plan = build(draft(installs(), opens(REQUIREMENTS)), SCOPE, [CRITERION], disk)

    assert len(plan.steps) == 2


def test_opening_a_folder_is_refused() -> None:
    folder = SCOPE + r"\venv"
    disk = disk_with(folders=(folder,))

    with pytest.raises(PlanRejectedError, match=r"steps\[1\] opens .*venv, which is a folder"):
        build(draft(installs(), opens(folder)), SCOPE, [CRITERION], disk)


def test_a_relative_path_matches_the_absolute_write_of_the_same_file() -> None:
    plan = build(
        draft(writes(REQUIREMENTS), opens("requirements.txt")), SCOPE, [CRITERION], nothing
    )

    assert len(plan.steps) == 2


def test_paths_match_without_regard_to_case() -> None:
    plan = build(
        draft(writes(REQUIREMENTS), opens(REQUIREMENTS.upper())), SCOPE, [CRITERION], nothing
    )

    assert len(plan.steps) == 2


def test_a_write_declared_only_in_effects_still_counts() -> None:
    generator = ProposedStep(
        description="generate the schema",
        service="task-runner",
        action=RunPythonModule(module="alembic", arguments=("upgrade", "head")),
        effects=effects(writes_paths=[SCRIPT]),
        on_failure="abort",
        criterion_refs=[CRITERION],
    )
    plan = build(draft(generator, runs(SCRIPT)), SCOPE, [CRITERION], nothing)

    assert len(plan.steps) == 2


def test_the_live_smoke_test_plan_is_refused_for_every_fault() -> None:
    venv = SCOPE + r"\venv"
    disk = disk_with(folders=(venv,))
    problems = out_of_order(
        draft(
            opens(REQUIREMENTS),
            writes(REQUIREMENTS),
            opens(venv),
            runs(SCOPE + r"\create_venv.py"),
        ),
        ROOT,
        disk,
    )

    assert problems == [
        f"steps[0] opens {REQUIREMENTS} before steps[1] writes it; move the write earlier",
        f"steps[2] opens {venv}, which is a folder; name a file",
        f"steps[3] runs {SCOPE}\\create_venv.py, which no earlier step writes "
        "and which does not exist",
    ]


def test_more_than_three_faults_are_counted_not_listed() -> None:
    missing = [SCOPE + rf"\missing_{index}.py" for index in range(5)]

    with pytest.raises(PlanRejectedError) as raised:
        build(draft(installs(), *[runs(path) for path in missing]), SCOPE, [CRITERION], nothing)

    assert raised.value.detail.endswith("; and 2 more")


def test_a_plan_with_nothing_to_open_or_run_never_looks_at_the_disk() -> None:
    looked: list[str] = []

    def watched(path: str) -> Presence:
        looked.append(path)

        return "missing"

    build(draft(installs(), writes(REQUIREMENTS)), SCOPE, [CRITERION], watched)

    assert looked == []


def test_only_opening_and_running_require_a_file() -> None:
    assert required_paths(OpenInEditor(path="a.py", line=None)) == (("opens", "a.py"),)
    assert required_paths(RunPythonScript(script_path="b.py", arguments=())) == (("runs", "b.py"),)
    assert required_paths(WriteFile(path="c.py", content="")) == ()
    assert required_paths(RunPythonModule(module="pytest", arguments=())) == ()
    assert required_paths(InstallPythonPackages(packages=("fastapi",))) == ()
