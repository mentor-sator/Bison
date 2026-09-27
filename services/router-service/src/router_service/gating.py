from __future__ import annotations

import ast
import re
from collections.abc import Callable, Sequence
from dataclasses import dataclass, replace
from pathlib import Path, PureWindowsPath
from typing import Final, Literal

from router_service.actions import (
    Action,
    InstallPythonPackages,
    OpenInEditor,
    RunPythonModule,
    RunPythonScript,
    WriteFile,
    installs_packages,
    opened_paths,
    required_paths,
    written_paths,
)
from router_service.context import Criterion, WorkspaceFile
from router_service.plan import Effects, ProposedStep, RouterDraft
from router_service.workspace import defined_names

SAFE_FAILURE_POLICY = "abort"
MAX_PATHS_NAMED = 3
MAX_PROBLEMS_NAMED = 3

Presence = Literal["file", "folder", "missing"]

PROVISIONING_MODULES: Final[frozenset[str]] = frozenset({"pip", "venv", "virtualenv", "ensurepip"})

SCRIPT_SUFFIXES: Final[frozenset[str]] = frozenset({".py", ".bat", ".cmd", ".ps1", ".sh"})

PROVISIONING_PATTERNS: Final[tuple[re.Pattern[str], ...]] = (
    re.compile(r"\bpip3?(?:\.exe)?[\"']?\s*,?\s*[\"']?install\b", re.IGNORECASE),
    re.compile(r"-m[\"']?\s*,?\s*[\"']?(?:pip|venv|virtualenv|ensurepip)\b", re.IGNORECASE),
    re.compile(r"\b(?:venv|virtualenv)\s*\.\s*(?:create|EnvBuilder|cli_run)\b", re.IGNORECASE),
    re.compile(r"\bimport\s+(?:pip|venv|virtualenv|ensurepip)\b", re.IGNORECASE),
    re.compile(r"\bfrom\s+(?:pip|venv|virtualenv|ensurepip)(?:\.\w+)*\s+import\b", re.IGNORECASE),
)

INSTALL_VERBS: Final[frozenset[str]] = frozenset({"install"})

NAME: Final[str] = r"[A-Za-z0-9](?:[A-Za-z0-9._-]*[A-Za-z0-9])?"
EXTRAS: Final[str] = rf"(?:\[{NAME}(?:,{NAME})*\])?"
CLAUSE: Final[str] = r"(?:===|==|!=|<=|>=|~=|<|>)[A-Za-z0-9.*+!_-]+"
SPECIFIER: Final[str] = rf"(?:{CLAUSE}(?:,{CLAUSE})*)?"
REQUIREMENT: Final[re.Pattern[str]] = re.compile(rf"{NAME}{EXTRAS}{SPECIFIER}")

RESERVED_PORT_LOW: Final[int] = 8000
RESERVED_PORT_HIGH: Final[int] = 9000
SUGGESTED_PORT: Final[int] = 9101

PORT_PATTERNS: Final[tuple[re.Pattern[str], ...]] = (
    re.compile(r"(?<![A-Za-z])port[\"']?\s*[=:]\s*[\"']?(\d{2,5})", re.IGNORECASE),
    re.compile(r"(?<![A-Za-z])port\s*:\s*int\s*=\s*(\d{2,5})", re.IGNORECASE),
    re.compile(r"--port[=\s]+[\"']?(\d{2,5})", re.IGNORECASE),
    re.compile(r"(?:127\.0\.0\.1|0\.0\.0\.0|localhost):(\d{2,5})", re.IGNORECASE),
    re.compile(r"\.listen\(\s*(\d{2,5})"),
    re.compile(r"\bbind\(\s*\(\s*[\"'][^\"']*[\"']\s*,\s*(\d{2,5})"),
)

PORT_NUMBER: Final[re.Pattern[str]] = re.compile(r"\d{2,5}")

PYTHON_SUFFIX: Final[str] = ".py"
DETERMINISTIC: Final[str] = "deterministic"
SETTLED_CRITERIA: Final[frozenset[str]] = frozenset({"verified", "ignored"})
DATABASE_CHECKS: Final[frozenset[str]] = frozenset({"sql_result"})
FILE_CHECKS: Final[frozenset[str]] = frozenset({"file_exists", "file_hash"})

ARGUMENT_READERS: Final[tuple[str, ...]] = (
    "sys.argv",
    "argparse",
    "getopt",
    "optparse",
    "click",
    "typer",
    "fire",
)
PLACEHOLDER_DECORATORS: Final[frozenset[str]] = frozenset({"abstractmethod", "overload"})
PROTOCOL_BASES: Final[frozenset[str]] = frozenset({"Protocol", "ABC"})
DECLARATIVE: Final[tuple[type[ast.stmt], ...]] = (
    ast.Import,
    ast.ImportFrom,
    ast.FunctionDef,
    ast.AsyncFunctionDef,
    ast.ClassDef,
    ast.Pass,
)

Disk = Callable[[str], Presence]
Reader = Callable[[str], str | None]


class PlanRejectedError(RuntimeError):
    def __init__(self, detail: str) -> None:
        super().__init__(detail)
        self.detail = detail


@dataclass(frozen=True)
class GatedStep:
    position: int
    description: str
    service: str
    action: Action | None
    requires_confirmation: bool
    confirmation_reason: str | None
    on_failure: str
    reversible: bool
    criterion_refs: list[str]
    effects: Effects


@dataclass(frozen=True)
class GatedPlan:
    intent: str
    rationale: str
    steps: list[GatedStep]
    gated_count: int


def normalise(path: PureWindowsPath) -> list[str] | None:
    collected: list[str] = []

    for part in path.parts:
        if part == ".":
            continue

        if part == "..":
            if not collected:
                return None

            collected.pop()
            continue

        collected.append(part.lower())

    return collected


def within(path: str, root: list[str]) -> bool:
    candidate = PureWindowsPath(path)
    absolute = candidate if candidate.is_absolute() else PureWindowsPath(*root) / candidate
    resolved = normalise(absolute)

    if resolved is None or len(resolved) < len(root):
        return False

    return resolved[: len(root)] == root


def outside(paths: list[str], root: list[str]) -> list[str]:
    return [path for path in paths if not within(path, root)]


def named_paths(paths: list[str]) -> str:
    listed = ", ".join(paths[:MAX_PATHS_NAMED])
    remaining = len(paths) - min(len(paths), MAX_PATHS_NAMED)

    return f"{listed} and {remaining} more" if remaining > 0 else listed


def reconciled(declared: Effects, action: Action | None) -> Effects:
    if action is None:
        return declared

    undeclared = [path for path in written_paths(action) if path not in declared.writes_paths]
    installs = declared.installs_packages or installs_packages(action)

    if not undeclared and installs == declared.installs_packages:
        return declared

    return replace(
        declared,
        writes_paths=declared.writes_paths + undeclared,
        installs_packages=installs,
    )


def reasons(effects: Effects, root: list[str]) -> list[str]:
    collected: list[str] = []

    if effects.deletes_paths:
        collected.append(f"deletes {len(effects.deletes_paths)} path(s)")

    escaped = outside(effects.writes_paths + effects.deletes_paths, root)

    if escaped:
        collected.append(f"touches {named_paths(escaped)} outside the project directory")

    if effects.needs_credentials:
        collected.append("needs credentials")

    if effects.network:
        collected.append("reaches the network")

    if effects.installs_packages:
        collected.append("installs packages")

    if effects.drives_input:
        collected.append("moves the mouse or types")

    if not effects.reversible:
        collected.append("cannot be undone")

    return collected


def openings(action: Action | None, root: list[str]) -> list[str]:
    if action is None:
        return []

    escaped = outside(list(opened_paths(action)), root)

    if not escaped:
        return []

    return [f"opens {named_paths(escaped)} outside the project directory"]


def gate(step: ProposedStep, position: int, root: list[str]) -> GatedStep:
    effects = reconciled(step.effects, step.action)
    triggered = reasons(effects, root) + openings(step.action, root)
    confirm = bool(triggered)
    demoted = confirm and step.on_failure == "continue"

    return GatedStep(
        position=position,
        description=step.description,
        service=step.service,
        action=step.action,
        requires_confirmation=confirm,
        confirmation_reason="; ".join(triggered) if confirm else None,
        on_failure=SAFE_FAILURE_POLICY if demoted else step.on_failure,
        reversible=effects.reversible,
        criterion_refs=step.criterion_refs,
        effects=effects,
    )


def unknown_refs(draft: RouterDraft, known: set[str]) -> list[str]:
    collected: list[str] = []

    for step in draft.steps:
        for reference in step.criterion_refs:
            if reference not in known and reference not in collected:
                collected.append(reference)

    return collected


def on_disk(path: str) -> Presence:
    candidate = Path(path)

    if candidate.is_file():
        return "file"

    if candidate.is_dir():
        return "folder"

    return "missing"


def read_text(path: str) -> str | None:
    candidate = Path(path)

    try:
        return candidate.read_text(encoding="utf-8") if candidate.is_file() else None
    except (OSError, UnicodeDecodeError):
        return None


def absolute(path: str, root: list[str]) -> PureWindowsPath:
    candidate = PureWindowsPath(path)

    return candidate if candidate.is_absolute() else PureWindowsPath(*root) / candidate


def identity(path: str, root: list[str]) -> tuple[str, ...] | None:
    segments = normalise(absolute(path, root))

    return tuple(segments) if segments is not None else None


def step_writes(step: ProposedStep) -> list[str]:
    declared = list(step.effects.writes_paths)

    if step.action is not None:
        declared.extend(written_paths(step.action))

    return declared


def first_writers(draft: RouterDraft, root: list[str]) -> dict[tuple[str, ...], int]:
    writers: dict[tuple[str, ...], int] = {}

    for position, step in enumerate(draft.steps):
        for path in step_writes(step):
            key = identity(path, root)

            if key is not None:
                writers.setdefault(key, position)

    return writers


def out_of_order(draft: RouterDraft, root: list[str], disk: Disk) -> list[str]:
    writers = first_writers(draft, root)
    problems: list[str] = []

    for position, step in enumerate(draft.steps):
        if step.action is None:
            continue

        for verb, path in required_paths(step.action):
            key = identity(path, root)

            if key is None:
                continue

            writer = writers.get(key)

            if writer is not None and writer < position:
                continue

            if writer is not None and writer > position:
                problems.append(
                    f"steps[{position}] {verb} {path} before steps[{writer}] writes it; "
                    "move the write earlier"
                )
                continue

            presence = disk(str(absolute(path, root)))

            if presence == "folder":
                problems.append(f"steps[{position}] {verb} {path}, which is a folder; name a file")
            elif presence == "missing":
                problems.append(
                    f"steps[{position}] {verb} {path}, which no earlier step writes "
                    "and which does not exist"
                )

    return problems


def root_module(module: str) -> str:
    return module.strip().split(".")[0].lower()


def is_script(path: str) -> bool:
    return PureWindowsPath(path).suffix.lower() in SCRIPT_SUFFIXES


def provisions(content: str) -> bool:
    return any(pattern.search(content) for pattern in PROVISIONING_PATTERNS)


def requested_packages(action: Action) -> tuple[str, ...] | None:
    if not isinstance(action, RunPythonModule) or root_module(action.module) != "pip":
        return None

    arguments = [argument.strip() for argument in action.arguments if argument.strip()]

    if not arguments or arguments[0] not in INSTALL_VERBS:
        return None

    named = arguments[1:]

    if not named or not all(REQUIREMENT.fullmatch(entry) for entry in named):
        return None

    return tuple(named)


def as_install(step: ProposedStep, packages: tuple[str, ...]) -> ProposedStep:
    effects = replace(step.effects, network=True, installs_packages=True)

    return replace(
        step,
        action=InstallPythonPackages(packages=packages),
        effects=effects,
    )


def installed_through_the_runner(draft: RouterDraft) -> RouterDraft:
    converted: list[ProposedStep] = []
    changed = False

    for step in draft.steps:
        packages = requested_packages(step.action) if step.action is not None else None

        if packages is None:
            converted.append(step)
            continue

        converted.append(as_install(step, packages))
        changed = True

    return replace(draft, steps=converted) if changed else draft


def self_provisioning(draft: RouterDraft) -> list[str]:
    problems: list[str] = []

    for position, step in enumerate(draft.steps):
        action = step.action

        if isinstance(action, RunPythonModule) and root_module(action.module) in (
            PROVISIONING_MODULES
        ):
            problems.append(f"steps[{position}] runs the {root_module(action.module)} module")
        elif (
            isinstance(action, WriteFile) and is_script(action.path) and provisions(action.content)
        ):
            problems.append(
                f"steps[{position}] writes {action.path}, a script that installs packages "
                "or creates a virtual environment"
            )

    return problems


def environment_left_alone(draft: RouterDraft) -> None:
    problems = self_provisioning(draft)

    if not problems:
        return

    named = "; ".join(problems[:MAX_PROBLEMS_NAMED])
    remaining = len(problems) - min(len(problems), MAX_PROBLEMS_NAMED)
    tail = f"; and {remaining} more" if remaining > 0 else ""

    raise PlanRejectedError(
        f"the plan builds its own Python environment: {named}{tail}. The task already has one; "
        "add packages with an install_python_packages step and never create a virtual environment"
    )


def reserved(value: int) -> bool:
    return RESERVED_PORT_LOW <= value <= RESERVED_PORT_HIGH


def reserved_in(text: str) -> list[int]:
    found: list[int] = []

    for pattern in PORT_PATTERNS:
        for match in pattern.finditer(text):
            value = int(match.group(1))

            if reserved(value) and value not in found:
                found.append(value)

    return found


def reserved_arguments(arguments: tuple[str, ...]) -> list[int]:
    found: list[int] = []

    for argument in arguments:
        stripped = argument.strip()
        bare = PORT_NUMBER.fullmatch(stripped)
        values = [int(stripped)] if bare else reserved_in(stripped)

        for value in values:
            if reserved(value) and value not in found:
                found.append(value)

    return found


def occupied(step: ProposedStep, position: int) -> list[str]:
    action = step.action

    if isinstance(action, WriteFile):
        return [
            f"steps[{position}] writes {action.path}, which binds port {port}"
            for port in reserved_in(action.content)
        ]

    if isinstance(action, RunPythonModule):
        return [
            f"steps[{position}] runs the {action.module} module on port {port}"
            for port in reserved_arguments(action.arguments)
        ]

    if isinstance(action, RunPythonScript):
        return [
            f"steps[{position}] runs {action.script_path} on port {port}"
            for port in reserved_arguments(action.arguments)
        ]

    return []


def ports_left_free(draft: RouterDraft) -> None:
    problems = [
        problem for position, step in enumerate(draft.steps) for problem in occupied(step, position)
    ]

    if not problems:
        return

    named = "; ".join(problems[:MAX_PROBLEMS_NAMED])
    remaining = len(problems) - min(len(problems), MAX_PROBLEMS_NAMED)
    tail = f"; and {remaining} more" if remaining > 0 else ""

    raise PlanRejectedError(
        f"the plan takes a port BISON is using: {named}{tail}. Ports {RESERVED_PORT_LOW} to "
        f"{RESERVED_PORT_HIGH} belong to BISON's own services on this machine; bind a port "
        f"above {RESERVED_PORT_HIGH}, such as {SUGGESTED_PORT}"
    )


def settled(draft: RouterDraft, root: list[str]) -> RouterDraft:
    writers = first_writers(draft, root)
    waiting: dict[int, list[ProposedStep]] = {}
    ordered: list[ProposedStep] = []

    for position, step in enumerate(draft.steps):
        if isinstance(step.action, OpenInEditor):
            key = identity(step.action.path, root)
            writer = writers.get(key) if key is not None else None

            if writer is not None and writer > position:
                waiting.setdefault(writer, []).append(step)
                continue

        ordered.append(step)
        ordered.extend(waiting.pop(position, []))

    if ordered == draft.steps:
        return draft

    return replace(draft, steps=ordered)


def sequence(draft: RouterDraft, root: list[str], disk: Disk) -> None:
    problems = out_of_order(draft, root, disk)

    if not problems:
        return

    named = "; ".join(problems[:MAX_PROBLEMS_NAMED])
    remaining = len(problems) - min(len(problems), MAX_PROBLEMS_NAMED)
    tail = f"; and {remaining} more" if remaining > 0 else ""

    raise PlanRejectedError(f"the plan uses files out of order: {named}{tail}")


def anchored_path(path: str, scope_root: str) -> str:
    candidate = PureWindowsPath(path)

    if not path.strip() or candidate.is_absolute():
        return path

    return str(PureWindowsPath(scope_root) / candidate)


def anchored_action(action: Action | None, scope_root: str) -> Action | None:
    if isinstance(action, WriteFile):
        return replace(action, path=anchored_path(action.path, scope_root))

    if isinstance(action, RunPythonScript):
        return replace(action, script_path=anchored_path(action.script_path, scope_root))

    if isinstance(action, OpenInEditor):
        return replace(action, path=anchored_path(action.path, scope_root))

    return action


def anchored_step(step: ProposedStep, scope_root: str) -> ProposedStep:
    effects = replace(
        step.effects,
        writes_paths=[anchored_path(path, scope_root) for path in step.effects.writes_paths],
        deletes_paths=[anchored_path(path, scope_root) for path in step.effects.deletes_paths],
    )

    return replace(step, action=anchored_action(step.action, scope_root), effects=effects)


def anchored(draft: RouterDraft, scope_root: str) -> RouterDraft:
    steps = [anchored_step(step, scope_root) for step in draft.steps]

    return draft if steps == draft.steps else replace(draft, steps=steps)


def syntax_fault(content: str) -> str | None:
    try:
        ast.parse(content)
    except SyntaxError as error:
        where = f" on line {error.lineno}" if error.lineno else ""

        return f"{error.msg}{where}"
    except ValueError as error:
        return str(error)

    return None


def defined_on_disk(
    workspace: Sequence[WorkspaceFile], root: list[str]
) -> dict[tuple[str, ...], list[str]]:
    mapping: dict[tuple[str, ...], list[str]] = {}

    for entry in workspace:
        key = identity(entry.path, root)

        if key is not None and entry.names:
            mapping[key] = list(entry.names)

    return mapping


def broken_python(
    draft: RouterDraft, root: list[str], workspace: Sequence[WorkspaceFile]
) -> list[str]:
    existing = defined_on_disk(workspace, root)
    problems: list[str] = []

    for position, step in enumerate(draft.steps):
        action = step.action

        if not isinstance(action, WriteFile):
            continue

        if PureWindowsPath(action.path).suffix.lower() != PYTHON_SUFFIX:
            continue

        fault = syntax_fault(action.content)

        if fault is not None:
            problems.append(
                f"steps[{position}] writes {action.path}, which is not valid Python: {fault}"
            )
            continue

        key = identity(action.path, root)
        before = existing.get(key, []) if key is not None else []
        after = set(defined_names(action.content))
        dropped = [name for name in before if name not in after]

        if dropped:
            problems.append(
                f"steps[{position}] rewrites {action.path} without {', '.join(dropped)}, "
                "which the file defines now"
            )

    return problems


def decorator_name(node: ast.expr) -> str:
    target = node.func if isinstance(node, ast.Call) else node

    if isinstance(target, ast.Attribute):
        return target.attr

    return target.id if isinstance(target, ast.Name) else ""


def base_name(node: ast.expr) -> str:
    if isinstance(node, ast.Attribute):
        return node.attr

    return node.id if isinstance(node, ast.Name) else ""


def placeholder_statement(statement: ast.stmt) -> bool:
    if isinstance(statement, ast.Pass):
        return True

    if isinstance(statement, ast.Expr) and isinstance(statement.value, ast.Constant):
        return True

    if isinstance(statement, ast.Raise) and statement.exc is not None:
        raised = statement.exc.func if isinstance(statement.exc, ast.Call) else statement.exc

        return isinstance(raised, ast.Name) and raised.id == "NotImplementedError"

    return False


def placeholder_body(function: ast.FunctionDef | ast.AsyncFunctionDef) -> bool:
    if any(decorator_name(entry) in PLACEHOLDER_DECORATORS for entry in function.decorator_list):
        return False

    return all(placeholder_statement(statement) for statement in function.body)


def functions_of(tree: ast.Module) -> list[ast.FunctionDef | ast.AsyncFunctionDef]:
    found: list[ast.FunctionDef | ast.AsyncFunctionDef] = []

    for node in tree.body:
        if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef):
            found.append(node)
        elif isinstance(node, ast.ClassDef):
            if any(base_name(base) in PROTOCOL_BASES for base in node.bases):
                continue

            found.extend(
                member
                for member in node.body
                if isinstance(member, ast.FunctionDef | ast.AsyncFunctionDef)
            )

    return found


def placeholders(content: str) -> list[str]:
    try:
        tree = ast.parse(content)
    except (SyntaxError, ValueError):
        return []

    return [function.name for function in functions_of(tree) if placeholder_body(function)]


def hollow_python(draft: RouterDraft) -> list[str]:
    problems: list[str] = []

    for position, step in enumerate(draft.steps):
        action = step.action

        if not isinstance(action, WriteFile):
            continue

        if PureWindowsPath(action.path).suffix.lower() != PYTHON_SUFFIX:
            continue

        empty = placeholders(action.content)

        if empty:
            problems.append(
                f"steps[{position}] writes {action.path} with {', '.join(empty)} left as "
                "placeholders that do nothing"
            )

    return problems


def code_intact(draft: RouterDraft, root: list[str], workspace: Sequence[WorkspaceFile]) -> None:
    problems = broken_python(draft, root, workspace) + hollow_python(draft)

    if not problems:
        return

    named = "; ".join(problems[:MAX_PROBLEMS_NAMED])
    remaining = len(problems) - min(len(problems), MAX_PROBLEMS_NAMED)
    tail = f"; and {remaining} more" if remaining > 0 else ""

    raise PlanRejectedError(
        f"the plan writes Python that would break the project: {named}{tail}. A write replaces "
        "the whole file, so its content must be valid Python, must keep every name the file "
        "already defines, and every function must do the work it is named for"
    )


def main_guard(statement: ast.stmt) -> bool:
    if not isinstance(statement, ast.If):
        return False

    test = statement.test

    if not isinstance(test, ast.Compare) or len(test.comparators) != 1:
        return False

    sides = [test.left, test.comparators[0]]
    names = [side.id for side in sides if isinstance(side, ast.Name)]
    values = [side.value for side in sides if isinstance(side, ast.Constant)]

    return names == ["__name__"] and values == ["__main__"]


def calls_something(node: ast.AST) -> bool:
    return any(isinstance(child, ast.Call) for child in ast.walk(node))


def acts(statement: ast.stmt) -> bool:
    if isinstance(statement, DECLARATIVE):
        return False

    if isinstance(statement, ast.Expr) and isinstance(statement.value, ast.Constant):
        return False

    if isinstance(statement, ast.Assign | ast.AnnAssign):
        value = statement.value

        return value is not None and calls_something(value)

    return True


def inert(content: str) -> bool:
    try:
        tree = ast.parse(content)
    except (SyntaxError, ValueError):
        return False

    return not any(main_guard(statement) or acts(statement) for statement in tree.body)


def reads_arguments(content: str) -> bool:
    return any(reader in content for reader in ARGUMENT_READERS)


def script_source(
    draft: RouterDraft, position: int, path: str, root: list[str], read: Reader
) -> str | None:
    key = identity(path, root)
    written: str | None = None

    for earlier in draft.steps[:position]:
        action = earlier.action

        if isinstance(action, WriteFile) and identity(action.path, root) == key:
            written = action.content

    if written is not None:
        return written

    return read(str(absolute(path, root)))


def idle_runs(draft: RouterDraft, root: list[str], read: Reader) -> list[str]:
    problems: list[str] = []

    for position, step in enumerate(draft.steps):
        action = step.action

        if not isinstance(action, RunPythonScript):
            continue

        source = script_source(draft, position, action.script_path, root, read)

        if source is None:
            continue

        if inert(source):
            problems.append(
                f"steps[{position}] runs {action.script_path}, which only defines names and has "
                "no if __name__ == '__main__' block, so running it does nothing"
            )
            continue

        if action.arguments and not reads_arguments(source):
            problems.append(
                f"steps[{position}] passes {' '.join(action.arguments)} to "
                f"{action.script_path}, which never reads its arguments"
            )

    return problems


def runs_effective(draft: RouterDraft, root: list[str], read: Reader) -> None:
    problems = idle_runs(draft, root, read)

    if not problems:
        return

    named = "; ".join(problems[:MAX_PROBLEMS_NAMED])
    remaining = len(problems) - min(len(problems), MAX_PROBLEMS_NAMED)
    tail = f"; and {remaining} more" if remaining > 0 else ""

    raise PlanRejectedError(
        f"the plan runs programs that cannot do what it runs them for: {named}{tail}. A script "
        "that is run must act when run, through an if __name__ == '__main__' block or statements "
        "at its top level, and must read any arguments it is given; write that into the script "
        "in an earlier step, or run a script that already does it"
    )


def fresh_write(
    step: ProposedStep,
    position: int,
    root: list[str],
    disk: Disk,
    writers: dict[tuple[str, ...], int],
) -> bool:
    action = step.action
    effects = step.effects

    if not isinstance(action, WriteFile):
        return False

    if effects.deletes_paths or effects.network or effects.installs_packages:
        return False

    if effects.needs_credentials or effects.drives_input:
        return False

    paths = list(dict.fromkeys(step_writes(step)))

    for path in paths:
        key = identity(path, root)

        if key is None or not within(path, root) or writers.get(key) != position:
            return False

        if disk(str(absolute(path, root))) != "missing":
            return False

    return bool(paths)


def undoable(draft: RouterDraft, root: list[str], disk: Disk) -> RouterDraft:
    writers = first_writers(draft, root)
    steps = [
        replace(step, effects=replace(step.effects, reversible=True))
        if not step.effects.reversible and fresh_write(step, position, root, disk, writers)
        else step
        for position, step in enumerate(draft.steps)
    ]

    return draft if steps == draft.steps else replace(draft, steps=steps)


def run_refs(draft: RouterDraft) -> set[str]:
    return {
        reference
        for step in draft.steps
        if isinstance(step.action, RunPythonScript | RunPythonModule)
        for reference in step.criterion_refs
    }


def unobserved(
    draft: RouterDraft, root: list[str], criteria: Sequence[Criterion], disk: Disk
) -> list[str]:
    writers = first_writers(draft, root)
    ran = run_refs(draft)
    problems: list[str] = []

    for criterion in criteria:
        if criterion.status in SETTLED_CRITERIA or criterion.check_kind != DETERMINISTIC:
            continue

        if criterion.criterion_id in ran:
            continue

        kind = criterion.check_type
        target = criterion.check_target

        if kind in DATABASE_CHECKS:
            problems.append(
                f"criterion {criterion.criterion_id} checks {target or 'a database'}, "
                "which changes only when a program runs"
            )
            continue

        if kind not in FILE_CHECKS or target is None:
            continue

        key = identity(target, root)

        if key is None or key in writers or disk(str(absolute(target, root))) == "file":
            continue

        problems.append(
            f"criterion {criterion.criterion_id} checks {target}, which no step writes, "
            "so only a program that runs can produce it"
        )

    return problems


def effects_observed(
    draft: RouterDraft, root: list[str], criteria: Sequence[Criterion], disk: Disk
) -> None:
    problems = unobserved(draft, root, criteria, disk)

    if not problems:
        return

    named = "; ".join(problems[:MAX_PROBLEMS_NAMED])
    remaining = len(problems) - min(len(problems), MAX_PROBLEMS_NAMED)
    tail = f"; and {remaining} more" if remaining > 0 else ""

    raise PlanRejectedError(
        f"the plan never runs the program its criteria depend on: {named}{tail}. Add a "
        "run_python_script or run_python_module step after the step that writes the program, "
        "and list each of these criterion ids in that run step's criterion_refs"
    )


def build(
    draft: RouterDraft,
    scope_root: str,
    criterion_ids: list[str],
    disk: Disk = on_disk,
    *,
    criteria: Sequence[Criterion] = (),
    workspace: Sequence[WorkspaceFile] = (),
    read: Reader = read_text,
) -> GatedPlan:
    root = normalise(PureWindowsPath(scope_root))

    if root is None or not PureWindowsPath(scope_root).is_absolute():
        raise ValueError("the project scope root must be an absolute path")

    known = set(criterion_ids)
    invented = unknown_refs(draft, known)

    if invented:
        listed = ", ".join(invented[:MAX_PATHS_NAMED])
        raise PlanRejectedError(f"the plan references criteria that do not exist: {listed}")

    if known and not any(step.criterion_refs for step in draft.steps):
        raise PlanRejectedError("the plan advances none of this task's acceptance criteria")

    installing = installed_through_the_runner(anchored(draft, scope_root))

    environment_left_alone(installing)
    ports_left_free(installing)
    ordered = settled(installing, root)
    sequence(ordered, root, disk)
    code_intact(ordered, root, workspace)
    runs_effective(ordered, root, read)
    effects_observed(ordered, root, criteria, disk)
    trusted = undoable(ordered, root, disk)

    steps = [gate(step, position, root) for position, step in enumerate(trusted.steps)]

    return GatedPlan(
        intent=trusted.intent,
        rationale=trusted.rationale,
        steps=steps,
        gated_count=sum(1 for step in steps if step.requires_confirmation),
    )
