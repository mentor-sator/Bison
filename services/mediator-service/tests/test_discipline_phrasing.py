from __future__ import annotations

import pytest

from mediator_service.checks import CheckSpec, FileExists, SqlResult
from mediator_service.discipline import SUGGESTED_EXPECT, SUGGESTED_QUERY, review
from mediator_service.tree import DraftCriterion, DraftTask, TreeDraft


def checked(spec: CheckSpec, statement: str = "The result is observable") -> DraftCriterion:
    return DraftCriterion(
        statement=statement, check_kind="deterministic", check_spec=spec, weight=1
    )


def leaf(
    ref: str,
    *criteria: DraftCriterion,
    depends_on: tuple[str, ...] = (),
    position: int = 0,
) -> DraftTask:
    return DraftTask(
        ref=ref,
        parent_ref=None,
        title=f"Create {ref}",
        description="",
        kind="code",
        assigned_role="engine",
        depends_on=depends_on,
        criteria=criteria,
        position=position,
    )


def tree(*tasks: DraftTask) -> TreeDraft:
    return TreeDraft(approach_summary="Build the task tracker", tasks=tasks)


def sql(expect: str, query: str = SUGGESTED_QUERY) -> SqlResult:
    return SqlResult(connection_ref="tasks.db", query=query, expect=expect)


@pytest.mark.parametrize(
    "statement",
    [
        "The file db.py exists in the working directory.",
        "db.py exists in the working folder",
        "report.txt appears in the Working Directory",
        "seed.py sits at the root of the working tree",
    ],
)
def test_a_path_phrase_is_not_mistaken_for_a_summary(statement: str) -> None:
    assert review(tree(leaf("db", checked(FileExists(path="db.py"), statement)))) == ()


@pytest.mark.parametrize(
    "statement",
    [
        "The tracker is working",
        "The report script is working in the working directory",
    ],
)
def test_working_as_a_summary_is_still_refused(statement: str) -> None:
    findings = review(tree(leaf("db", checked(FileExists(path="db.py"), statement))))

    assert len(findings) == 1
    assert "says working, which is a summary" in findings[0]


def test_the_tree_the_model_wrote_passes_once_its_tasks_are_siblings() -> None:
    draft = tree(
        leaf(
            "db_init",
            checked(FileExists(path="db.py"), "The file db.py exists in the working directory."),
        ),
        leaf(
            "seed_script",
            checked(
                FileExists(path="seed.py"), "The file seed.py exists in the working directory."
            ),
            depends_on=("db_init",),
            position=1,
        ),
        leaf(
            "report_script",
            checked(
                FileExists(path="report.py"),
                "The file report.py exists in the working directory.",
            ),
            depends_on=("db_init",),
            position=2,
        ),
    )

    assert review(draft) == ()


@pytest.mark.parametrize("expect", ["3", "0", "tasks", "Buy milk", "2026-09-22"])
def test_a_literal_expect_is_accepted(expect: str) -> None:
    assert review(tree(leaf("seed", checked(sql(expect))))) == ()


@pytest.mark.parametrize(
    "expect",
    [
        "row_count > 0",
        ">= 1",
        "= 3",
        "!= 0",
        "rows exist",
        "at least 1",
        "more than 2",
        "non-empty",
        "not empty",
        "any",
        "RowCount 3",
    ],
)
def test_an_expect_that_is_not_a_literal_is_sent_back(expect: str) -> None:
    findings = review(tree(leaf("seed", checked(sql(expect)))))

    assert len(findings) == 1
    assert f"expects {expect!r}" in findings[0]


def test_the_finding_shows_the_value_to_select_instead() -> None:
    findings = review(tree(leaf("seed", checked(sql("row_count > 0")))))

    assert f"such as {SUGGESTED_QUERY} with expect {SUGGESTED_EXPECT}" in findings[0]
    assert "equals expect exactly" in findings[0]


def test_the_sql_a_criterion_quotes_is_not_read_as_two_claims() -> None:
    statement = (
        "In tasks.db, SELECT name FROM sqlite_master WHERE type='table' "
        "AND name='tasks' returns tasks"
    )
    spec = SqlResult(
        connection_ref="tasks.db",
        query="SELECT name FROM sqlite_master WHERE type='table' AND name='tasks'",
        expect="tasks",
    )

    assert review(tree(leaf("table", checked(spec, statement)))) == ()


def test_a_claim_joined_after_the_query_is_still_refused() -> None:
    statement = "In tasks.db, SELECT COUNT(*) FROM tasks returns 3 and report.txt exists"
    findings = review(tree(leaf("seed", checked(sql("3"), statement))))

    assert len(findings) == 1
    assert "joins two claims with and" in findings[0]


def test_a_query_is_only_ignored_where_the_check_is_sql() -> None:
    statement = "The report lists the tasks and the totals"
    findings = review(tree(leaf("report", checked(FileExists(path="report.txt"), statement))))

    assert len(findings) == 1
    assert "joins two claims with and" in findings[0]
