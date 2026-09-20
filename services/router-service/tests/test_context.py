from __future__ import annotations

from router_service.context import (
    BriefFacts,
    Capability,
    Criterion,
    HistoryEntry,
    MachineFacts,
    RouterContext,
    TaskFacts,
    WorkspaceFile,
    criterion_ids,
    render,
)

SCOPE = r"C:\Users\dev\bison\workspace"

MACHINE = MachineFacts(
    os_version="Windows 11 Pro 26100",
    cpu_cores=8,
    ram_gb=16.0,
    free_disk_gb=214.5,
    capabilities=[
        Capability(name="sandbox", backend="job_object", strength="medium"),
        Capability(name="database", backend="sqlite", strength="full"),
        Capability(name="secrets", backend=None, strength="unavailable"),
    ],
)


WORKSPACE = [
    WorkspaceFile(
        path="db_helper.py",
        size_bytes=1242,
        names=["create_task", "select_all_tasks"],
    ),
    WorkspaceFile(path="README.md", size_bytes=88),
]


def criterion(index: int) -> Criterion:
    return Criterion(
        criterion_id=f"c{index}",
        statement=f"Table number {index} exists in the database",
        check_kind="deterministic",
        status="unverified",
    )


def context(**overrides: object) -> RouterContext:
    base: dict[str, object] = {
        "task": TaskFacts(
            title="Provision the project database",
            description="Create the schema and seed reference data",
            kind="code",
            state="ready",
        ),
        "criteria": [criterion(1), criterion(2)],
        "scope_root": SCOPE,
        "machine": MACHINE,
        "brief": BriefFacts(
            interpreted_goal="Match every invoice to a payment",
            project_type="code",
            known_constraints=["runs offline"],
            out_of_scope=["tax filing"],
            assumptions=["amounts are in RWF"],
        ),
        "history": [HistoryEntry(title=f"Earlier task {n}", state="done") for n in range(12)],
        "workspace": list(WORKSPACE),
    }
    base.update(overrides)

    return RouterContext(**base)  # type: ignore[arg-type]


def test_renders_every_section() -> None:
    rendered = render(context())

    assert "TASK" in rendered
    assert "ACCEPTANCE CRITERIA" in rendered
    assert "WORKING DIRECTORY" in rendered
    assert "WORKSPACE FILES" in rendered
    assert "MACHINE" in rendered
    assert "PROJECT" in rendered
    assert "RECENT TASKS" in rendered


def test_the_machine_is_described_in_full() -> None:
    rendered = render(context())

    assert "- os: Windows 11 Pro 26100" in rendered
    assert "- cpu cores: 8" in rendered
    assert "- ram: 16 GB" in rendered
    assert "- free disk: 214.5 GB" in rendered


def test_capabilities_carry_their_backend_and_strength() -> None:
    rendered = render(context())

    assert "- sandbox: job_object (medium)" in rendered
    assert "- database: sqlite (full)" in rendered


def test_a_capability_with_no_backend_says_none() -> None:
    assert "- secrets: none (unavailable)" in render(context())


def test_a_machine_with_no_capabilities_still_reports_its_hardware() -> None:
    bare = MachineFacts(
        os_version="Windows 11 Pro 26100",
        cpu_cores=8,
        ram_gb=16.0,
        free_disk_gb=214.5,
    )
    rendered = render(context(machine=bare))

    assert "MACHINE" in rendered
    assert "- cpu cores: 8" in rendered


def test_the_working_directory_is_stated_verbatim() -> None:
    assert SCOPE in render(context())


def test_criteria_carry_their_ids() -> None:
    rendered = render(context())

    assert "c1" in rendered
    assert "c2" in rendered


def test_criteria_carry_status_and_check_kind() -> None:
    assert "[unverified/deterministic]" in render(context())


def test_a_task_with_no_criteria_says_so() -> None:
    rendered = render(context(criteria=[]))

    assert "none recorded for this task" in rendered


def test_a_missing_brief_drops_only_that_section() -> None:
    rendered = render(context(brief=None))

    assert "PROJECT" not in rendered
    assert "ACCEPTANCE CRITERIA" in rendered


def test_history_shrinks_before_anything_else_is_lost() -> None:
    full = context()
    squeezed = render(full, budget=len(render(full)) - 200)

    assert "c1" in squeezed
    assert "c2" in squeezed
    assert SCOPE in squeezed
    assert "Earlier task 11" not in squeezed


def test_criteria_survive_a_budget_that_kills_all_history() -> None:
    full = context()
    squeezed = render(full, budget=400)

    assert "c1" in squeezed
    assert "RECENT TASKS" not in squeezed


def test_the_machine_survives_a_budget_that_kills_all_history() -> None:
    full = context()
    squeezed = render(full, budget=len(render(full)) - 200)

    assert "- os: Windows 11 Pro 26100" in squeezed
    assert "Earlier task 11" not in squeezed


def test_history_is_capped_before_any_budget_pressure() -> None:
    many = context(history=[HistoryEntry(title=f"Task {n}", state="done") for n in range(40)])
    rendered = render(many)

    assert "(12 of 40)" in rendered


def test_a_long_description_is_truncated_rather_than_dropped() -> None:
    verbose = TaskFacts(
        title="Provision the project database",
        description="x" * 9000,
        kind="code",
        state="ready",
    )
    rendered = render(context(task=verbose))

    assert "[...truncated]" in rendered
    assert "Provision the project database" in rendered


def test_criterion_ids_matches_what_was_rendered() -> None:
    assert criterion_ids(context()) == ["c1", "c2"]


def test_a_workspace_file_carries_its_size_and_the_names_it_defines() -> None:
    rendered = render(context())

    assert "- db_helper.py (1242 bytes) defines create_task, select_all_tasks" in rendered


def test_a_workspace_file_with_no_names_carries_only_its_size() -> None:
    assert "- README.md (88 bytes)\n" in render(context())


def test_the_workspace_says_how_many_files_it_lists() -> None:
    assert "WORKSPACE FILES (2 of 2)" in render(context())


def test_an_empty_workspace_says_the_directory_is_empty() -> None:
    rendered = render(context(workspace=[]))

    assert "the working directory is empty" in rendered
    assert "WORKING DIRECTORY" in rendered


def test_a_long_name_list_is_cut_with_a_count() -> None:
    crowded = [
        WorkspaceFile(
            path="models.py",
            size_bytes=4096,
            names=[f"name{index}" for index in range(20)],
        )
    ]
    rendered = render(context(workspace=crowded))

    assert "name0" in rendered
    assert "and 8 more" in rendered
    assert "name19" not in rendered


def test_the_workspace_survives_a_budget_that_kills_all_history() -> None:
    full = context()
    squeezed = render(full, budget=len(render(full)) - 200)

    assert "db_helper.py" in squeezed
    assert "Earlier task 11" not in squeezed


def test_the_workspace_shrinks_only_once_history_is_gone() -> None:
    many = context(
        workspace=[
            WorkspaceFile(path=f"file{index:02d}.py", size_bytes=100, names=["run"])
            for index in range(30)
        ]
    )
    squeezed = render(many, budget=1500)

    assert "RECENT TASKS" not in squeezed
    assert "WORKSPACE FILES (16 of 30)" in squeezed


def test_a_workspace_too_large_for_the_budget_says_it_was_not_listed() -> None:
    many = context(
        workspace=[
            WorkspaceFile(path=f"file{index:02d}.py", size_bytes=100, names=["run"])
            for index in range(30)
        ]
    )
    squeezed = render(many, budget=800)

    assert "WORKSPACE FILES (0 of 30)" in squeezed
    assert "c1" in squeezed
