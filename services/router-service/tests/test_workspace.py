from __future__ import annotations

from pathlib import Path

from router_service.workspace import defined_names, scan

MODULE = """
import sqlite3

DATABASE = "tasks.db"


def create_task(title: str) -> int:
    return 1


def select_all_tasks() -> list[str]:
    return []


class TaskStore:
    def open(self) -> None:
        return None


def _private_helper() -> None:
    return None
"""


def write(root: Path, name: str, text: str) -> Path:
    path = root / name
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")

    return path


def test_a_missing_directory_scans_to_nothing(tmp_path: Path) -> None:
    assert scan(tmp_path / "absent") == []


def test_an_empty_directory_scans_to_nothing(tmp_path: Path) -> None:
    assert scan(tmp_path) == []


def test_a_file_carries_its_size_in_bytes(tmp_path: Path) -> None:
    write(tmp_path, "notes.txt", "hello")
    found = scan(tmp_path)

    assert found[0].path == "notes.txt"
    assert found[0].size_bytes == 5


def test_a_python_file_carries_the_names_it_defines(tmp_path: Path) -> None:
    write(tmp_path, "db_helper.py", MODULE)
    found = scan(tmp_path)

    assert found[0].names == ["DATABASE", "create_task", "select_all_tasks", "TaskStore"]


def test_a_private_name_is_left_out(tmp_path: Path) -> None:
    write(tmp_path, "db_helper.py", MODULE)

    assert "_private_helper" not in scan(tmp_path)[0].names


def test_a_name_defined_inside_a_function_is_not_a_module_name(tmp_path: Path) -> None:
    write(tmp_path, "inner.py", "def outer() -> None:\n    inner = 1\n")

    assert scan(tmp_path)[0].names == ["outer"]


def test_an_annotated_constant_is_a_name(tmp_path: Path) -> None:
    write(tmp_path, "settings.py", "TIMEOUT: int = 30\n")

    assert scan(tmp_path)[0].names == ["TIMEOUT"]


def test_a_file_that_does_not_parse_is_still_listed(tmp_path: Path) -> None:
    write(tmp_path, "broken.py", "def (:\n")
    found = scan(tmp_path)

    assert found[0].path == "broken.py"
    assert found[0].names == []


def test_a_file_that_is_not_python_carries_no_names(tmp_path: Path) -> None:
    write(tmp_path, "README.md", "# Notes\n\ndef create_task() -> None: ...\n")

    assert scan(tmp_path)[0].names == []


def test_a_nested_file_carries_its_path_from_the_root(tmp_path: Path) -> None:
    write(tmp_path, "src/api.py", "def health() -> None:\n    return None\n")
    found = scan(tmp_path)

    assert found[0].path == str(Path("src") / "api.py")


def test_a_generated_directory_is_never_walked(tmp_path: Path) -> None:
    write(tmp_path, "main.py", "def run() -> None:\n    return None\n")
    write(tmp_path, "__pycache__/main.cpython-312.pyc", "x")
    write(tmp_path, ".venv/Lib/site.py", "def site() -> None:\n    return None\n")
    listed = [entry.path for entry in scan(tmp_path)]

    assert listed == ["main.py"]


def test_the_files_at_the_root_come_first(tmp_path: Path) -> None:
    write(tmp_path, "src/api.py", "")
    write(tmp_path, "main.py", "")
    listed = [entry.path for entry in scan(tmp_path)]

    assert listed[0] == "main.py"


def test_the_order_is_stable(tmp_path: Path) -> None:
    for name in ["c.py", "a.py", "b.py"]:
        write(tmp_path, name, "")

    assert [entry.path for entry in scan(tmp_path)] == ["a.py", "b.py", "c.py"]


def test_the_listing_stops_at_the_limit(tmp_path: Path) -> None:
    for index in range(12):
        write(tmp_path, f"file{index:02d}.py", "")

    assert len(scan(tmp_path, limit=5)) == 5


def test_a_name_defined_twice_is_listed_once() -> None:
    assert defined_names("def run() -> None: ...\ndef run() -> None: ...\n") == ["run"]


def test_an_async_definition_is_a_name() -> None:
    assert defined_names("async def fetch() -> None: ...\n") == ["fetch"]


def test_an_import_is_not_a_definition() -> None:
    assert defined_names("import sqlite3\nfrom pathlib import Path\n") == []
