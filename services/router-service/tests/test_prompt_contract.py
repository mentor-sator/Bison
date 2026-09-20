from __future__ import annotations

import re

import pytest
from bison_contracts import load_prompt

from router_service.actions import ACTION_MENUS, DECLARABLE_TYPES
from router_service.config import settings
from router_service.gating import RESERVED_PORT_HIGH, RESERVED_PORT_LOW, SUGGESTED_PORT
from router_service.manifest import CAPABILITY_NAMES
from router_service.plan import FAILURE_POLICIES, INTENTS, SERVICES

TOP_LEVEL_KEYS = ("intent", "rationale", "steps")

STEP_KEYS = (
    "description",
    "service",
    "action",
    "effects",
    "on_failure",
    "criterion_refs",
)

EFFECT_KEYS = (
    "writes_paths",
    "deletes_paths",
    "network",
    "installs_packages",
    "needs_credentials",
    "drives_input",
    "reversible",
)

ACTION_FIELDS = (
    "path",
    "content",
    "script_path",
    "module",
    "arguments",
    "packages",
    "line",
)


def prompt_text() -> str:
    resolved = settings()
    raw = load_prompt(resolved.prompt_name, resolved.prompt_version).text

    return re.sub(r"\s+", " ", raw)


@pytest.mark.parametrize("key", TOP_LEVEL_KEYS)
def test_the_prompt_names_every_top_level_key(key: str) -> None:
    assert key in prompt_text()


@pytest.mark.parametrize("key", STEP_KEYS)
def test_the_prompt_names_every_step_key(key: str) -> None:
    assert key in prompt_text()


@pytest.mark.parametrize("key", EFFECT_KEYS)
def test_the_prompt_names_every_effect_key(key: str) -> None:
    assert key in prompt_text()


@pytest.mark.parametrize("intent", sorted(INTENTS))
def test_the_prompt_lists_every_intent(intent: str) -> None:
    assert intent in prompt_text()


@pytest.mark.parametrize("service", sorted(SERVICES))
def test_the_prompt_lists_every_service(service: str) -> None:
    assert service in prompt_text()


@pytest.mark.parametrize("policy", sorted(FAILURE_POLICIES))
def test_the_prompt_lists_every_failure_policy(policy: str) -> None:
    assert policy in prompt_text()


@pytest.mark.parametrize("action_type", sorted(DECLARABLE_TYPES))
def test_the_prompt_lists_every_action_type(action_type: str) -> None:
    assert action_type in prompt_text()


@pytest.mark.parametrize("field", ACTION_FIELDS)
def test_the_prompt_names_every_action_field(field: str) -> None:
    assert field in prompt_text()


def test_the_prompt_says_an_action_may_be_null() -> None:
    assert "null" in prompt_text()


@pytest.mark.parametrize("service", sorted(ACTION_MENUS))
def test_the_prompt_names_every_service_that_requires_an_action(service: str) -> None:
    assert f"{service} step" in prompt_text()


@pytest.mark.parametrize("service", sorted(ACTION_MENUS))
def test_the_prompt_gives_every_service_that_carries_an_action_its_own_menu(service: str) -> None:
    assert f"The {service} action menu" in prompt_text()


def test_the_prompt_forbids_command_lines() -> None:
    text = prompt_text()

    assert "never carries a command line" in text


def test_the_prompt_requires_a_written_path_to_be_declared() -> None:
    assert "appears in writes_paths as well" in prompt_text()


def test_the_prompt_names_the_machine_block() -> None:
    assert "MACHINE block" in prompt_text()


@pytest.mark.parametrize("capability", sorted(CAPABILITY_NAMES))
def test_the_prompt_names_every_capability_the_context_renders(capability: str) -> None:
    assert capability in prompt_text()


def test_the_prompt_names_every_hardware_fact_the_context_renders() -> None:
    text = prompt_text()

    assert "operating system" in text
    assert "core count" in text
    assert "memory" in text
    assert "free disk" in text


def test_the_prompt_says_an_unavailable_capability_cannot_be_used() -> None:
    assert "strength is unavailable cannot be used" in prompt_text()


def test_the_prompt_says_the_machine_is_reread_on_every_plan() -> None:
    text = prompt_text()

    assert "read afresh every time a plan is made" in text
    assert "re-planned" in text


def test_the_service_is_configured_with_a_prompt_that_knows_about_the_machine() -> None:
    resolved = settings()

    assert resolved.prompt_version == "v9"
    assert "MACHINE" in load_prompt(resolved.prompt_name, resolved.prompt_version).text


def test_the_service_is_configured_with_a_prompt_that_knows_about_actions() -> None:
    resolved = settings()

    assert resolved.prompt_name == "router"
    assert "action" in load_prompt(resolved.prompt_name, resolved.prompt_version).text


@pytest.mark.parametrize("service", ["automation", "engine-session"])
def test_the_prompt_offers_no_service_the_router_refuses(service: str) -> None:
    resolved = settings()
    raw = load_prompt(resolved.prompt_name, resolved.prompt_version).text
    offered = [line for line in raw.splitlines() if line.startswith(service)]

    assert offered == []


def test_the_prompt_states_that_order_is_checked() -> None:
    text = prompt_text()

    assert "Write first, then open or run." in text
    assert "install_python_packages" in text


def test_the_prompt_forbids_planning_a_virtual_environment() -> None:
    assert "Never plan a step that creates a virtual environment" in prompt_text()


def test_the_prompt_tells_the_model_a_task_asking_for_an_environment_is_already_met() -> None:
    text = prompt_text()

    assert "Treat that part of the task as already done." in text
    assert "rejected, and so is a step that runs pip, venv, virtualenv or ensurepip" in text


def test_the_prompt_names_the_workspace_block() -> None:
    assert "WORKSPACE FILES block" in prompt_text()


def test_the_prompt_says_what_a_workspace_line_carries() -> None:
    text = prompt_text()

    assert "size in bytes" in text
    assert "names it defines at the top level" in text


def test_the_prompt_requires_code_to_use_the_names_on_disk() -> None:
    assert "must use the names those files actually define" in prompt_text()


def test_the_prompt_says_a_missing_name_is_written_rather_than_assumed() -> None:
    text = prompt_text()

    assert "write it in this plan rather than assume it" in text
    assert "imports a name no file defines" in text


def test_the_prompt_says_an_empty_working_directory_is_stated() -> None:
    assert "the working directory is empty" in prompt_text()


def test_the_prompt_names_the_reserved_port_range_the_router_enforces() -> None:
    text = prompt_text()

    assert f"Ports {RESERVED_PORT_LOW} to {RESERVED_PORT_HIGH} belong to" in text
    assert f"above {RESERVED_PORT_HIGH}" in text
    assert str(SUGGESTED_PORT) in text


def test_the_prompt_says_a_reserved_port_is_refused() -> None:
    text = prompt_text()

    assert "Never bind one" in text
    assert "sent back to you with the step named" in text
