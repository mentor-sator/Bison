from __future__ import annotations

import sys
from pathlib import Path

import pytest

from task_runner_service.baseline import BASELINE_KEYS, baseline, launch_environment

WINDOWS = {
    "SystemRoot": r"C:\WINDOWS",
    "windir": r"C:\WINDOWS",
    "SystemDrive": "C:",
    "ComSpec": r"C:\WINDOWS\system32\cmd.exe",
    "PATHEXT": ".COM;.EXE;.BAT",
    "NUMBER_OF_PROCESSORS": "14",
    "PROCESSOR_ARCHITECTURE": "AMD64",
    "OS": "Windows_NT",
    "OPENROUTER_API_KEY": "sk-secret",
    "USERPROFILE": r"C:\Users\dev",
    "PATH": r"C:\Windows\system32;C:\tools",
}


def test_the_baseline_carries_only_what_windows_needs_to_run_a_process() -> None:
    assert set(baseline(WINDOWS)) == set(BASELINE_KEYS)


def test_names_are_matched_whatever_their_case() -> None:
    assert baseline(WINDOWS)["SYSTEMROOT"] == r"C:\WINDOWS"
    assert baseline(WINDOWS)["WINDIR"] == r"C:\WINDOWS"


def test_secrets_and_the_user_profile_never_reach_the_sandbox() -> None:
    merged = launch_environment({}, WINDOWS)

    assert "OPENROUTER_API_KEY" not in merged
    assert "USERPROFILE" not in merged


def test_the_machine_path_is_not_inherited() -> None:
    assert "PATH" not in launch_environment({}, WINDOWS)


def test_a_missing_or_empty_variable_is_left_out() -> None:
    assert baseline({"SYSTEMROOT": r"C:\WINDOWS", "WINDIR": ""}) == {"SYSTEMROOT": r"C:\WINDOWS"}


def test_what_the_step_declares_is_kept_alongside_the_baseline() -> None:
    merged = launch_environment({"PATH": r"C:\venv\Scripts", "VIRTUAL_ENV": r"C:\venv"}, WINDOWS)

    assert merged["PATH"] == r"C:\venv\Scripts"
    assert merged["VIRTUAL_ENV"] == r"C:\venv"
    assert merged["SYSTEMROOT"] == r"C:\WINDOWS"


def test_a_declared_value_replaces_the_baseline_one_whatever_its_case() -> None:
    merged = launch_environment({"SystemRoot": r"D:\WINDOWS"}, WINDOWS)

    assert merged["SystemRoot"] == r"D:\WINDOWS"
    assert "SYSTEMROOT" not in merged


@pytest.fixture
def workspace(tmp_path: Path) -> Path:
    directory = tmp_path.resolve() / "workspace"
    directory.mkdir()

    return directory


@pytest.fixture
def runs(tmp_path: Path) -> Path:
    return tmp_path.resolve() / "runs"


@pytest.mark.skipif(sys.platform != "win32", reason="the job object sandbox is Windows only")
async def test_a_sandboxed_process_can_resolve_a_host_name(workspace: Path, runs: Path) -> None:
    from task_runner_service.jobobject import JobObjectSandbox
    from task_runner_service.sandbox import (
        Limits,
        Mount,
        OutputChunk,
        SandboxRequest,
    )

    class Recorder:
        def __init__(self) -> None:
            self.chunks: list[OutputChunk] = []

        async def emit(self, chunk: OutputChunk) -> None:
            self.chunks.append(chunk)

        def text(self) -> str:
            return "".join(chunk.text for chunk in self.chunks if chunk.stream == "stdout")

    recorder = Recorder()
    body = "import socket; print(len(socket.getaddrinfo('localhost', 80)) > 0)"
    request = SandboxRequest(
        step_id="step-1",
        program=sys.executable,
        arguments=["-c", body],
        working_directory=str(workspace),
        mounts=[Mount(path=str(workspace), writable=True)],
        environment={},
        network=False,
        limits=Limits(wall_clock_seconds=30, memory_mb=256, max_output_bytes=65536),
    )

    result = await JobObjectSandbox(runtime_dir=runs).run(request, recorder)

    assert result.exit_code == 0
    assert recorder.text().strip() == "True"
