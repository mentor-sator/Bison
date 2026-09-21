from __future__ import annotations

import re
from typing import Final
from urllib.parse import urlsplit

from mediator_service.checks import CheckSpec, FileExists, FileHash, HttpStatus, PortOpen, SqlResult
from mediator_service.tree import DraftCriterion, DraftTask, TreeDraft, leaf_refs

REAL_WORLD_KIND: Final[str] = "real_world"
MAX_FINDINGS: Final[int] = 12

RESERVED_PORT_LOW: Final[int] = 8000
RESERVED_PORT_HIGH: Final[int] = 9000
SUGGESTED_PORT: Final[int] = 9101
DEFAULT_PORTS: Final[dict[str, int]] = {"http": 80, "https": 443}

ENVIRONMENT_SEGMENTS: Final[frozenset[str]] = frozenset(
    {"venv", ".venv", "virtualenv", "site-packages"}
)

MECHANISABLE: Final[frozenset[str]] = frozenset(
    {
        "file exists",
        "exists at",
        "exists in",
        "directory",
        "folder",
        "table",
        "column",
        "row count",
        "rows",
        "select",
        "query",
        "database",
        "schema",
        "migration",
        "port",
        "listening",
        "endpoint",
        "status code",
        "responds",
        "environment variable",
        "installed",
        "package",
        "dependency",
        "commit",
        "branch",
    }
)

JUDGEMENT: Final[frozenset[str]] = frozenset(
    {
        "matches the reference",
        "reference image",
        "reference screenshot",
        "screenshot",
        "mockup",
        "visually",
        "visual",
        "looks",
        "appears",
        "appearance",
        "layout",
        "design",
        "readable",
        "legible",
        "aligned",
        "alignment",
        "colour",
        "color",
        "font",
        "spacing",
        "styling",
        "user confirms",
        "user reports",
        "by hand",
        "in person",
        "physically",
        "phone",
        "delivered",
        "signed",
        "printed",
        "posted",
        "mailed",
        "tone",
        "wording",
        "sounds",
        "subjective",
        "judgement",
        "judgment",
    }
)

VAGUE: Final[frozenset[str]] = frozenset(
    {
        "set up",
        "works",
        "working",
        "functional",
        "functions",
        "complete",
        "is done",
        "finished",
        "ready",
        "properly",
        "correctly",
        "as expected",
        "successfully",
        "no issues",
        "no problems",
        "everything",
        "all good",
        "is fine",
        "is good",
        "acceptable",
        "appropriate",
        "reasonable",
    }
)

UNEXPRESSIBLE: Final[frozenset[str]] = frozenset(
    {
        "exit code",
        "exits with",
        "exits cleanly",
        "returns 0",
        "exit status",
    }
)

COMPOUND: Final[frozenset[str]] = frozenset({"and", "then", "as well as", "along with"})

EXTENSION: Final[re.Pattern[str]] = re.compile(
    r"\S+\.(py|ts|tsx|js|json|toml|yaml|yml|md|sql|csv|log|exe|zip|db|sqlite|cfg|ini|env)\b"
)

ADDRESS: Final[re.Pattern[str]] = re.compile(r"https?://|:\d{2,5}\b|[a-z]:[/\\]")


class TreeRejectedError(RuntimeError):
    def __init__(self, findings: tuple[str, ...]) -> None:
        super().__init__(" ".join(findings))
        self.findings = findings


def normalise(statement: str) -> str:
    cleaned = re.sub(r"[^a-z0-9./:\\_-]+", " ", statement.lower())

    return f" {cleaned.strip()} "


def first_match(text: str, phrases: frozenset[str]) -> str | None:
    for phrase in sorted(phrases, key=len, reverse=True):
        if f" {phrase} " in text:
            return phrase

    return None


def looks_mechanisable(text: str) -> str | None:
    phrase = first_match(text, MECHANISABLE)

    if phrase is not None:
        return phrase

    extension = EXTENSION.search(text)

    if extension is not None:
        return extension.group(0)

    address = ADDRESS.search(text)

    return address.group(0) if address is not None else None


def checked_port(spec: CheckSpec) -> int | None:
    if isinstance(spec, PortOpen):
        return spec.port

    if not isinstance(spec, HttpStatus):
        return None

    parts = urlsplit(spec.url)

    try:
        port = parts.port
    except ValueError:
        return None

    return port if port is not None else DEFAULT_PORTS.get(parts.scheme)


def checked_path(spec: CheckSpec) -> str | None:
    if isinstance(spec, FileExists | FileHash):
        return spec.path

    if isinstance(spec, SqlResult):
        return spec.connection_ref

    return None


def inside_environment(path: str) -> bool:
    return any(segment in ENVIRONMENT_SEGMENTS for segment in re.split(r"[\\/]+", path.lower()))


def spec_findings(criterion: DraftCriterion, label: str) -> list[str]:
    spec = criterion.check_spec

    if spec is None:
        return []

    collected: list[str] = []
    port = checked_port(spec)

    if port is not None and RESERVED_PORT_LOW <= port <= RESERVED_PORT_HIGH:
        collected.append(
            f"{label} checks port {port}, which belongs to BISON's own services, so no plan may "
            f"bind it; check a port above {RESERVED_PORT_HIGH}, such as {SUGGESTED_PORT}"
        )

    path = checked_path(spec)

    if path is not None and inside_environment(path):
        collected.append(
            f"{label} checks {path}, inside a virtual environment; BISON keeps each task's "
            "environment outside the working directory, so check a result the task produces "
            "there instead"
        )

    return collected


def criterion_findings(task: DraftTask, criterion: DraftCriterion, index: int) -> list[str]:
    label = f"task {task.ref} criterion {index}"
    text = normalise(criterion.statement)
    collected: list[str] = []

    unexpressible = first_match(text, UNEXPRESSIBLE)

    if unexpressible is not None:
        collected.append(
            f"{label} turns on {unexpressible}, which BISON cannot check when the tree is "
            "built; state the observable result instead"
        )

    vague = first_match(text, VAGUE)

    if vague is not None:
        collected.append(
            f"{label} says {vague}, which is a summary rather than a criterion; state the one "
            "observable fact that would settle it"
        )

    compound = first_match(text, COMPOUND)

    if compound is not None:
        collected.append(
            f"{label} joins two claims with {compound}; state one thing per criterion and split "
            "this into separate criteria"
        )

    if criterion.check_kind == "inspected" and first_match(text, JUDGEMENT) is None:
        signal = looks_mechanisable(text)

        if signal is not None:
            collected.append(
                f"{label} is inspected but mentions {signal}, which code could settle; make it "
                "deterministic with a check_spec"
            )

    collected.extend(spec_findings(criterion, label))

    return collected


def duplicate_findings(task: DraftTask) -> list[str]:
    seen: set[str] = set()
    collected: list[str] = []

    for criterion in task.criteria:
        text = normalise(criterion.statement)

        if text in seen:
            collected.append(
                f"task {task.ref} states the same criterion twice, which would count its weight "
                "against progress twice"
            )
            break

        seen.add(text)

    return collected


def leaf_findings(task: DraftTask) -> list[str]:
    if not task.criteria:
        return [
            f"task {task.ref} is a leaf with no acceptance criteria, so nothing could ever mark "
            "it done"
        ]

    if task.kind == REAL_WORLD_KIND:
        return []

    if any(criterion.check_kind == "deterministic" for criterion in task.criteria):
        return []

    return [
        f"task {task.ref} is settled entirely by judgement; give it at least one deterministic "
        "criterion so its progress rests on evidence"
    ]


def parent_findings(task: DraftTask) -> list[str]:
    if not task.criteria:
        return []

    return [
        f"task {task.ref} has children, so its criteria belong on the leaves that actually "
        "produce the result"
    ]


def review(draft: TreeDraft) -> tuple[str, ...]:
    leaves = leaf_refs(draft)
    collected: list[str] = []

    for task in draft.tasks:
        if task.ref in leaves:
            collected.extend(leaf_findings(task))
        else:
            collected.extend(parent_findings(task))

        collected.extend(duplicate_findings(task))

        for index, criterion in enumerate(task.criteria):
            collected.extend(criterion_findings(task, criterion, index))

    return tuple(collected[:MAX_FINDINGS])


def assert_disciplined(draft: TreeDraft) -> None:
    findings = review(draft)

    if findings:
        raise TreeRejectedError(findings)
