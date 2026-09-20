from __future__ import annotations

import ast
import os
from pathlib import Path

from router_service.context import MAX_WORKSPACE_FILES, WorkspaceFile

MAX_PARSED_BYTES = 400_000
MAX_DEPTH = 6

SKIPPED_DIRECTORIES = frozenset(
    {
        ".git",
        ".idea",
        ".mypy_cache",
        ".pytest_cache",
        ".ruff_cache",
        ".turbo",
        ".venv",
        ".vscode",
        "__pycache__",
        "build",
        "dist",
        "node_modules",
        "venv",
    }
)

PARSED_SUFFIXES = frozenset({".py"})


def defined_names(source: str) -> list[str]:
    try:
        tree = ast.parse(source)
    except (SyntaxError, ValueError):
        return []

    found: list[str] = []

    for node in tree.body:
        if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef):
            found.append(node.name)
        elif isinstance(node, ast.Assign):
            found.extend(target.id for target in node.targets if isinstance(target, ast.Name))
        elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            found.append(node.target.id)

    ordered: list[str] = []

    for name in found:
        if not name.startswith("_") and name not in ordered:
            ordered.append(name)

    return ordered


def names_in(path: Path, size: int) -> list[str]:
    if path.suffix.lower() not in PARSED_SUFFIXES or size > MAX_PARSED_BYTES:
        return []

    try:
        source = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return []

    return defined_names(source)


def entry_for(path: Path, root: Path) -> WorkspaceFile | None:
    try:
        size = path.stat().st_size
    except OSError:
        return None

    return WorkspaceFile(
        path=str(path.relative_to(root)),
        size_bytes=size,
        names=names_in(path, size),
    )


def files_under(root: Path) -> list[Path]:
    collected: list[Path] = []

    for current, directories, names in os.walk(root):
        here = Path(current)
        directories[:] = sorted(
            name for name in directories if name.lower() not in SKIPPED_DIRECTORIES
        )

        if len(here.relative_to(root).parts) >= MAX_DEPTH:
            directories[:] = []

        collected.extend(here / name for name in sorted(names))

    return collected


def scan(root: Path, limit: int = MAX_WORKSPACE_FILES) -> list[WorkspaceFile]:
    if not root.is_dir():
        return []

    entries: list[WorkspaceFile] = []

    for path in files_under(root):
        if len(entries) >= limit:
            break

        entry = entry_for(path, root)

        if entry is not None:
            entries.append(entry)

    return entries
