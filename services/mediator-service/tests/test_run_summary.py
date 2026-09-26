from __future__ import annotations

from mediator_service.events import run_finished
from mediator_service.loop import run_summary
from tests.test_loop import failed, gated_body, plan_for, run_loop, step_body, task

RESET = "set a task back to ready to run it again"


def test_a_finished_run_carries_a_null_detail_by_default() -> None:
    assert run_finished(1, 0, 1, 100.0)["detail"] is None


def test_a_finished_run_carries_the_detail_it_is_given() -> None:
    assert run_finished(0, 0, 2, 50.0, "nothing to run")["detail"] == "nothing to run"


def test_the_settled_summary_lists_states_in_a_fixed_order() -> None:
    summary = run_summary(0, ["ignored", "done", "skipped", "done"], 0)

    assert summary == (
        f"nothing to run: every task is already settled (2 done, 1 skipped, 1 ignored); {RESET}"
    )


async def test_a_run_with_every_task_settled_says_so_instead_of_reporting_nothing() -> None:
    ran = await run_loop((task("t-1", 0, state="done"), task("t-2", 1, state="failed")))
    finished = ran.one("run_finished")

    assert ran.started() == []
    assert (finished["tasks_completed"], finished["tasks_failed"]) == (0, 0)
    assert finished["detail"] == (
        f"nothing to run: every task is already settled (1 done, 1 failed); {RESET}"
    )


async def test_a_run_where_everything_waits_on_an_unfinished_task_names_the_wait() -> None:
    ran = await run_loop(
        (
            task("t-1", 0, state="skipped"),
            task("t-2", 1, depends_on=("t-1",)),
            task("t-3", 2, depends_on=("t-1",)),
        )
    )

    assert ran.started() == []
    assert ran.one("run_finished")["detail"] == (
        "nothing to run: 2 tasks wait on a task that did not finish"
    )


async def test_a_run_that_leaves_a_dependent_unrun_says_why() -> None:
    ran = await run_loop(
        (task("t-1", 0), task("t-2", 1, depends_on=("t-1",))),
        plans={"t-1": plan_for("t-1", step_body("s-1"))},
        scripts={"s-1": [failed("s-1")]},
    )

    assert ran.one("run_finished")["detail"] == (
        "1 task waits on a task that did not finish, so it did not run"
    )


async def test_a_run_that_worked_everything_carries_no_detail() -> None:
    ran = await run_loop((task("t-1", 0), task("t-2", 1)))

    assert ran.one("run_finished")["detail"] is None


async def test_a_parked_run_carries_no_detail() -> None:
    ran = await run_loop(
        (task("t-1", 0), task("t-2", 1, depends_on=("t-1",))),
        plans={"t-1": plan_for("t-1", gated_body("s-1"))},
    )

    assert ran.loop.awaiting_task_id == "t-1"
    assert ran.one("run_finished")["detail"] is None
