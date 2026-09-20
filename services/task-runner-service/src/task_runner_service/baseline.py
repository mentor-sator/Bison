from __future__ import annotations

from collections.abc import Mapping
from typing import Final

BASELINE_KEYS: Final[tuple[str, ...]] = (
    "SYSTEMROOT",
    "WINDIR",
    "SYSTEMDRIVE",
    "COMSPEC",
    "PATHEXT",
    "NUMBER_OF_PROCESSORS",
    "PROCESSOR_ARCHITECTURE",
    "OS",
)


def baseline(source: Mapping[str, str]) -> dict[str, str]:
    by_name = {key.upper(): value for key, value in source.items()}

    return {key: by_name[key] for key in BASELINE_KEYS if by_name.get(key)}


def launch_environment(declared: Mapping[str, str], source: Mapping[str, str]) -> dict[str, str]:
    merged = baseline(source)
    overridden = {key.upper() for key in declared}

    for key in list(merged):
        if key in overridden:
            del merged[key]

    merged.update(declared)

    return merged
