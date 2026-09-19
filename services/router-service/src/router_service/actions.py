from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any, ClassVar, Final

TASK_RUNNER_SERVICE: Final[str] = "task-runner"
DEV_ENV_SERVICE: Final[str] = "dev-env"

TASK_RUNNER_TYPES: Final[frozenset[str]] = frozenset(
    {
        "write_file",
        "run_python_script",
        "run_python_module",
        "install_python_packages",
    }
)

DEV_ENV_TYPES: Final[frozenset[str]] = frozenset({"open_in_editor"})

DECLARABLE_TYPES: Final[frozenset[str]] = TASK_RUNNER_TYPES | DEV_ENV_TYPES

ACTION_MENUS: Final[dict[str, frozenset[str]]] = {
    TASK_RUNNER_SERVICE: TASK_RUNNER_TYPES,
    DEV_ENV_SERVICE: DEV_ENV_TYPES,
}

MAX_CONTENT_CHARS: Final[int] = 200_000
MAX_ARGUMENTS: Final[int] = 32
MAX_PACKAGES: Final[int] = 32


class ActionSpecError(RuntimeError):
    def __init__(self, detail: str) -> None:
        super().__init__(detail)
        self.detail = detail


@dataclass(frozen=True)
class WriteFile:
    path: str
    content: str
    TYPE: ClassVar[str] = "write_file"


@dataclass(frozen=True)
class RunPythonScript:
    script_path: str
    arguments: tuple[str, ...]
    TYPE: ClassVar[str] = "run_python_script"


@dataclass(frozen=True)
class RunPythonModule:
    module: str
    arguments: tuple[str, ...]
    TYPE: ClassVar[str] = "run_python_module"


@dataclass(frozen=True)
class InstallPythonPackages:
    packages: tuple[str, ...]
    TYPE: ClassVar[str] = "install_python_packages"


@dataclass(frozen=True)
class OpenInEditor:
    path: str
    line: int | None
    TYPE: ClassVar[str] = "open_in_editor"


Action = WriteFile | RunPythonScript | RunPythonModule | InstallPythonPackages | OpenInEditor


def listed(types: frozenset[str]) -> str:
    return ", ".join(sorted(types))


def payload(action: Action) -> dict[str, Any]:
    fields = {
        key: list(value) if isinstance(value, tuple) else value
        for key, value in asdict(action).items()
    }

    return {"type": action.TYPE, **fields}


def written_paths(action: Action) -> tuple[str, ...]:
    if isinstance(action, WriteFile):
        return (action.path,)

    return ()


def opened_paths(action: Action) -> tuple[str, ...]:
    if isinstance(action, OpenInEditor):
        return (action.path,)

    return ()


def installs_packages(action: Action) -> bool:
    return isinstance(action, InstallPythonPackages)


def text(source: dict[str, Any], key: str, label: str) -> str:
    value = source.get(key)

    if not isinstance(value, str) or not value.strip():
        raise ActionSpecError(f"{label}.{key} must be a non-empty string")

    return value.strip()


def body(source: dict[str, Any], key: str, label: str) -> str:
    value = source.get(key)

    if not isinstance(value, str):
        raise ActionSpecError(f"{label}.{key} must be a string, and may be empty")

    if len(value) > MAX_CONTENT_CHARS:
        raise ActionSpecError(
            f"{label}.{key} must be under {MAX_CONTENT_CHARS} characters; "
            "split the file or write it in more than one step"
        )

    return value


def strings(source: dict[str, Any], key: str, label: str, limit: int) -> tuple[str, ...]:
    value = source.get(key, [])

    if value is None:
        return ()

    if not isinstance(value, list):
        raise ActionSpecError(f"{label}.{key} must be an array of strings")

    if len(value) > limit:
        raise ActionSpecError(f"{label}.{key} must hold no more than {limit} entries")

    collected: list[str] = []

    for index, item in enumerate(value):
        if not isinstance(item, str):
            raise ActionSpecError(f"{label}.{key}[{index}] must be a string")

        collected.append(item)

    return tuple(collected)


def named(source: dict[str, Any], key: str, label: str, limit: int) -> tuple[str, ...]:
    collected = strings(source, key, label, limit)

    for index, item in enumerate(collected):
        if not item.strip():
            raise ActionSpecError(f"{label}.{key}[{index}] must be a non-empty string")

    return tuple(item.strip() for item in collected)


def line_number(source: dict[str, Any], key: str, label: str) -> int | None:
    value = source.get(key)

    if value is None:
        return None

    if isinstance(value, bool) or not isinstance(value, int) or value < 1:
        raise ActionSpecError(f"{label}.{key} must be a whole number from 1, or null")

    return value


def declared_type(entry: Any, label: str, menu: frozenset[str]) -> str:
    if not isinstance(entry, dict):
        raise ActionSpecError(f"{label} must be an object")

    declared = entry.get("type")

    if not isinstance(declared, str) or not declared:
        raise ActionSpecError(f"{label}.type must be one of {listed(menu)}")

    if declared not in DECLARABLE_TYPES:
        raise ActionSpecError(
            f"{label}.type {declared} is not an action this machine performs; "
            f"use one of {listed(menu)}"
        )

    return declared


def parse(entry: Any, label: str) -> Action:
    declared = declared_type(entry, label, DECLARABLE_TYPES)

    if declared == WriteFile.TYPE:
        return WriteFile(
            path=text(entry, "path", label),
            content=body(entry, "content", label),
        )

    if declared == RunPythonScript.TYPE:
        return RunPythonScript(
            script_path=text(entry, "script_path", label),
            arguments=strings(entry, "arguments", label, MAX_ARGUMENTS),
        )

    if declared == RunPythonModule.TYPE:
        return RunPythonModule(
            module=text(entry, "module", label),
            arguments=strings(entry, "arguments", label, MAX_ARGUMENTS),
        )

    if declared == OpenInEditor.TYPE:
        return OpenInEditor(
            path=text(entry, "path", label),
            line=line_number(entry, "line", label),
        )

    packages = named(entry, "packages", label, MAX_PACKAGES)

    if not packages:
        raise ActionSpecError(f"{label}.packages must name at least one package")

    return InstallPythonPackages(packages=packages)


def parse_for(entry: Any, service: str, label: str) -> Action | None:
    menu = ACTION_MENUS.get(service)

    if menu is None:
        if entry is None:
            return None

        carriers = " and ".join(sorted(ACTION_MENUS))
        raise ActionSpecError(
            f"{label} must be null for a {service} step; only {carriers} steps carry an action"
        )

    if entry is None:
        raise ActionSpecError(
            f"{label} is required for a {service} step; name one of {listed(menu)}"
        )

    declared = declared_type(entry, label, menu)

    if declared not in menu:
        raise ActionSpecError(
            f"{label}.type {declared} is not an action a {service} step performs; "
            f"use one of {listed(menu)}"
        )

    return parse(entry, label)
