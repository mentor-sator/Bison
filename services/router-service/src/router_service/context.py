from __future__ import annotations

from dataclasses import dataclass, field

MAX_STATEMENT_CHARS = 500
MAX_DESCRIPTION_CHARS = 4000
MAX_NOTE_CHARS = 500
MAX_HISTORY_ENTRIES = 12
MAX_WORKSPACE_FILES = 40
MAX_NAMES_PER_FILE = 12
MAX_CONTEXT_CHARS = 24000

SHRINK_STEPS = (
    (MAX_HISTORY_ENTRIES, MAX_WORKSPACE_FILES),
    (6, MAX_WORKSPACE_FILES),
    (3, MAX_WORKSPACE_FILES),
    (0, MAX_WORKSPACE_FILES),
    (0, 16),
    (0, 6),
    (0, 0),
)

NO_BACKEND = "none"


@dataclass(frozen=True)
class Criterion:
    criterion_id: str
    statement: str
    check_kind: str
    status: str


@dataclass(frozen=True)
class TaskFacts:
    title: str
    description: str
    kind: str
    state: str


@dataclass(frozen=True)
class Capability:
    name: str
    backend: str | None
    strength: str


@dataclass(frozen=True)
class MachineFacts:
    os_version: str
    cpu_cores: int
    ram_gb: float
    free_disk_gb: float
    capabilities: list[Capability] = field(default_factory=list)


@dataclass(frozen=True)
class BriefFacts:
    interpreted_goal: str
    project_type: str
    known_constraints: list[str] = field(default_factory=list)
    out_of_scope: list[str] = field(default_factory=list)
    assumptions: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class HistoryEntry:
    title: str
    state: str
    note: str | None = None


@dataclass(frozen=True)
class WorkspaceFile:
    path: str
    size_bytes: int
    names: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class RouterContext:
    task: TaskFacts
    criteria: list[Criterion]
    scope_root: str
    machine: MachineFacts
    brief: BriefFacts | None = None
    history: list[HistoryEntry] = field(default_factory=list)
    workspace: list[WorkspaceFile] = field(default_factory=list)


def clip(value: str, limit: int) -> str:
    text = value.strip()

    if len(text) <= limit:
        return text

    return f"{text[:limit].rstrip()} [...truncated]"


def bullets(values: list[str]) -> list[str]:
    return [f"- {clip(value, MAX_NOTE_CHARS)}" for value in values if value.strip()]


def render_criterion(criterion: Criterion) -> str:
    statement = clip(criterion.statement, MAX_STATEMENT_CHARS)

    return f"- {criterion.criterion_id} [{criterion.status}/{criterion.check_kind}] {statement}"


def render_history(entry: HistoryEntry) -> str:
    line = f"- {clip(entry.title, MAX_NOTE_CHARS)} [{entry.state}]"

    if entry.note:
        return f"{line} - {clip(entry.note, MAX_NOTE_CHARS)}"

    return line


def render_names(names: list[str]) -> str:
    if not names:
        return ""

    shown = names[:MAX_NAMES_PER_FILE]
    remaining = len(names) - len(shown)
    listed = ", ".join(shown)

    return f" defines {listed} and {remaining} more" if remaining > 0 else f" defines {listed}"


def render_workspace_file(entry: WorkspaceFile) -> str:
    path = clip(entry.path, MAX_NOTE_CHARS)

    return f"- {path} ({entry.size_bytes} bytes){render_names(entry.names)}"


def render_workspace(files: list[WorkspaceFile], listed: int) -> str:
    if not files:
        return "WORKSPACE FILES\nthe working directory is empty"

    shown = files[:listed]

    if not shown:
        return f"WORKSPACE FILES (0 of {len(files)})\nnot listed, to stay inside the budget"

    heading = f"WORKSPACE FILES ({len(shown)} of {len(files)})"

    return "\n".join([heading, *[render_workspace_file(entry) for entry in shown]])


def render_capability(capability: Capability) -> str:
    backend = capability.backend if capability.backend else NO_BACKEND

    return f"- {capability.name}: {backend} ({capability.strength})"


def render_machine(machine: MachineFacts) -> list[str]:
    lines = [
        f"- os: {machine.os_version}",
        f"- cpu cores: {machine.cpu_cores}",
        f"- ram: {machine.ram_gb:g} GB",
        f"- free disk: {machine.free_disk_gb:g} GB",
    ]
    lines.extend(render_capability(capability) for capability in machine.capabilities)

    return lines


def sections(context: RouterContext, history_entries: int, workspace_files: int) -> list[str]:
    task = context.task

    facts = [
        f"title: {clip(task.title, MAX_NOTE_CHARS)}",
        f"kind: {task.kind}",
        f"state: {task.state}",
    ]

    if task.description.strip():
        facts.append(f"description: {clip(task.description, MAX_DESCRIPTION_CHARS)}")

    blocks = ["\n".join(["TASK", *facts])]

    if context.criteria:
        rendered = [render_criterion(criterion) for criterion in context.criteria]
        blocks.append("\n".join(["ACCEPTANCE CRITERIA", *rendered]))
    else:
        blocks.append("ACCEPTANCE CRITERIA\nnone recorded for this task")

    blocks.append(f"WORKING DIRECTORY\n{context.scope_root}")
    blocks.append(render_workspace(context.workspace, workspace_files))
    blocks.append("\n".join(["MACHINE", *render_machine(context.machine)]))

    if context.brief is not None:
        brief = context.brief
        lines = [
            f"type: {brief.project_type}",
            f"goal: {clip(brief.interpreted_goal, MAX_NOTE_CHARS)}",
        ]

        if brief.known_constraints:
            lines.extend(["constraints:", *bullets(brief.known_constraints)])

        if brief.out_of_scope:
            lines.extend(["out of scope:", *bullets(brief.out_of_scope)])

        if brief.assumptions:
            lines.extend(["assumptions:", *bullets(brief.assumptions)])

        blocks.append("\n".join(["PROJECT", *lines]))

    if context.history and history_entries > 0:
        shown = context.history[:history_entries]
        rendered = [render_history(entry) for entry in shown]
        heading = f"RECENT TASKS ({len(shown)} of {len(context.history)})"
        blocks.append("\n".join([heading, *rendered]))

    return blocks


def render(context: RouterContext, budget: int = MAX_CONTEXT_CHARS) -> str:
    history_entries, workspace_files = SHRINK_STEPS[0]
    rendered = "\n\n".join(sections(context, history_entries, workspace_files))

    for history_entries, workspace_files in SHRINK_STEPS[1:]:
        if len(rendered) <= budget:
            return rendered

        rendered = "\n\n".join(sections(context, history_entries, workspace_files))

    return rendered if len(rendered) <= budget else clip(rendered, budget)


def criterion_ids(context: RouterContext) -> list[str]:
    return [criterion.criterion_id for criterion in context.criteria]
