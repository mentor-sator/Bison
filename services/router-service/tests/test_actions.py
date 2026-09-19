from __future__ import annotations

from typing import Any

import pytest

from router_service.actions import (
    ACTION_MENUS,
    DECLARABLE_TYPES,
    DEV_ENV_TYPES,
    TASK_RUNNER_TYPES,
    ActionSpecError,
    InstallPythonPackages,
    OpenInEditor,
    RunPythonModule,
    RunPythonScript,
    WriteFile,
    installs_packages,
    opened_paths,
    parse,
    parse_for,
    payload,
    written_paths,
)

LABEL = "steps[0].action"

SCRIPT = "C:\\scope\\count_files.py"


def write_file(**overrides: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "type": "write_file",
        "path": SCRIPT,
        "content": "print('hello')\n",
    }
    base.update(overrides)

    return base


def run_script(**overrides: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "type": "run_python_script",
        "script_path": SCRIPT,
        "arguments": ["--verbose"],
    }
    base.update(overrides)

    return base


def run_module(**overrides: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "type": "run_python_module",
        "module": "pytest",
        "arguments": ["-q", "tests"],
    }
    base.update(overrides)

    return base


def install(**overrides: Any) -> dict[str, Any]:
    base: dict[str, Any] = {"type": "install_python_packages", "packages": ["fastapi"]}
    base.update(overrides)

    return base


def open_editor(**overrides: Any) -> dict[str, Any]:
    base: dict[str, Any] = {"type": "open_in_editor", "path": SCRIPT, "line": 12}
    base.update(overrides)

    return base


def test_a_write_file_action_parses() -> None:
    action = parse(write_file(), LABEL)

    assert isinstance(action, WriteFile)
    assert action.path == SCRIPT
    assert action.content == "print('hello')\n"


def test_an_empty_file_is_legitimate() -> None:
    action = parse(write_file(content=""), LABEL)

    assert isinstance(action, WriteFile)
    assert action.content == ""


def test_content_is_kept_exactly_and_never_stripped() -> None:
    action = parse(write_file(content="\n  indented\n\n"), LABEL)

    assert isinstance(action, WriteFile)
    assert action.content == "\n  indented\n\n"


def test_content_that_is_not_a_string_is_refused() -> None:
    with pytest.raises(ActionSpecError, match="must be a string"):
        parse(write_file(content=["print('hello')"]), LABEL)


def test_an_enormous_file_is_refused_with_advice() -> None:
    with pytest.raises(ActionSpecError, match="more than one step"):
        parse(write_file(content="x" * 200_001), LABEL)


def test_a_run_python_script_action_parses() -> None:
    action = parse(run_script(), LABEL)

    assert isinstance(action, RunPythonScript)
    assert action.script_path == SCRIPT
    assert action.arguments == ("--verbose",)


def test_a_script_with_no_arguments_parses() -> None:
    action = parse(run_script(arguments=[]), LABEL)

    assert isinstance(action, RunPythonScript)
    assert action.arguments == ()


def test_absent_arguments_read_as_none_given() -> None:
    entry = run_script()
    del entry["arguments"]

    action = parse(entry, LABEL)

    assert isinstance(action, RunPythonScript)
    assert action.arguments == ()


def test_a_run_python_module_action_parses() -> None:
    action = parse(run_module(), LABEL)

    assert isinstance(action, RunPythonModule)
    assert action.module == "pytest"
    assert action.arguments == ("-q", "tests")


def test_an_install_action_parses() -> None:
    action = parse(install(packages=["fastapi", "uvicorn>=0.32"]), LABEL)

    assert isinstance(action, InstallPythonPackages)
    assert action.packages == ("fastapi", "uvicorn>=0.32")


def test_an_install_with_nothing_to_install_is_refused() -> None:
    with pytest.raises(ActionSpecError, match="at least one package"):
        parse(install(packages=[]), LABEL)


def test_a_blank_package_name_is_refused() -> None:
    with pytest.raises(ActionSpecError, match=r"packages\[1\]"):
        parse(install(packages=["fastapi", "   "]), LABEL)


def test_an_argument_that_is_not_a_string_is_refused_rather_than_dropped() -> None:
    with pytest.raises(ActionSpecError, match=r"arguments\[1\]"):
        parse(run_module(arguments=["-q", 7]), LABEL)


def test_an_argument_may_be_empty_because_a_program_may_want_one() -> None:
    action = parse(run_script(arguments=["--name", ""]), LABEL)

    assert isinstance(action, RunPythonScript)
    assert action.arguments == ("--name", "")


def test_arguments_that_are_not_an_array_are_refused() -> None:
    with pytest.raises(ActionSpecError, match="array of strings"):
        parse(run_module(arguments="-q tests"), LABEL)


def test_too_many_arguments_are_refused() -> None:
    with pytest.raises(ActionSpecError, match="no more than 32"):
        parse(run_module(arguments=["-q"] * 33), LABEL)


def test_an_unknown_action_type_names_the_ones_that_work() -> None:
    with pytest.raises(ActionSpecError) as raised:
        parse({"type": "run_shell"}, LABEL)

    for name in DECLARABLE_TYPES:
        assert name in raised.value.detail


def test_a_missing_action_type_is_refused() -> None:
    with pytest.raises(ActionSpecError, match="must be one of"):
        parse({"path": SCRIPT}, LABEL)


def test_an_action_that_is_not_an_object_is_refused() -> None:
    with pytest.raises(ActionSpecError, match="must be an object"):
        parse(["write_file"], LABEL)


def test_a_missing_required_field_names_the_field() -> None:
    entry = write_file()
    del entry["path"]

    with pytest.raises(ActionSpecError, match=r"steps\[0\]\.action\.path"):
        parse(entry, LABEL)


def test_a_task_runner_step_must_carry_an_action() -> None:
    with pytest.raises(ActionSpecError, match="is required"):
        parse_for(None, "task-runner", LABEL)


def test_a_task_runner_step_carries_the_action_it_declared() -> None:
    action = parse_for(write_file(), "task-runner", LABEL)

    assert isinstance(action, WriteFile)


def test_another_service_carries_no_action() -> None:
    for service in ("automation", "engine-session"):
        assert parse_for(None, service, LABEL) is None


def test_the_refusal_names_every_service_that_carries_an_action() -> None:
    with pytest.raises(ActionSpecError) as raised:
        parse_for(write_file(), "engine-session", LABEL)

    for service in ACTION_MENUS:
        assert service in raised.value.detail


def test_an_open_in_editor_action_parses() -> None:
    action = parse(open_editor(), LABEL)

    assert isinstance(action, OpenInEditor)
    assert action.path == SCRIPT
    assert action.line == 12


def test_an_open_without_a_line_opens_at_the_top() -> None:
    assert parse(open_editor(line=None), LABEL) == OpenInEditor(path=SCRIPT, line=None)


def test_an_absent_line_reads_as_no_line() -> None:
    entry = open_editor()
    del entry["line"]

    assert parse(entry, LABEL) == OpenInEditor(path=SCRIPT, line=None)


@pytest.mark.parametrize("line", [0, -3, 2.5, "12", True])
def test_a_line_that_is_not_a_whole_number_from_one_is_refused(line: object) -> None:
    with pytest.raises(ActionSpecError, match=r"line must be a whole number from 1"):
        parse(open_editor(line=line), LABEL)


def test_an_open_needs_a_path() -> None:
    with pytest.raises(ActionSpecError, match=r"steps\[0\]\.action\.path"):
        parse(open_editor(path="  "), LABEL)


def test_a_dev_env_step_must_carry_an_action() -> None:
    with pytest.raises(ActionSpecError, match="is required for a dev-env step") as raised:
        parse_for(None, "dev-env", LABEL)

    assert "open_in_editor" in raised.value.detail


def test_a_dev_env_step_carries_the_action_it_declared() -> None:
    assert isinstance(parse_for(open_editor(), "dev-env", LABEL), OpenInEditor)


@pytest.mark.parametrize("entry", [write_file(), run_script(), run_module(), install()])
def test_a_dev_env_step_refuses_a_task_runner_action(entry: dict[str, Any]) -> None:
    with pytest.raises(ActionSpecError, match="not an action a dev-env step performs"):
        parse_for(entry, "dev-env", LABEL)


def test_a_task_runner_step_refuses_a_dev_env_action() -> None:
    with pytest.raises(ActionSpecError, match="not an action a task-runner step performs"):
        parse_for(open_editor(), "task-runner", LABEL)


def test_an_unknown_type_offers_only_the_menu_of_that_service() -> None:
    with pytest.raises(ActionSpecError) as raised:
        parse_for({"type": "run_shell"}, "task-runner", LABEL)

    assert "open_in_editor" not in raised.value.detail

    for name in TASK_RUNNER_TYPES:
        assert name in raised.value.detail


def test_every_declarable_type_belongs_to_exactly_one_menu() -> None:
    assert TASK_RUNNER_TYPES | DEV_ENV_TYPES == DECLARABLE_TYPES
    assert not TASK_RUNNER_TYPES & DEV_ENV_TYPES


def test_an_action_on_another_service_is_refused_rather_than_ignored() -> None:
    with pytest.raises(ActionSpecError, match="must be null"):
        parse_for(write_file(), "automation", LABEL)


def test_a_stored_action_names_its_own_type() -> None:
    assert payload(parse(write_file(), LABEL))["type"] == "write_file"


def test_a_stored_action_carries_arguments_as_a_list() -> None:
    stored = payload(parse(run_module(), LABEL))

    assert stored["arguments"] == ["-q", "tests"]
    assert isinstance(stored["arguments"], list)


def test_a_stored_open_carries_its_line_even_when_null() -> None:
    assert payload(parse(open_editor(line=None), LABEL)) == {
        "type": "open_in_editor",
        "path": SCRIPT,
        "line": None,
    }


def test_a_stored_install_carries_packages_as_a_list() -> None:
    stored = payload(parse(install(packages=["fastapi", "uvicorn"]), LABEL))

    assert stored["packages"] == ["fastapi", "uvicorn"]


def test_every_declarable_type_round_trips_through_storage() -> None:
    for entry in (write_file(), run_script(), run_module(), install(), open_editor()):
        stored = payload(parse(entry, LABEL))

        assert stored["type"] == entry["type"]


def test_only_a_write_declares_a_written_path() -> None:
    assert written_paths(parse(write_file(), LABEL)) == (SCRIPT,)
    assert written_paths(parse(run_script(), LABEL)) == ()
    assert written_paths(parse(run_module(), LABEL)) == ()
    assert written_paths(parse(install(), LABEL)) == ()
    assert written_paths(parse(open_editor(), LABEL)) == ()


def test_only_an_open_declares_an_opened_path() -> None:
    assert opened_paths(parse(open_editor(), LABEL)) == (SCRIPT,)
    assert opened_paths(parse(write_file(), LABEL)) == ()
    assert opened_paths(parse(install(), LABEL)) == ()


def test_only_an_install_declares_a_package_install() -> None:
    assert installs_packages(parse(install(), LABEL))
    assert not installs_packages(parse(write_file(), LABEL))
    assert not installs_packages(parse(run_script(), LABEL))


def test_there_is_no_action_that_takes_a_shell_string() -> None:
    for name in DECLARABLE_TYPES:
        assert "shell" not in name
        assert "command" not in name
