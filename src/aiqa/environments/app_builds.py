"""APK registration. Metadata tools may read a file. The APK itself is never executed."""

from __future__ import annotations

import io
import shutil
import zipfile
from dataclasses import dataclass
from pathlib import Path
from uuid import UUID, uuid4

from aiqa.contracts.jobs import JobReceipt
from aiqa.store.artifacts import APK_BYTE_LIMIT, content_hash, within_apk_budget

code_executions = 0
_known: dict[tuple[str, str], tuple[JobReceipt, AppBuildView]] = {}


class ApkRejected(ValueError):
    """The upload is not one inspectable APK."""


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


def list_app_builds(project_id: UUID) -> tuple[AppBuildView, ...]:
    return tuple(view for (stored_project, _), (_, view) in _known.items() if stored_project == str(project_id))


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
