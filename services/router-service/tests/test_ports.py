from __future__ import annotations

import pytest

from router_service.actions import RunPythonModule, RunPythonScript, WriteFile
from router_service.gating import PlanRejectedError, Presence, build
from router_service.plan import Effects, ProposedStep, RouterDraft

SCOPE = r"C:\Users\dev\bison\workspace"
CRITERION = "c1"
SERVER = rf"{SCOPE}\run.py"


def present(path: str) -> Presence:
    return "file"


def effects(**overrides: object) -> Effects:
    base: dict[str, object] = {
        "writes_paths": [],
        "deletes_paths": [],
        "network": False,
        "installs_packages": False,
        "needs_credentials": False,
        "drives_input": False,
        "reversible": True,
    }
    base.update(overrides)

    return Effects(**base)  # type: ignore[arg-type]


def step(**overrides: object) -> ProposedStep:
    base: dict[str, object] = {
        "description": "Start the API",
        "service": "task-runner",
        "action": WriteFile(path=SERVER, content="print('hello')\n"),
        "effects": effects(),
        "on_failure": "abort",
        "criterion_refs": [CRITERION],
    }
    base.update(overrides)

    return ProposedStep(**base)  # type: ignore[arg-type]


def draft(*steps: ProposedStep) -> RouterDraft:
    return RouterDraft(
        intent="dev_task",
        rationale="the task asks for an API to be served",
        steps=list(steps) or [step()],
    )


def written(content: str) -> RouterDraft:
    return draft(step(action=WriteFile(path=SERVER, content=content)))


def refusal(plan: RouterDraft) -> str:
    with pytest.raises(PlanRejectedError) as caught:
        build(plan, SCOPE, [CRITERION], present)

    return str(caught.value)


@pytest.mark.parametrize(
    "content",
    [
        "uvicorn.run(app, host='127.0.0.1', port=8000)\n",
        "PORT = 8600\n",
        "app.run(port = 8900)\n",
        '{"port": 8100}\n',
        "server.listen(8300)\n",
        'sock.bind(("0.0.0.0", 8800))\n',
        'BASE = "http://127.0.0.1:8400/health"\n',
        'command = "uvicorn main:app --port 8700"\n',
    ],
)
def test_a_written_file_that_binds_a_bison_port_is_refused(content: str) -> None:
    assert "the plan takes a port BISON is using" in refusal(written(content))


@pytest.mark.parametrize("content", ["port=9101\n", "port = 5432\n", "TIMEOUT_MS = 8500\n"])
def test_a_port_outside_the_range_is_left_alone(content: str) -> None:
    plan = build(written(content), SCOPE, [CRITERION], present)

    assert len(plan.steps) == 1


def test_a_module_run_on_a_bison_port_is_refused() -> None:
    running = draft(step(action=RunPythonModule(module="http.server", arguments=("8000",))))

    assert "runs the http.server module on port 8000" in refusal(running)


def test_a_module_flag_carrying_a_bison_port_is_refused() -> None:
    running = draft(
        step(action=RunPythonModule(module="uvicorn", arguments=("main:app", "--port", "8700")))
    )

    assert "runs the uvicorn module on port 8700" in refusal(running)


def test_a_joined_port_flag_is_refused() -> None:
    running = draft(step(action=RunPythonModule(module="uvicorn", arguments=("--port=8400",))))

    assert "on port 8400" in refusal(running)


def test_a_script_run_on_a_bison_port_is_refused() -> None:
    running = draft(step(action=RunPythonScript(script_path=SERVER, arguments=("8900",))))

    assert f"runs {SERVER} on port 8900" in refusal(running)


def test_a_module_argument_outside_the_range_is_left_alone() -> None:
    running = draft(step(action=RunPythonModule(module="http.server", arguments=("9101",))))
    plan = build(running, SCOPE, [CRITERION], present)

    assert len(plan.steps) == 1


def test_the_refusal_names_the_step_and_the_file() -> None:
    detail = refusal(written("port=8000\n"))

    assert "steps[0] writes" in detail
    assert SERVER in detail


def test_the_refusal_names_a_port_the_model_may_use() -> None:
    detail = refusal(written("port=8000\n"))

    assert "above 9000" in detail
    assert "9101" in detail


def test_the_refusal_names_the_whole_reserved_range() -> None:
    detail = refusal(written("port=8000\n"))

    assert "Ports 8000 to 9000" in detail


def test_every_offending_step_is_counted() -> None:
    many = draft(
        step(action=WriteFile(path=SERVER, content="port=8000\n")),
        step(action=WriteFile(path=rf"{SCOPE}\second.py", content="port=8100\n")),
        step(action=WriteFile(path=rf"{SCOPE}\third.py", content="port=8200\n")),
        step(action=WriteFile(path=rf"{SCOPE}\fourth.py", content="port=8300\n")),
    )
    detail = refusal(many)

    assert "and 1 more" in detail


def test_one_file_binding_two_ports_reports_both() -> None:
    detail = refusal(written("api_port = 8000\nadmin_port: int = 8100\n"))

    assert "port 8000" in detail
    assert "port 8100" in detail


def test_a_plan_that_binds_nothing_is_untouched() -> None:
    plan = build(draft(), SCOPE, [CRITERION], present)

    assert plan.steps[0].requires_confirmation is False
