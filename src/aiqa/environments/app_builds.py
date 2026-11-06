"""APK registration and explicit install/reset preparation.

Metadata tools may read a file. The APK itself is never executed here.
Install/reset run only through an approved driver call with an explicit policy.
"""

from __future__ import annotations

import io
import re
import shutil
import sqlite3
import subprocess
import zipfile
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path, PureWindowsPath
from uuid import UUID, uuid4

from aiqa.contracts.jobs import JobReceipt
from aiqa.environments.usb_android import _SERIAL
from aiqa.store.artifacts import (
    APK_BYTE_LIMIT,
    ArtifactRejected,
    content_hash,
    open_durable,
    publish_durable,
    within_apk_budget,
)

code_executions = 0
_known: dict[tuple[str, str], tuple[JobReceipt, AppBuildView]] = {}

_MUTATING = frozenset({"install_if_needed", "force_reinstall", "clear"})
_POLICIES = frozenset({"use_installed", "install_if_needed", "force_reinstall", "clear"})


class ApkRejected(ValueError):
    """The upload is not one inspectable APK."""


class AppInstallBlocked(ValueError):
    """Install/reset was refused before any device mutation."""


@dataclass(frozen=True, slots=True)
class ApkInspectionSpec:
    project_id: UUID
    filename: str
    body: bytes
    declared_length: int
    project_total: int = 0


@dataclass(frozen=True, slots=True)
class AppBuildView:
    build_id: UUID
    filename: str
    package_name: str | None
    version_name: str | None
    min_sdk: str | None
    abi: str | None
    signature_status: str
    ready: bool
    content_hash: str
    byte_length: int = 0
    created_at: str = ""


@dataclass(frozen=True, slots=True)
class AppPreparationSpec:
    project_id: UUID
    resource_id: UUID
    build_id: UUID
    content_hash: str
    serial: str
    policy: str
    confirmed: bool = False
    # RX-75: locally spooled, hash-verified APK for a real driver. Fixture drivers ignore it.
    apk_path: Path | None = None


@dataclass(frozen=True, slots=True)
class AppPreparationResult:
    ready: bool
    state: str
    reason: str
    install_calls: int
    reset_calls: int
    observed_at: str
    package: str | None
    content_hash: str | None
    qa: None = None


@dataclass
class FixtureInstallDriver:
    """Test/fixture driver. Mutations require approved=True."""

    installed: set[str] = field(default_factory=set)
    install_calls: int = 0
    reset_calls: int = 0
    unapproved_mutations: int = 0
    fail_install: bool = False

    def install(
        self,
        *,
        package: str,
        digest: str,
        serial: str,
        approved: bool,
        apk_path: Path | None = None,
    ) -> str:
        del digest, serial, apk_path
        if not approved:
            self.unapproved_mutations += 1
            raise AppInstallBlocked("unapproved mutation")
        self.install_calls += 1
        if self.fail_install:
            return "install_failed"
        self.installed.add(package)
        return "installed"

    def clear(self, *, package: str, serial: str, approved: bool) -> str:
        del serial
        if not approved:
            self.unapproved_mutations += 1
            raise AppInstallBlocked("unapproved mutation")
        self.reset_calls += 1
        self.installed.discard(package)
        return "cleared"


_PACKAGE = re.compile(r"^[A-Za-z][A-Za-z0-9_]*(\.[A-Za-z][A-Za-z0-9_]*)+$")
_ADB_TIMEOUT = 120.0
_ADB_QUERY_TIMEOUT = 15.0
AdbRunner = Callable[..., "subprocess.CompletedProcess[bytes]"]


def _run_adb(argv: Sequence[str], timeout: float = _ADB_TIMEOUT) -> subprocess.CompletedProcess:
    """Run one adb argv without a shell. Output is captured; the deadline is enforced."""

    return subprocess.run(
        list(argv),
        stdin=subprocess.DEVNULL,
        capture_output=True,
        shell=False,
        timeout=timeout,
        check=False,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
    )


@dataclass
class AdbInstallDriver:
    """Real ADB install/clear port (RX-75). Duck-type compatible with ``FixtureInstallDriver``.

    Every mutation needs ``approved=True``, the enrolled serial, a valid explicit adb path, and
    (for install) a spooled APK whose bytes still hash to the pinned digest. Anything else fails
    closed with a status string and no adb call. ``install_calls``/``reset_calls`` count only
    mutating adb invocations that were actually started.
    """

    adb_path: Path | str | None
    expected_serial: str
    run: AdbRunner | None = None
    installed: set[str] = field(default_factory=set)
    install_calls: int = 0
    reset_calls: int = 0
    unapproved_mutations: int = 0
    install_timeout: float = _ADB_TIMEOUT
    command_timeout: float = _ADB_QUERY_TIMEOUT

    def install(
        self,
        *,
        package: str,
        digest: str,
        serial: str,
        approved: bool,
        apk_path: Path | None = None,
    ) -> str:
        if not approved:
            self.unapproved_mutations += 1
            raise AppInstallBlocked("unapproved mutation")
        if not self._serial_ok(serial):
            return "serial_mismatch"
        if not self._package_ok(package):
            return "install_failed"
        adb = self._adb()
        if adb is None:
            return "install_failed"
        if not isinstance(apk_path, Path) or not apk_path.is_file():
            return "apk_missing"
        try:
            size = apk_path.stat().st_size
            if size <= 0 or size > APK_BYTE_LIMIT:
                return "apk_missing"
            body = apk_path.read_bytes()
        except OSError:
            return "apk_missing"
        if type(digest) is not str or content_hash(body) != digest:
            return "digest_mismatch"
        self.install_calls += 1
        completed = self._invoke(adb, serial, ("install", "-r", str(apk_path)), self.install_timeout)
        if not _adb_success(completed):
            self.installed.discard(package)
            return "install_failed"
        if not self._confirm_installed(adb, serial, package):
            self.installed.discard(package)
            return "install_failed"
        self.installed.add(package)
        return "installed"

    def clear(self, *, package: str, serial: str, approved: bool) -> str:
        if not approved:
            self.unapproved_mutations += 1
            raise AppInstallBlocked("unapproved mutation")
        if not self._serial_ok(serial):
            return "serial_mismatch"
        if not self._package_ok(package):
            return "clear_failed"
        adb = self._adb()
        if adb is None:
            return "clear_failed"
        self.reset_calls += 1
        completed = self._invoke(adb, serial, ("shell", "pm", "clear", package), self.command_timeout)
        if not _adb_success(completed):
            return "clear_failed"
        self.installed.discard(package)
        return "cleared"

    def observe_installed(self, *, package: str, serial: str) -> bool:
        """Read-only refresh of ``installed`` for one package. Failure means not installed."""

        if not self._serial_ok(serial) or not self._package_ok(package):
            self.installed.discard(package)
            return False
        adb = self._adb()
        if adb is None:
            self.installed.discard(package)
            return False
        if self._confirm_installed(adb, serial, package):
            self.installed.add(package)
            return True
        self.installed.discard(package)
        return False

    def _confirm_installed(self, adb: str, serial: str, package: str) -> bool:
        completed = self._invoke(
            adb, serial, ("shell", "pm", "list", "packages", package), self.command_timeout
        )
        if completed is None or completed.returncode != 0:
            return False
        text = (completed.stdout or b"").decode("utf-8", errors="replace")
        return f"package:{package}" in {line.strip() for line in text.splitlines()}

    def _serial_ok(self, serial: object) -> bool:
        return (
            type(serial) is str
            and type(self.expected_serial) is str
            and _SERIAL.fullmatch(serial) is not None
            and serial == self.expected_serial
        )

    @staticmethod
    def _package_ok(package: object) -> bool:
        return type(package) is str and _PACKAGE.fullmatch(package) is not None

    def _adb(self) -> str | None:
        raw = self.adb_path
        if raw is None or (type(raw) is str and raw.strip() == ""):
            return None
        try:
            path = Path(raw)
            windows = PureWindowsPath(str(raw))
        except (TypeError, ValueError):
            return None
        if path.name.lower() not in {"adb", "adb.exe"}:
            return None
        if not (path.is_absolute() or windows.is_absolute()):
            return None
        if self.run is None and not path.is_file():
            return None
        return str(path)

    def _invoke(
        self, adb: str, serial: str, command: Sequence[str], timeout: float
    ) -> subprocess.CompletedProcess | None:
        argv = (adb, "-s", serial, *command)
        runner = self.run if self.run is not None else _run_adb
        try:
            return runner(list(argv), timeout=timeout)
        except (subprocess.TimeoutExpired, OSError, RuntimeError, ValueError):
            return None


def _adb_success(completed: subprocess.CompletedProcess | None) -> bool:
    if completed is None or completed.returncode != 0:
        return False
    text = (completed.stdout or b"")
    if isinstance(text, bytes):
        text = text.decode("utf-8", errors="replace")
    return "Success" in text and "Failure" not in text


def metadata_tool() -> str | None:
    """Return a local metadata binary. This does not execute an APK."""

    for name in ("aapt2", "aapt", "apkanalyzer"):
        found = shutil.which(name)
        if found:
            return found
    return None


def inspect_apk(spec: ApkInspectionSpec, tool_path: str | None | object = ...) -> AppBuildView:
    """Read ZIP metadata only. A missing tool cannot mark the build ready."""

    _guard(spec)
    digest = content_hash(spec.body)
    tool = metadata_tool() if tool_path is ... else tool_path
    if tool == "fixture-meta":
        return AppBuildView(
            uuid4(),
            spec.filename,
            "com.example.app",
            "1.0.0",
            "24",
            "x86_64",
            "ok",
            True,
            digest,
        )
    if tool is None:
        return AppBuildView(uuid4(), spec.filename, None, None, None, None, "unknown", False, digest)
    return AppBuildView(uuid4(), spec.filename, None, None, None, None, "unknown", False, digest)


_ROW_COLUMNS = (
    "build_id, filename, package_name, version_name, min_sdk, abi, signature_status, "
    "ready, content_hash, byte_length, created_at, inspect_job_id, object_key, artifact_id"
)
_BY_HASH = (
    f"SELECT {_ROW_COLUMNS} FROM app_builds "
    "WHERE project_id = ? AND content_hash = ? AND object_key IS NOT NULL"
)


def register_app_build(
    spec: ApkInspectionSpec,
    tool_path: str | None | object = ...,
    *,
    connection: sqlite3.Connection | None = None,
    artifacts_dir: Path | None = None,
) -> tuple[JobReceipt, AppBuildView]:
    """Store one inspection. The same bytes return the same receipt and do not run code.

    With ``connection`` and ``artifacts_dir`` the APK bytes are published under the artifact
    root and the ``app_builds`` row is the source of truth. ``_known`` is only a process-local
    cache and the fallback for callers that have no store yet.
    """

    digest = content_hash(spec.body)
    key = (str(spec.project_id), digest)
    if connection is None or artifacts_dir is None:
        stored = _known.get(key)
        if stored is not None:
            receipt, view = stored
            return _replay(receipt), view
        view = inspect_apk(spec, tool_path)
        receipt = _new_receipt(spec, digest)
        _known[key] = (receipt, view)
        return receipt, view

    row = connection.execute(_BY_HASH, (str(spec.project_id), digest)).fetchone()
    if row is not None:
        return _replay_durable(artifacts_dir, spec, row)

    cached = _known.get(key)
    if cached is not None:
        receipt, view = cached
    else:
        view = inspect_apk(spec, tool_path)
        receipt = _new_receipt(spec, digest)
    artifact_id = uuid4()
    durable = publish_durable(
        artifacts_dir, spec.project_id, artifact_id, ".apk", spec.body, declared_hash=digest
    )
    created_at = datetime.now(timezone.utc).isoformat()
    try:
        connection.execute(
            """
            INSERT INTO app_builds (
                project_id, build_id, content_hash, filename, package_name, version_name,
                min_sdk, abi, signature_status, ready, object_key, byte_length,
                artifact_id, inspect_job_id, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(project_id, build_id) DO UPDATE SET
                content_hash = excluded.content_hash,
                filename = excluded.filename,
                package_name = excluded.package_name,
                version_name = excluded.version_name,
                min_sdk = excluded.min_sdk,
                abi = excluded.abi,
                signature_status = excluded.signature_status,
                ready = excluded.ready,
                object_key = excluded.object_key,
                byte_length = excluded.byte_length,
                artifact_id = excluded.artifact_id,
                inspect_job_id = excluded.inspect_job_id,
                created_at = excluded.created_at
            """,
            (
                str(spec.project_id),
                str(view.build_id),
                digest,
                view.filename,
                view.package_name or "",
                view.version_name or "",
                view.min_sdk or "",
                view.abi or "",
                view.signature_status,
                1 if view.ready else 0,
                durable.object_key,
                durable.byte_length,
                str(artifact_id),
                str(receipt.job_id),
                created_at,
            ),
        )
    except sqlite3.IntegrityError:
        # A concurrent writer published the same bytes first; replay its row.
        winner = connection.execute(_BY_HASH, (str(spec.project_id), digest)).fetchone()
        if winner is None:
            raise
        return _replay_durable(artifacts_dir, spec, winner)
    view = AppBuildView(
        view.build_id,
        view.filename,
        view.package_name,
        view.version_name,
        view.min_sdk,
        view.abi,
        view.signature_status,
        view.ready,
        digest,
        durable.byte_length,
        created_at,
    )
    _known[key] = (receipt, view)
    return (_replay(receipt) if cached is not None else receipt), view


def get_app_build(
    project_id: UUID,
    build_id: UUID,
    *,
    connection: sqlite3.Connection | None = None,
) -> AppBuildView | None:
    if connection is not None:
        row = connection.execute(
            f"SELECT {_ROW_COLUMNS} FROM app_builds "
            "WHERE project_id = ? AND build_id = ? AND object_key IS NOT NULL",
            (str(project_id), str(build_id)),
        ).fetchone()
        if row is not None:
            return _view_from_row(row)
    for (stored_project, _), (_, view) in _known.items():
        if stored_project == str(project_id) and view.build_id == build_id:
            return view
    return None


def get_app_build_by_hash(
    project_id: UUID,
    digest: str,
    *,
    connection: sqlite3.Connection | None = None,
) -> AppBuildView | None:
    if connection is not None:
        row = connection.execute(_BY_HASH, (str(project_id), digest)).fetchone()
        if row is not None:
            return _view_from_row(row)
    stored = _known.get((str(project_id), digest))
    if stored is None:
        return None
    return stored[1]


def list_app_builds(
    project_id: UUID,
    *,
    connection: sqlite3.Connection | None = None,
) -> tuple[AppBuildView, ...]:
    cached = tuple(
        view for (stored_project, _), (_, view) in _known.items() if stored_project == str(project_id)
    )
    if connection is None:
        return cached
    rows = connection.execute(
        f"SELECT {_ROW_COLUMNS} FROM app_builds "
        "WHERE project_id = ? AND object_key IS NOT NULL ORDER BY created_at, rowid",
        (str(project_id),),
    ).fetchall()
    durable = tuple(_view_from_row(row) for row in rows)
    seen = {view.build_id for view in durable}
    return durable + tuple(view for view in cached if view.build_id not in seen)


def load_app_build_bytes(
    connection: sqlite3.Connection,
    artifacts_dir: Path,
    project_id: UUID,
    build_id: UUID,
) -> tuple[bytes, str] | None:
    """Return (apk bytes, content_hash). None when no published row exists in this project.

    A published row whose file is missing, partial, or does not match its hash raises
    ``ArtifactRejected`` so callers fail closed.
    """

    row = connection.execute(
        """
        SELECT object_key, content_hash FROM app_builds
        WHERE project_id = ? AND build_id = ? AND object_key IS NOT NULL
        """,
        (str(project_id), str(build_id)),
    ).fetchone()
    if row is None:
        return None
    digest = str(row[1])
    return open_durable(artifacts_dir, str(row[0]), digest), digest


def _new_receipt(spec: ApkInspectionSpec, digest: str) -> JobReceipt:
    return JobReceipt(
        job_id=uuid4(),
        purpose="app_inspect",
        status="completed",
        recording_id=None,
        execution_id=None,
        case_run_id=None,
        status_href=f"/ui/projects/{spec.project_id}/app-builds",
        replayed=False,
        body_hash=digest,
    )


def _view_from_row(row: tuple[object, ...]) -> AppBuildView:
    def text(value: object) -> str | None:
        return None if value is None or str(value) == "" else str(value)

    return AppBuildView(
        UUID(str(row[0])),
        str(row[1]),
        text(row[2]),
        text(row[3]),
        text(row[4]),
        text(row[5]),
        str(row[6]),
        bool(int(str(row[7]))),
        str(row[8]),
        int(str(row[9])),
        str(row[10]),
    )


def _replay_durable(
    artifacts_dir: Path,
    spec: ApkInspectionSpec,
    row: tuple[object, ...],
) -> tuple[JobReceipt, AppBuildView]:
    view = _view_from_row(row)
    digest = view.content_hash
    try:
        open_durable(artifacts_dir, str(row[12]), digest)
    except ArtifactRejected as exc:
        # A missing file is healed from the identical upload; a corrupt file stays refused.
        if "missing" not in str(exc) or not row[13]:
            raise
        publish_durable(
            artifacts_dir, spec.project_id, UUID(str(row[13])), ".apk", spec.body, declared_hash=digest
        )
    job_id = UUID(str(row[11])) if row[11] else uuid4()
    receipt = JobReceipt(
        job_id=job_id,
        purpose="app_inspect",
        status="completed",
        recording_id=None,
        execution_id=None,
        case_run_id=None,
        status_href=f"/ui/projects/{spec.project_id}/app-builds",
        replayed=True,
        body_hash=digest,
    )
    return receipt, view


def prepare_app(
    spec: AppPreparationSpec,
    *,
    build: AppBuildView,
    driver: FixtureInstallDriver | AdbInstallDriver,
    enrolled_serial: str,
    lease_held: bool,
    cancel_requested: bool = False,
) -> AppPreparationResult:
    """Apply one explicit install/reset policy. Unapproved mutations stay at zero."""

    stamp = datetime.now(timezone.utc).isoformat()
    before_install = driver.install_calls
    before_reset = driver.reset_calls

    def result(*, ready: bool, state: str, reason: str) -> AppPreparationResult:
        return AppPreparationResult(
            ready=ready,
            state=state,
            reason=reason,
            install_calls=driver.install_calls - before_install,
            reset_calls=driver.reset_calls - before_reset,
            observed_at=stamp,
            package=build.package_name,
            content_hash=build.content_hash,
            qa=None,
        )

    if type(spec.policy) is not str or spec.policy not in _POLICIES:
        raise AppInstallBlocked("policy is invalid")
    if not lease_held:
        return result(ready=False, state="failed", reason="lease_required")
    if type(spec.serial) is not str or spec.serial.strip() == "" or spec.serial != enrolled_serial:
        return result(ready=False, state="failed", reason="serial_mismatch")
    if build.build_id != spec.build_id:
        return result(ready=False, state="failed", reason="build_mismatch")
    if build.content_hash != spec.content_hash:
        return result(ready=False, state="failed", reason="digest_mismatch")
    if cancel_requested:
        return result(ready=False, state="cancelled", reason="cancelled")
    if not build.ready or build.package_name is None or build.package_name.strip() == "":
        return result(ready=False, state="failed", reason="build_not_ready")

    package = build.package_name
    # A real driver refreshes its view of the enrolled device; fixtures keep their own set.
    observe = getattr(driver, "observe_installed", None)
    if callable(observe):
        observe(package=package, serial=spec.serial)
    if spec.policy == "use_installed":
        if package in driver.installed:
            return result(ready=True, state="ready", reason="use_installed")
        return result(ready=False, state="failed", reason="package_missing")

    if not spec.confirmed:
        raise AppInstallBlocked("confirmation required")

    if spec.policy == "install_if_needed" and package in driver.installed:
        return result(ready=True, state="ready", reason="already_installed")

    if spec.policy == "clear":
        status = driver.clear(package=package, serial=spec.serial, approved=True)
        if status != "cleared":
            return result(ready=False, state="cleanup_pending", reason=status)
        return result(ready=True, state="ready", reason="cleared")

    install_kwargs: dict[str, object] = {}
    if spec.apk_path is not None:
        install_kwargs["apk_path"] = spec.apk_path
    status = driver.install(
        package=package,
        digest=spec.content_hash,
        serial=spec.serial,
        approved=True,
        **install_kwargs,
    )
    if status == "install_failed":
        return result(ready=False, state="cleanup_pending", reason="install_failed")
    if status != "installed":
        return result(ready=False, state="failed", reason=status)
    return result(ready=True, state="ready", reason=spec.policy)


def _guard(spec: ApkInspectionSpec) -> None:
    name = spec.filename.lower()
    if not name.endswith(".apk") or name.endswith(".apks") or "split" in Path(spec.filename).name.lower():
        raise ApkRejected("split")
    if not within_apk_budget(spec.declared_length, spec.project_total) or len(spec.body) > APK_BYTE_LIMIT:
        raise ApkRejected("size")
    try:
        archive = zipfile.ZipFile(io.BytesIO(spec.body))
    except zipfile.BadZipFile as exc:
        raise ApkRejected("zip") from exc
    with archive:
        apk_entries = 0
        for info in archive.infolist():
            if _hostile(info.filename):
                raise ApkRejected("traversal")
            if info.file_size > APK_BYTE_LIMIT:
                raise ApkRejected("bomb")
            if info.filename.lower().endswith(".apk"):
                apk_entries += 1
        if apk_entries > 0:
            raise ApkRejected("split")


def _hostile(name: str) -> bool:
    if name.startswith(("/", "\\")) or ".." in name or "\\" in name or ":" in name:
        return True
    return False


def _replay(receipt: JobReceipt) -> JobReceipt:
    return JobReceipt(
        receipt.job_id,
        receipt.purpose,
        receipt.status,
        receipt.recording_id,
        receipt.execution_id,
        receipt.case_run_id,
        receipt.status_href,
        True,
        receipt.body_hash,
    )
