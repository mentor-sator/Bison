from __future__ import annotations

from dataclasses import replace

import pytest

from mediator_service.checks import FileExists, FileHash
from mediator_service.context import BriefFacts
from mediator_service.decomposition import brief_text
from mediator_service.discipline import TreeRejectedError, assert_disciplined, review
from mediator_service.settle import LEFT_IGNORED, VERIFIED, verdict, verdicts
from tests.test_discipline_reserved import checked, tree
from tests.test_settle import SCOPE_ROOT, criterion, file_exists, file_hash, result, wrote

EMPTY_FILE_DIGEST = "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855"
SUPPLIED_DIGEST = "9f86d081884c7d659a2feaa0c55ad015a3bf4f1b2b0b822cd15d6c15b0f00a08"


def test_a_digest_the_brief_never_supplied_is_rejected() -> None:
    findings = review(tree(checked(FileHash(path="db.py", expected_sha256=EMPTY_FILE_DIGEST))))

    assert len(findings) == 1
    assert "expects the digest e3b0c44298fc..." in findings[0]
    assert "which nothing in the brief supplies" in findings[0]


def test_an_invented_digest_stops_the_tree() -> None:
    with pytest.raises(TreeRejectedError):
        assert_disciplined(
            tree(checked(FileHash(path="db.py", expected_sha256=EMPTY_FILE_DIGEST))), "no hashes"
        )


def test_a_digest_the_brief_supplies_is_accepted() -> None:
    spec = FileHash(path="installer.exe", expected_sha256=SUPPLIED_DIGEST)
    supplied = f"The installer must match SHA-256 {SUPPLIED_DIGEST.upper()}"

    assert review(tree(checked(spec)), supplied) == ()


def test_a_file_that_merely_exists_needs_no_digest() -> None:
    assert review(tree(checked(FileExists(path="db.py")))) == ()


def test_every_part_of_the_brief_can_supply_a_digest() -> None:
    brief = BriefFacts(
        interpreted_goal="goal",
        project_type="cli",
        summary="summary",
        known_constraints=["constraint"],
        assumptions=["assumption"],
        out_of_scope=["excluded"],
        seeded_success_criteria=[f"installer hashes to {SUPPLIED_DIGEST}"],
    )
    text = brief_text(brief)

    assert SUPPLIED_DIGEST in text
    for part in ("goal", "summary", "constraint", "assumption", "excluded"):
        assert part in text


def test_an_ignored_criterion_is_never_settled_by_a_run() -> None:
    ignored = replace(criterion(file_hash("db.py", EMPTY_FILE_DIGEST)), status="ignored")
    settled = verdict(ignored, (result((wrote("C:\\scope\\db.py", "c" * 64),)),), SCOPE_ROOT)

    assert settled.status is None
    assert settled.detail == LEFT_IGNORED


def test_an_ignored_criterion_stays_out_even_when_the_run_would_verify_it() -> None:
    ignored = replace(criterion(file_exists("db.py")), status="ignored")
    settled = verdict(ignored, (result((wrote("C:\\scope\\db.py"),)),), SCOPE_ROOT)

    assert settled.status is None


def test_only_the_ignored_criterion_is_left_alone() -> None:
    kept = criterion(file_exists("db.py"), criterion_id="c-kept")
    ignored = replace(criterion(file_exists("db.py"), criterion_id="c-ignored"), status="ignored")

    settled = verdicts((kept, ignored), (result((wrote("C:\\scope\\db.py"),)),), SCOPE_ROOT)

    assert [(entry.criterion_id, entry.status) for entry in settled] == [
        ("c-kept", VERIFIED),
        ("c-ignored", None),
    ]
