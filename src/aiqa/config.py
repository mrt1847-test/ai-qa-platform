"""Process settings for the single local API. This module opens no clients."""

from __future__ import annotations

import os
import re
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

LOOPBACK_HOST = "127.0.0.1"
DEFAULT_PORT = 8000
_PORT_TEXT = re.compile(r"[0-9]+")


class SettingsError(ValueError):
    """AIQA_HOST, AIQA_PORT, or the runtime root was refused."""


@dataclass(frozen=True, slots=True)
class AppSettings:
    host: str
    port: int
    runtime_root: Path

    def __post_init__(self) -> None:
        if type(self.host) is not str or self.host != LOOPBACK_HOST:
            raise SettingsError(f"AIQA_HOST must be {LOOPBACK_HOST}; refused {self.host!r}")
        if type(self.port) is not int or not 1 <= self.port <= 65535:
            raise SettingsError(
                f"AIQA_PORT must be an integer from 1 to 65535; refused {self.port!r}"
            )
        if not isinstance(self.runtime_root, Path):
            raise SettingsError("runtime_root must be a pathlib.Path")


def load_settings(env: Mapping[str, str] | None = None) -> AppSettings:
    """Read AIQA_* from env, or from the process environment when env is omitted."""

    source: Mapping[str, str] = os.environ if env is None else env
    host = source["AIQA_HOST"] if "AIQA_HOST" in source else LOOPBACK_HOST
    port = _parse_port(source["AIQA_PORT"]) if "AIQA_PORT" in source else DEFAULT_PORT
    if "AIQA_RUNTIME_ROOT" in source:
        raw_root = source["AIQA_RUNTIME_ROOT"]
        if type(raw_root) is not str or raw_root.strip() == "":
            raise SettingsError("AIQA_RUNTIME_ROOT is empty")
        runtime_root = Path(raw_root)
    else:
        local = source["LOCALAPPDATA"] if "LOCALAPPDATA" in source else ""
        if type(local) is not str or local.strip() == "":
            raise SettingsError("AIQA_RUNTIME_ROOT is unset and LOCALAPPDATA is missing")
        runtime_root = Path(local) / "AIQA"
    return AppSettings(host=host, port=port, runtime_root=runtime_root)


def _parse_port(raw: object) -> int:
    if type(raw) is not str or _PORT_TEXT.fullmatch(raw) is None:
        raise SettingsError(f"AIQA_PORT is not an integer: {raw!r}")
    return int(raw, 10)
