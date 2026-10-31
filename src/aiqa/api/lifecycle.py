"""API process start. Factory creation stays free of SQLite; start reconciles jobs."""

from __future__ import annotations

import ctypes
from ctypes import wintypes
from datetime import datetime

from fastapi import FastAPI

from aiqa.config import AppSettings

_boot_id: str | None = None
_SYSTEM_TIMEOFDAY_INFORMATION = 3


class _TimeOfDay(ctypes.Structure):
    _fields_ = (
        ("boot_time", ctypes.c_longlong),
        ("current_time", ctypes.c_longlong),
        ("timezone_bias", ctypes.c_longlong),
        ("timezone_id", wintypes.ULONG),
        ("reserved", wintypes.ULONG),
        ("boot_time_bias", ctypes.c_ulonglong),
        ("sleep_time_bias", ctypes.c_ulonglong),
    )


def host_boot_id() -> str:
    """Stable id of this PC boot. An API process restart does not change it."""

    global _boot_id
    if _boot_id is not None:
        return _boot_id
    info = _TimeOfDay()
    status = ctypes.WinDLL("ntdll").NtQuerySystemInformation(
        _SYSTEM_TIMEOFDAY_INFORMATION,
        ctypes.byref(info),
        ctypes.sizeof(info),
        None,
    )
    if status != 0:
        raise OSError("host boot id is unavailable")
    _boot_id = str(int(info.boot_time))
    return _boot_id


def start_api(settings: AppSettings, now: datetime) -> FastAPI:
    """Open one API process and reconcile queued jobs against the current boot."""

    from aiqa.api.app import create_app
    from aiqa.store.database import migrate_store
    from aiqa.worker.service import bind_claim_store, reconcile_jobs

    application = create_app(settings)
    store = application.state.open_store()
    try:
        migrate_store(store)
        with bind_claim_store(store):
            reconcile_jobs(now)
    finally:
        store.close()
    return application
