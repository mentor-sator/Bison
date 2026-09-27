from __future__ import annotations

from typing import Any

from mediator_service.dispatch import FileWrite
from mediator_service.execution import COMPLETED, FAILED, refuted_by, unmet_reason
from mediator_service.inspection import to_inspection
from tests.test_execution import (
    DIGEST,
    TASK_ID,
    criterion,
    run_pass,
    step_body,
    succeeded,
)
from tests.test_execution_inspect import REPORT, inspected_pass

TABLE_UNMET = "criterion 'tasks.db holds a tasks table' failed: tasks.db does not exist"
OTHER_DIGEST = "b" * 64


def report_with(*verdicts: str) -> dict[str, Any]:
    results = [
        {
            **REPORT["results"][0],
            "criterion_id": f"c-{index + 1}",
            "statement": f"criterion {index + 1}",
            "verdict": verdict,
            "reasoning": f"reason {index + 1}",
        }
        for index, verdict in enumerate(verdicts)
    ]

    return {**REPORT, "results": results}


async def test_a_criterion_the_inspector_refutes_fails_the_task() -> None:
    ran = await inspected_pass()

    assert ran.run.state == FAILED
    assert ran.run.reason == TABLE_UNMET
    assert ran.project.task_moves[-1] == (TASK_ID, "failed", TABLE_UNMET)


async def test_the_finish_event_carries_the_refuted_criterion() -> None:
    ran = await inspected_pass()
    finished = ran.one("task_finished")

    assert finished["state"] == FAILED
    assert finished["reason"] == TABLE_UNMET


async def test_a_task_whose_criteria_all_hold_is_done() -> None:
    ran = await inspected_pass(body=report_with("verified", "verified"))

    assert ran.run.state == COMPLETED
    assert ran.task_states() == ["in_progress", "verifying", "done"]


async def test_an_inconclusive_verdict_does_not_fail_the_task() -> None:
    ran = await inspected_pass(body=report_with("verified", "inconclusive"))

    assert ran.run.state == COMPLETED


async def test_a_run_disproving_a_criterion_fails_the_task_before_inspection() -> None:
    check = {"type": "file_hash", "path": "schema.sql", "expected_sha256": OTHER_DIGEST}
    ran = await run_pass(
        steps=(step_body(),),
        scripts={"s-1": [succeeded(files=(FileWrite("C:\\scope\\schema.sql", DIGEST, 12),))]},
        criteria=(criterion(check_spec=check),),
    )

    assert ran.run.state == FAILED
    assert ran.run.reason is not None
    assert ran.run.reason.startswith("criterion 'the schema file exists' failed: the run wrote")
    assert [state for _, state, _ in ran.project.task_moves][-1] == "failed"


async def test_a_run_proving_its_criterion_still_completes() -> None:
    ran = await run_pass(
        steps=(step_body(),),
        scripts={"s-1": [succeeded(files=(FileWrite("C:\\scope\\schema.sql", DIGEST, 12),))]},
        criteria=(criterion(),),
    )

    assert ran.run.state == COMPLETED


def test_several_unmet_criteria_name_the_first_and_count_the_rest() -> None:
    assert unmet_reason(["first", "second", "third"]) == "first (and 2 more)"


def test_no_unmet_criteria_give_no_reason() -> None:
    assert unmet_reason([]) is None


def test_no_inspection_refutes_nothing() -> None:
    assert refuted_by(None) is None


def test_every_refuted_verdict_is_counted() -> None:
    inspection = to_inspection(TASK_ID, report_with("failed", "verified", "failed"))

    assert refuted_by(inspection) == "criterion 'criterion 1' failed: reason 1 (and 1 more)"
