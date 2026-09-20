from __future__ import annotations

import pytest

from router_service.actions import (
    InstallPythonPackages,
    RunPythonModule,
    RunPythonScript,
    WriteFile,
)
from router_service.gating import (
    PlanRejectedError,
    Presence,
    build,
    provisions,
    self_provisioning,
)
from router_service.plan import Effects, ProposedStep, RouterDraft

SCOPE = r"C:\Users\dev\bison\projects\p-1\workspace"
CRITERION = "c1"


def effects(writes_paths: list[str] | None = None, installs: bool = False) -> Effects:
    return Effects(
        writes_paths=writes_paths or [],
        deletes_paths=[],
        network=installs,
        installs_packages=installs,
        needs_credentials=False,
        drives_input=False,
        reversible=True,
    )


def writes(name: str, content: str) -> ProposedStep:
    path = SCOPE + "\\" + name

    return ProposedStep(
        description=f"write {name}",
        service="task-runner",
        action=WriteFile(path=path, content=content),
        effects=effects(writes_paths=[path]),
        on_failure="abort",
        criterion_refs=[CRITERION],
    )


def module(name: str, *arguments: str) -> ProposedStep:
    return ProposedStep(
        description=f"run {name}",
        service="task-runner",
        action=RunPythonModule(module=name, arguments=arguments),
        effects=effects(),
        on_failure="abort",
        criterion_refs=[CRITERION],
    )


def installs(*packages: str) -> ProposedStep:
    return ProposedStep(
        description="install the packages",
        service="task-runner",
        action=InstallPythonPackages(packages=packages),
        effects=effects(installs=True),
        on_failure="abort",
        criterion_refs=[CRITERION],
    )


def draft(*steps: ProposedStep) -> RouterDraft:
    return RouterDraft(intent="dev_task", rationale="the task asks for it", steps=list(steps))


def nothing(path: str) -> Presence:
    return "missing"


@pytest.mark.parametrize(
    "content",
    [
        "import subprocess\nsubprocess.run(['pip', 'install', 'fastapi'])\n",
        "subprocess.check_call([sys.executable, '-m', 'pip', 'install', 'x'])\n",
        "import venv\nvenv.create('venv', with_pip=True)\n",
        "import os\nos.system('python -m venv venv')\n",
        "import os\nos.system('pip install -r requirements.txt')\n",
        "from pip._internal import main\nmain(['install', 'fastapi'])\n",
        "import ensurepip\nensurepip.bootstrap()\n",
        "PIP3.EXE INSTALL fastapi\n",
    ],
)
def test_a_script_that_provisions_is_recognised(content: str) -> None:
    assert provisions(content)


@pytest.mark.parametrize(
    "content",
    [
        "from fastapi import FastAPI\n\napp = FastAPI()\n",
        "import sqlite3\n\nconnection = sqlite3.connect('tasks.db')\n",
        "pipeline = 1\n",
        "import pipes\n",
        "def install_routes(app):\n    return app\n",
    ],
)
def test_ordinary_code_is_left_alone(content: str) -> None:
    assert not provisions(content)


def test_the_live_smoke_test_plan_is_refused() -> None:
    script = "import subprocess\nsubprocess.run(['python', '-m', 'venv', 'venv'])\n"

    assert self_provisioning(draft(writes("setup_env.py", script))) == [
        f"steps[0] writes {SCOPE}\\setup_env.py, a script that installs packages "
        "or creates a virtual environment"
    ]


@pytest.mark.parametrize("name", ["pip", "venv", "virtualenv", "ensurepip", "pip.__main__", "PIP"])
def test_running_a_provisioning_module_is_refused(name: str) -> None:
    assert self_provisioning(draft(module(name, "install", "fastapi"))) == [
        f"steps[0] runs the {name.split('.')[0].lower()} module"
    ]


@pytest.mark.parametrize("name", ["pytest", "uvicorn", "http.server", "pipdeptree"])
def test_running_an_ordinary_module_is_left_alone(name: str) -> None:
    assert self_provisioning(draft(module(name))) == []


def test_a_requirements_file_naming_pip_is_not_a_script() -> None:
    assert self_provisioning(draft(writes("requirements.txt", "pip\nfastapi\n"))) == []


def test_a_readme_that_explains_pip_install_is_not_a_script() -> None:
    readme = "Run `pip install -r requirements.txt` to set up.\n"

    assert self_provisioning(draft(writes("README.md", readme))) == []


@pytest.mark.parametrize("name", ["setup.bat", "setup.cmd", "setup.ps1", "setup.sh"])
def test_a_shell_script_that_installs_is_refused(name: str) -> None:
    assert len(self_provisioning(draft(writes(name, "pip install fastapi\n")))) == 1


def test_the_refusal_tells_the_model_what_to_do_instead() -> None:
    with pytest.raises(PlanRejectedError) as raised:
        build(draft(module("venv", "venv")), SCOPE, [CRITERION], nothing)

    assert raised.value.detail == (
        "the plan builds its own Python environment: steps[0] runs the venv module. "
        "The task already has one; add packages with an install_python_packages step "
        "and never create a virtual environment"
    )


def test_every_fault_is_named_up_to_three() -> None:
    steps = [module("pip") for _ in range(5)]

    with pytest.raises(PlanRejectedError) as raised:
        build(draft(*steps), SCOPE, [CRITERION], nothing)

    assert "; and 2 more." in raised.value.detail


def test_installing_through_the_runner_is_accepted() -> None:
    app = "from fastapi import FastAPI\n\napp = FastAPI()\n"
    plan = build(
        draft(installs("fastapi", "uvicorn"), writes("main.py", app)),
        SCOPE,
        [CRITERION],
        nothing,
    )

    assert [step.action.TYPE for step in plan.steps if step.action is not None] == [
        "install_python_packages",
        "write_file",
    ]


def test_a_script_is_still_run_after_it_is_written() -> None:
    script = "print('seeded')\n"
    runner = ProposedStep(
        description="seed the database",
        service="task-runner",
        action=RunPythonScript(script_path=SCOPE + "\\seed.py", arguments=()),
        effects=effects(),
        on_failure="abort",
        criterion_refs=[CRITERION],
    )

    plan = build(draft(writes("seed.py", script), runner), SCOPE, [CRITERION], nothing)

    assert len(plan.steps) == 2
