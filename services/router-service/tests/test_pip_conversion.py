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
    installed_through_the_runner,
    requested_packages,
)
from router_service.plan import Effects, ProposedStep, RouterDraft

SCOPE = r"C:\Users\dev\bison\projects\p-1\workspace"
CRITERION = "c1"


def effects(**overrides: object) -> Effects:
    declared: dict[str, object] = {
        "writes_paths": [],
        "deletes_paths": [],
        "network": False,
        "installs_packages": False,
        "needs_credentials": False,
        "drives_input": False,
        "reversible": True,
    }
    declared.update(overrides)

    return Effects(**declared)  # type: ignore[arg-type]


def step(action: object, **overrides: object) -> ProposedStep:
    declared: dict[str, object] = {
        "description": "install the dependencies",
        "service": "task-runner",
        "action": action,
        "effects": effects(),
        "on_failure": "abort",
        "criterion_refs": [CRITERION],
    }
    declared.update(overrides)

    return ProposedStep(**declared)  # type: ignore[arg-type]


def pip(*arguments: str) -> ProposedStep:
    return step(RunPythonModule(module="pip", arguments=arguments))


def draft(*steps: ProposedStep) -> RouterDraft:
    return RouterDraft(intent="dev_task", rationale="the task asks for it", steps=list(steps))


def nothing(path: str) -> Presence:
    return "missing"


def only_step(plan_steps: list[ProposedStep]) -> ProposedStep:
    assert len(plan_steps) == 1

    return plan_steps[0]


def test_a_pip_install_names_the_packages_it_would_install() -> None:
    assert requested_packages(
        RunPythonModule(module="pip", arguments=("install", "fastapi", "uvicorn"))
    ) == ("fastapi", "uvicorn")


def test_a_version_pin_survives_the_reading() -> None:
    action = RunPythonModule(module="pip", arguments=("install", "pydantic==2.9.2"))

    assert requested_packages(action) == ("pydantic==2.9.2",)


@pytest.mark.parametrize(
    "arguments",
    [
        ("install", "-r", "requirements.txt"),
        ("install", "--upgrade", "fastapi"),
        ("install", "-e", "."),
        ("install", "https://example.test/pkg.whl"),
        ("install", r"C:\wheels\pkg.whl"),
        ("install",),
        ("download", "fastapi"),
        (),
    ],
)
def test_anything_that_is_not_a_plain_install_is_left_for_the_model(
    arguments: tuple[str, ...],
) -> None:
    assert requested_packages(RunPythonModule(module="pip", arguments=arguments)) is None


@pytest.mark.parametrize("module", ["pytest", "venv", "http.server"])
def test_only_pip_is_read_as_an_install(module: str) -> None:
    action = RunPythonModule(module=module, arguments=("install", "fastapi"))

    assert requested_packages(action) is None


def test_another_kind_of_action_is_never_read_as_an_install() -> None:
    assert requested_packages(WriteFile(path="a.py", content="")) is None
    assert requested_packages(RunPythonScript(script_path="a.py", arguments=())) is None
    assert requested_packages(InstallPythonPackages(packages=("fastapi",))) is None


def test_a_pip_step_becomes_an_install_step() -> None:
    converted = only_step(installed_through_the_runner(draft(pip("install", "fastapi"))).steps)

    assert converted.action == InstallPythonPackages(packages=("fastapi",))
    assert converted.description == "install the dependencies"
    assert converted.criterion_refs == [CRITERION]


def test_the_converted_step_declares_what_it_really_does() -> None:
    converted = only_step(installed_through_the_runner(draft(pip("install", "fastapi"))).steps)

    assert converted.effects.network is True
    assert converted.effects.installs_packages is True


def test_a_plan_with_no_pip_step_is_left_exactly_as_it_was() -> None:
    original = draft(step(WriteFile(path=SCOPE + r"\main.py", content="print(1)\n")))

    assert installed_through_the_runner(original) is original


def test_the_live_plan_of_three_pip_steps_is_accepted_as_three_installs() -> None:
    plan = build(
        draft(pip("install", "fastapi"), pip("install", "uvicorn"), pip("install", "pydantic")),
        SCOPE,
        [CRITERION],
        nothing,
    )

    assert [entry.action for entry in plan.steps] == [
        InstallPythonPackages(packages=("fastapi",)),
        InstallPythonPackages(packages=("uvicorn",)),
        InstallPythonPackages(packages=("pydantic",)),
    ]


def test_a_converted_install_is_still_gated_for_confirmation() -> None:
    plan = build(draft(pip("install", "fastapi")), SCOPE, [CRITERION], nothing)

    assert plan.gated_count == 1
    assert "installs packages" in str(plan.steps[0].confirmation_reason)
    assert "reaches the network" in str(plan.steps[0].confirmation_reason)


def test_a_pip_step_that_cannot_be_converted_is_still_refused() -> None:
    with pytest.raises(PlanRejectedError, match="runs the pip module"):
        build(draft(pip("install", "-r", "requirements.txt")), SCOPE, [CRITERION], nothing)


def test_a_venv_step_is_refused_even_next_to_a_convertible_install() -> None:
    venv = step(RunPythonModule(module="venv", arguments=("venv",)))

    with pytest.raises(PlanRejectedError, match=r"steps\[1\] runs the venv module"):
        build(draft(pip("install", "fastapi"), venv), SCOPE, [CRITERION], nothing)
