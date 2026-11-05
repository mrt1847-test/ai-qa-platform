"""APK registration and explicit install/reset preparation.

Metadata tools may read a file. The APK itself is never executed here.
Install/reset run only through an approved driver call with an explicit policy.
"""

from __future__ import annotations

import io
import shutil
import zipfile
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from uuid import UUID, uuid4

from aiqa.contracts.jobs import JobReceipt
from aiqa.store.artifacts import APK_BYTE_LIMIT, content_hash, within_apk_budget

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


@dataclass(frozen=True, slots=True)
class AppPreparationSpec:
    project_id: UUID
    resource_id: UUID
    build_id: UUID
    content_hash: str
    serial: str
    policy: str
    confirmed: bool = False


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

    def install(self, *, package: str, digest: str, serial: str, approved: bool) -> str:
        del digest, serial
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


def register_app_build(spec: ApkInspectionSpec, tool_path: str | None | object = ...) -> tuple[JobReceipt, AppBuildView]:
    """Store one inspection. The same bytes return the same receipt and do not run code."""

    digest = content_hash(spec.body)
    key = (str(spec.project_id), digest)
    stored = _known.get(key)
    if stored is not None:
        receipt, view = stored
        return _replay(receipt), view
    view = inspect_apk(spec, tool_path)
    receipt = JobReceipt(
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
    _known[key] = (receipt, view)
    return receipt, view


def get_app_build(project_id: UUID, build_id: UUID) -> AppBuildView | None:
    for (stored_project, _), (_, view) in _known.items():
        if stored_project == str(project_id) and view.build_id == build_id:
            return view
    return None


def get_app_build_by_hash(project_id: UUID, digest: str) -> AppBuildView | None:
    stored = _known.get((str(project_id), digest))
    if stored is None:
        return None
    return stored[1]


def list_app_builds(project_id: UUID) -> tuple[AppBuildView, ...]:
    return tuple(view for (stored_project, _), (_, view) in _known.items() if stored_project == str(project_id))


def prepare_app(
    spec: AppPreparationSpec,
    *,
    build: AppBuildView,
    driver: FixtureInstallDriver,
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

    status = driver.install(
        package=package,
        digest=spec.content_hash,
        serial=spec.serial,
        approved=True,
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
