from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, replace
from pathlib import Path, PureWindowsPath
from typing import Literal

from router_service.actions import (
    Action,
    installs_packages,
    opened_paths,
    required_paths,
    written_paths,
)
from router_service.plan import Effects, ProposedStep, RouterDraft

SAFE_FAILURE_POLICY = "abort"
MAX_PATHS_NAMED = 3
MAX_PROBLEMS_NAMED = 3

Presence = Literal["file", "folder", "missing"]

Disk = Callable[[str], Presence]


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


def sequence(draft: RouterDraft, root: list[str], disk: Disk) -> None:
    problems = out_of_order(draft, root, disk)

    if not problems:
        return

    named = "; ".join(problems[:MAX_PROBLEMS_NAMED])
    remaining = len(problems) - min(len(problems), MAX_PROBLEMS_NAMED)
    tail = f"; and {remaining} more" if remaining > 0 else ""

    raise PlanRejectedError(f"the plan uses files out of order: {named}{tail}")


def build(
    draft: RouterDraft,
    scope_root: str,
    criterion_ids: list[str],
    disk: Disk = on_disk,
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

    sequence(draft, root, disk)

    steps = [gate(step, position, root) for position, step in enumerate(draft.steps)]

    return GatedPlan(
        intent=draft.intent,
        rationale=draft.rationale,
        steps=steps,
        gated_count=sum(1 for step in steps if step.requires_confirmation),
    )
