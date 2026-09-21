from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from inspector_service import SERVICE_NAME
from inspector_service.config import settings
from inspector_service.inspection import Outcome, inspect_task
from inspector_service.upstream import (
    ProjectClient,
    ProjectNotFoundError,
    TaskNotFoundError,
    UpstreamError,
)

WORKSPACE_DIRNAME = "workspace"


class Health(BaseModel):
    service: str
    status: Literal["ok"]
    project_service: str


class EvidenceRead(BaseModel):
    kind: str
    excerpt: str | None


class ResultRead(BaseModel):
    criterion_id: str
    task_id: str
    statement: str
    check_kind: str
    verdict: str
    reasoning: str
    evidence: list[EvidenceRead]
    status_before: str
    status_after: str


class ReportRead(BaseModel):
    project_id: str
    workspace: str
    inspected_at: str
    verified: int
    failed: int
    inconclusive: int
    changed: int
    results: list[ResultRead]


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    resolved = settings()

    app.state.projects = ProjectClient(
        resolved.project_service_url,
        resolved.upstream_timeout_seconds,
        resolved.connect_timeout_seconds,
    )

    yield

    await app.state.projects.close()


app = FastAPI(title=SERVICE_NAME, lifespan=lifespan)


@app.exception_handler(ProjectNotFoundError)
async def handle_project_not_found(request: Request, exc: Exception) -> JSONResponse:
    return JSONResponse(status_code=404, content={"error": "project_not_found", "detail": str(exc)})


@app.exception_handler(TaskNotFoundError)
async def handle_task_not_found(request: Request, exc: Exception) -> JSONResponse:
    return JSONResponse(status_code=404, content={"error": "task_not_found", "detail": str(exc)})


@app.exception_handler(UpstreamError)
async def handle_upstream(request: Request, exc: Exception) -> JSONResponse:
    return JSONResponse(
        status_code=503, content={"error": "upstream_unavailable", "detail": str(exc)}
    )


@app.get("/health")
async def health() -> Health:
    return Health(
        service=SERVICE_NAME,
        status="ok",
        project_service=settings().project_service_url,
    )


def workspace_of(project_id: str) -> Path:
    return settings().workspace_root / project_id / WORKSPACE_DIRNAME


def result_read(outcome: Outcome) -> ResultRead:
    evidence = (
        [EvidenceRead(kind=outcome.evidence_kind, excerpt=outcome.excerpt)]
        if outcome.evidence_kind is not None
        else []
    )

    return ResultRead(
        criterion_id=outcome.criterion_id,
        task_id=outcome.task_id,
        statement=outcome.statement,
        check_kind=outcome.check_kind,
        verdict=outcome.verdict,
        reasoning=outcome.reason,
        evidence=evidence,
        status_before=outcome.status_before,
        status_after=outcome.status_after,
    )


def report(project_id: str, workspace: Path, outcomes: list[Outcome]) -> ReportRead:
    return ReportRead(
        project_id=project_id,
        workspace=str(workspace),
        inspected_at=datetime.now(UTC).isoformat(),
        verified=sum(1 for outcome in outcomes if outcome.verdict == "verified"),
        failed=sum(1 for outcome in outcomes if outcome.verdict == "failed"),
        inconclusive=sum(1 for outcome in outcomes if outcome.verdict == "inconclusive"),
        changed=sum(1 for outcome in outcomes if outcome.changed),
        results=[result_read(outcome) for outcome in outcomes],
    )


@app.post("/projects/{project_id}/tasks/{task_id}/inspect")
async def inspect_one(project_id: str, task_id: str) -> ReportRead:
    projects: ProjectClient = app.state.projects
    tasks = await projects.tasks(project_id)

    if all(task.id != task_id for task in tasks):
        raise TaskNotFoundError(task_id)

    workspace = workspace_of(project_id)
    outcomes = await inspect_task(projects, task_id, workspace, settings().probe_seconds)

    return report(project_id, workspace, outcomes)


@app.post("/projects/{project_id}/inspect")
async def inspect_all(project_id: str) -> ReportRead:
    projects: ProjectClient = app.state.projects
    workspace = workspace_of(project_id)
    probe_seconds = settings().probe_seconds
    outcomes: list[Outcome] = []

    for task in await projects.tasks(project_id):
        outcomes.extend(await inspect_task(projects, task.id, workspace, probe_seconds))

    return report(project_id, workspace, outcomes)
