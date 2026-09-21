from __future__ import annotations

import asyncio
from dataclasses import dataclass
from pathlib import Path
from typing import Final, Protocol

from inspector_service.checks import CheckSpecError, parse
from inspector_service.runners import EvidenceKind, Finding, Verdict, inconclusive, run
from inspector_service.upstream import Criterion

DETERMINISTIC: Final[str] = "deterministic"
IGNORED: Final[str] = "ignored"
SETTLING: Final[frozenset[str]] = frozenset({"verified", "failed"})


class Projects(Protocol):
    async def criteria(self, task_id: str) -> list[Criterion]: ...

    async def settle(self, criterion_id: str, status: str, reason: str) -> None: ...


@dataclass(frozen=True)
class Outcome:
    criterion_id: str
    task_id: str
    statement: str
    check_kind: str
    verdict: Verdict
    reason: str
    evidence_kind: EvidenceKind | None
    excerpt: str | None
    status_before: str
    status_after: str

    @property
    def changed(self) -> bool:
        return self.status_before != self.status_after


def finding_for(criterion: Criterion, workspace: Path, probe_seconds: float) -> Finding:
    if criterion.status == IGNORED:
        return inconclusive("the user set this criterion aside, so it is not inspected")

    if criterion.check_kind != DETERMINISTIC:
        return inconclusive(
            "this criterion is judged from evidence by the inspector model, which is not built yet"
        )

    try:
        spec = parse(criterion.check_spec)
    except CheckSpecError as error:
        return inconclusive(f"the stored check could not be read: {error.detail}")

    return run(spec, workspace, probe_seconds)


async def inspect_criterion(
    projects: Projects, criterion: Criterion, workspace: Path, probe_seconds: float
) -> Outcome:
    finding = await asyncio.to_thread(finding_for, criterion, workspace, probe_seconds)
    after = criterion.status

    if finding.verdict in SETTLING and finding.verdict != criterion.status:
        await projects.settle(criterion.id, finding.verdict, finding.reason)
        after = finding.verdict

    return Outcome(
        criterion_id=criterion.id,
        task_id=criterion.task_id,
        statement=criterion.statement,
        check_kind=criterion.check_kind,
        verdict=finding.verdict,
        reason=finding.reason,
        evidence_kind=finding.evidence_kind,
        excerpt=finding.excerpt,
        status_before=criterion.status,
        status_after=after,
    )


async def inspect_task(
    projects: Projects, task_id: str, workspace: Path, probe_seconds: float
) -> list[Outcome]:
    return [
        await inspect_criterion(projects, criterion, workspace, probe_seconds)
        for criterion in await projects.criteria(task_id)
    ]
