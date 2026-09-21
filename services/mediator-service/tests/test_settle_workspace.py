from __future__ import annotations

from typing import Any

from mediator_service.dispatch import FileWrite, Result
from mediator_service.settle import VERIFIED, resolved, verdict
from mediator_service.upstream import Criterion

SCOPE_ROOT = "C:\\scope"
DIGEST = "a" * 64


def criterion(check_spec: dict[str, Any]) -> Criterion:
    return Criterion(
        id="c-1",
        task_id="t-1",
        statement="the helper module exists",
        check_kind="deterministic",
        check_spec=check_spec,
        weight=1,
        status="unverified",
    )


def wrote(path: str) -> Result:
    return Result(
        step_id="s-1",
        state="succeeded",
        exit_code=0,
        terminated_by=None,
        error_message=None,
        files_written=(FileWrite(path=path, sha256=DIGEST, size_bytes=12),),
        files_deleted=(),
        ports_opened=(),
        started_at="2026-01-01T00:00:00+00:00",
        ended_at="2026-01-01T00:00:01+00:00",
    )


def test_the_workspace_placeholder_resolves_to_the_scope_root() -> None:
    assert resolved("<workspace>/db_helper.py", SCOPE_ROOT) == "c:/scope/db_helper.py"


def test_the_placeholder_resolves_whatever_its_case_and_separator() -> None:
    assert resolved("<WORKSPACE>\\src\\api.py", SCOPE_ROOT) == "c:/scope/src/api.py"


def test_the_placeholder_on_its_own_is_the_scope_root() -> None:
    assert resolved("<workspace>", SCOPE_ROOT) == "c:/scope"


def test_a_placeholder_followed_by_a_dot_segment_still_resolves() -> None:
    assert resolved("<workspace>/./main.py", SCOPE_ROOT) == "c:/scope/main.py"


def test_a_placeholder_that_is_not_at_the_start_is_left_alone() -> None:
    assert resolved("notes/<workspace>.md", SCOPE_ROOT) == "c:/scope/notes/<workspace>.md"


def test_a_file_the_run_wrote_settles_a_placeholder_criterion() -> None:
    settled = verdict(
        criterion({"type": "file_exists", "path": "<workspace>/db_helper.py"}),
        (wrote("C:\\scope\\db_helper.py"),),
        SCOPE_ROOT,
    )

    assert settled.status == VERIFIED


def test_a_digest_settles_a_placeholder_criterion() -> None:
    settled = verdict(
        criterion(
            {"type": "file_hash", "path": "<workspace>/db_helper.py", "expected_sha256": DIGEST}
        ),
        (wrote("C:\\scope\\db_helper.py"),),
        SCOPE_ROOT,
    )

    assert settled.status == VERIFIED
