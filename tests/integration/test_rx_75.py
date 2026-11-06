"""RX-75: real ADB install/clear driver port behind the Android worker handler."""

from __future__ import annotations

import hashlib
import json
import subprocess
from pathlib import Path
from uuid import UUID, uuid4

import pytest

from aiqa.environments.app_builds import (
    AdbInstallDriver,
    AppBuildView,
    AppInstallBlocked,
    FixtureInstallDriver,
)
from aiqa.worker.android_jobs import (
    AppInstallHandler,
    build_android_support_handlers,
    http_apk_provider,
)

ADB = Path(r"C:\sdk\platform-tools\adb.exe")
SERIAL = "emulator-5580"
PACKAGE = "com.example.app"


def _digest(body: bytes) -> str:
    return "sha256:" + hashlib.sha256(body).hexdigest()


class FakeAdb:
    """Capture argv and simulate adb install -r / pm clear / pm list packages."""

    def __init__(self, *, install_ok: bool = True, clear_ok: bool = True, list_ok: bool = True) -> None:
        self.calls: list[list[str]] = []
        self.install_ok = install_ok
        self.clear_ok = clear_ok
        self.list_ok = list_ok
        self.present: set[str] = set()

    def __call__(self, argv, timeout=None, **_: object) -> subprocess.CompletedProcess:
        assert isinstance(timeout, (int, float)) and timeout > 0
        self.calls.append([str(item) for item in argv])
        tail = list(argv)[3:]
        if tail[:2] == ["install", "-r"]:
            if self.install_ok:
                self.present.add(PACKAGE)
                return _done(0, b"Performing Streamed Install\nSuccess\n")
            return _done(1, b"Failure [INSTALL_FAILED_OLDER_SDK]\n")
        if tail[:3] == ["shell", "pm", "clear"]:
            if self.clear_ok:
                return _done(0, b"Success\n")
            return _done(1, b"Failed\n")
        if tail[:4] == ["shell", "pm", "list", "packages"]:
            if not self.list_ok:
                return _done(1, b"")
            name = tail[4]
            line = f"package:{name}\n".encode() if name in self.present else b""
            return _done(0, line)
        return _done(1, b"unsupported")

    def mutating(self) -> list[list[str]]:
        return [
            call
            for call in self.calls
            if call[3:5] == ["install", "-r"] or call[3:6] == ["shell", "pm", "clear"]
        ]


def _done(code: int, out: bytes) -> subprocess.CompletedProcess:
    return subprocess.CompletedProcess([], code, stdout=out, stderr=b"")


def _apk(tmp_path: Path, body: bytes = b"apk-bytes") -> tuple[Path, str]:
    path = tmp_path / "app.apk"
    path.write_bytes(body)
    return path, _digest(body)


def _build(digest: str, *, build_id: UUID | None = None) -> AppBuildView:
    return AppBuildView(
        build_id or uuid4(), "demo.apk", PACKAGE, "1.0", "24", "x86_64", "ok", True, digest, 9
    )


def _claim(
    project_id: UUID,
    build: AppBuildView,
    *,
    policy: str = "force_reinstall",
    serial: str = SERIAL,
    confirmed: bool = True,
) -> dict[str, object]:
    limits = {
        "build_id": str(build.build_id),
        "content_hash": build.content_hash,
        "policy": policy,
        "serial": serial,
        "confirmed": confirmed,
        "resource_id": str(uuid4()),
    }
    return {
        "project_id": str(project_id),
        "snapshot": {"purpose": "app_install", "limits": json.dumps(limits), "serial": serial},
    }


def _payload(result) -> dict[str, object]:
    return json.loads(result.action_mapping)


class FakeClient:
    def __init__(self, body: bytes, *, lie_hash: str | None = None) -> None:
        self.body = body
        self.lie_hash = lie_hash
        self.fetches = 0

    def fetch_app_build_content(self, project_id, build_id, *, expected_hash=None):
        self.fetches += 1
        return self.body, self.lie_hash or _digest(self.body)


def _handler(driver, provider, build):
    return AppInstallHandler(
        expected_serial=SERIAL, driver=driver, build=build, apk_provider=provider, lease_held=True
    )


def test_rx_75_worker_handler_installs_through_adb_driver(tmp_path: Path) -> None:
    body = b"dex-pinned-bytes"
    digest = _digest(body)
    build = _build(digest)
    fake = FakeAdb()
    driver = AdbInstallDriver(adb_path=ADB, expected_serial=SERIAL, run=fake)
    provider = http_apk_provider(FakeClient(body), tmp_path / "apk-spool")
    handler = _handler(driver, provider, build)

    result = handler.handle(_claim(uuid4(), build))

    payload = _payload(result)
    assert result.outcome == "completed"
    assert payload["ready"] is True and payload["reason"] == "force_reinstall"
    assert payload["install_calls"] == 1 and payload["unapproved_mutations"] == 0
    assert PACKAGE in driver.installed
    spooled = tmp_path / "apk-spool" / (digest.split(":")[1] + ".apk")
    assert spooled.read_bytes() == body
    installs = [call for call in fake.calls if call[3:5] == ["install", "-r"]]
    assert installs == [[str(ADB), "-s", SERIAL, "install", "-r", str(spooled)]]
    assert any(call[3:8] == ["shell", "pm", "list", "packages", PACKAGE] for call in fake.calls)


def test_rx_75_use_installed_reads_device_and_clear_removes(tmp_path: Path) -> None:
    body = b"x" * 32
    build = _build(_digest(body))
    fake = FakeAdb()
    driver = AdbInstallDriver(adb_path=ADB, expected_serial=SERIAL, run=fake)
    handler = _handler(driver, http_apk_provider(FakeClient(body), tmp_path / "s"), build)
    project = uuid4()

    missing = handler.handle(_claim(project, build, policy="use_installed", confirmed=False))
    assert missing.outcome == "error"
    assert fake.mutating() == []

    assert handler.handle(_claim(project, build)).outcome == "completed"
    present = handler.handle(_claim(project, build, policy="use_installed", confirmed=False))
    assert present.outcome == "completed"

    cleared = handler.handle(_claim(project, build, policy="clear"))
    assert cleared.outcome == "completed"
    assert PACKAGE not in driver.installed
    assert driver.reset_calls == 1
    assert [PACKAGE] == [call[6] for call in fake.calls if call[3:6] == ["shell", "pm", "clear"]]


def test_rx_75_install_failure_is_not_ready(tmp_path: Path) -> None:
    body = b"bad-install"
    build = _build(_digest(body))
    fake = FakeAdb(install_ok=False)
    driver = AdbInstallDriver(adb_path=ADB, expected_serial=SERIAL, run=fake)
    handler = _handler(driver, http_apk_provider(FakeClient(body), tmp_path / "s"), build)

    result = handler.handle(_claim(uuid4(), build))

    payload = _payload(result)
    assert result.outcome == "error"
    assert payload["ready"] is False and payload["reason"] == "install_failed"
    assert PACKAGE not in driver.installed


def test_rx_75_unconfirmed_install_stays_blocked(tmp_path: Path) -> None:
    body = b"unconfirmed"
    build = _build(_digest(body))
    fake = FakeAdb()
    driver = AdbInstallDriver(adb_path=ADB, expected_serial=SERIAL, run=fake)
    client = FakeClient(body)
    handler = _handler(driver, http_apk_provider(client, tmp_path / "s"), build)

    with pytest.raises(AppInstallBlocked):
        handler.handle(_claim(uuid4(), build, confirmed=False))
    assert fake.calls == [] or fake.mutating() == []
    assert client.fetches == 0


def test_rx_75_device_change_fails_closed(tmp_path: Path) -> None:
    path, digest = _apk(tmp_path)
    fake = FakeAdb()
    driver = AdbInstallDriver(adb_path=ADB, expected_serial=SERIAL, run=fake)

    assert driver.install(package=PACKAGE, digest=digest, serial="other-device", approved=True, apk_path=path) == (
        "serial_mismatch"
    )
    assert driver.clear(package=PACKAGE, serial="other-device", approved=True) == "serial_mismatch"
    assert driver.install(package=PACKAGE, digest=digest, serial="bad serial", approved=True, apk_path=path) == (
        "serial_mismatch"
    )
    assert fake.calls == []
    assert driver.install_calls == 0 and driver.reset_calls == 0

    # Through the handler the enrolled serial gate also refuses before any adb call.
    build = _build(digest)
    handler = _handler(driver, http_apk_provider(FakeClient(path.read_bytes()), tmp_path / "s"), build)
    result = handler.handle(_claim(uuid4(), build, serial="other-device"))
    assert result.outcome == "error"
    assert fake.calls == []


@pytest.mark.parametrize(
    "adb_path",
    [None, "", "adb.exe", Path("relative/adb.exe"), Path(r"C:\sdk\not-adb.exe")],
)
def test_rx_75_invalid_adb_path_fails_install(tmp_path: Path, adb_path) -> None:
    path, digest = _apk(tmp_path)
    fake = FakeAdb()
    driver = AdbInstallDriver(adb_path=adb_path, expected_serial=SERIAL, run=fake)

    assert driver.install(package=PACKAGE, digest=digest, serial=SERIAL, approved=True, apk_path=path) == (
        "install_failed"
    )
    assert driver.clear(package=PACKAGE, serial=SERIAL, approved=True) == "clear_failed"
    assert fake.calls == []
    assert PACKAGE not in driver.installed


def test_rx_75_missing_adb_binary_fails_without_runner(tmp_path: Path) -> None:
    path, digest = _apk(tmp_path)
    driver = AdbInstallDriver(adb_path=tmp_path / "adb.exe", expected_serial=SERIAL)
    assert driver.install(package=PACKAGE, digest=digest, serial=SERIAL, approved=True, apk_path=path) == (
        "install_failed"
    )
    assert driver.install_calls == 0


def test_rx_75_adb_launch_errors_fail_closed(tmp_path: Path) -> None:
    path, digest = _apk(tmp_path)

    def broken(argv, timeout=None):
        raise FileNotFoundError("adb")

    def slow(argv, timeout=None):
        raise subprocess.TimeoutExpired(list(argv), timeout)

    for runner in (broken, slow):
        driver = AdbInstallDriver(adb_path=ADB, expected_serial=SERIAL, run=runner)
        assert driver.install(package=PACKAGE, digest=digest, serial=SERIAL, approved=True, apk_path=path) == (
            "install_failed"
        )
        assert driver.clear(package=PACKAGE, serial=SERIAL, approved=True) == "clear_failed"
        assert PACKAGE not in driver.installed


def test_rx_75_install_requires_package_confirmation(tmp_path: Path) -> None:
    path, digest = _apk(tmp_path)
    fake = FakeAdb(list_ok=False)
    driver = AdbInstallDriver(adb_path=ADB, expected_serial=SERIAL, run=fake)

    status = driver.install(package=PACKAGE, digest=digest, serial=SERIAL, approved=True, apk_path=path)

    assert status == "install_failed"
    assert PACKAGE not in driver.installed


def test_rx_75_hash_mismatch_never_calls_install(tmp_path: Path) -> None:
    path, _ = _apk(tmp_path, b"tampered")
    fake = FakeAdb()
    driver = AdbInstallDriver(adb_path=ADB, expected_serial=SERIAL, run=fake)

    status = driver.install(
        package=PACKAGE, digest="sha256:" + "0" * 64, serial=SERIAL, approved=True, apk_path=path
    )

    assert status == "digest_mismatch"
    assert fake.calls == [] and driver.install_calls == 0
    missing = driver.install(
        package=PACKAGE, digest=_digest(b"x"), serial=SERIAL, approved=True, apk_path=tmp_path / "nope.apk"
    )
    assert missing == "apk_missing"
    none_path = driver.install(package=PACKAGE, digest=_digest(b"x"), serial=SERIAL, approved=True)
    assert none_path == "apk_missing"
    assert fake.calls == []


def test_rx_75_spool_hash_mismatch_from_server_is_blocked(tmp_path: Path) -> None:
    body = b"real-bytes"
    build = _build(_digest(body))
    fake = FakeAdb()
    driver = AdbInstallDriver(adb_path=ADB, expected_serial=SERIAL, run=fake)
    spool = tmp_path / "apk-spool"
    client = FakeClient(b"other-bytes", lie_hash=_digest(body))
    handler = _handler(driver, http_apk_provider(client, spool), build)

    result = handler.handle(_claim(uuid4(), build))

    assert result.outcome == "error"
    assert fake.calls == []
    assert not spool.exists() or list(spool.iterdir()) == []
    assert PACKAGE not in driver.installed


def test_rx_75_unapproved_mutation_is_counted_and_blocked(tmp_path: Path) -> None:
    path, digest = _apk(tmp_path)
    fake = FakeAdb()
    driver = AdbInstallDriver(adb_path=ADB, expected_serial=SERIAL, run=fake)

    with pytest.raises(AppInstallBlocked):
        driver.install(package=PACKAGE, digest=digest, serial=SERIAL, approved=False, apk_path=path)
    with pytest.raises(AppInstallBlocked):
        driver.clear(package=PACKAGE, serial=SERIAL, approved=False)

    assert driver.unapproved_mutations == 2
    assert fake.calls == []


def test_rx_75_default_assembly_uses_adb_driver_not_fixture() -> None:
    fake = FakeAdb()
    probe, install = build_android_support_handlers(adb_path=ADB, serial=SERIAL, run=fake)

    assert isinstance(install.driver, AdbInstallDriver)
    assert not isinstance(install.driver, FixtureInstallDriver)
    assert install.driver.expected_serial == SERIAL
    assert install.driver.run is fake
    assert probe.run is fake
    assert install.apk_provider is None


def test_rx_75_fixture_driver_still_injectable(tmp_path: Path) -> None:
    fixture = FixtureInstallDriver(installed=set())
    _, install = build_android_support_handlers(adb_path=ADB, serial=SERIAL, install_driver=fixture)
    assert install.driver is fixture

    body = b"fixture-flow"
    build = _build(_digest(body))
    handler = _handler(fixture, http_apk_provider(FakeClient(body), tmp_path / "s"), build)
    result = handler.handle(_claim(uuid4(), build))

    assert result.outcome == "completed"
    assert fixture.install_calls == 1 and PACKAGE in fixture.installed
    assert fixture.install(package=PACKAGE, digest="x", serial=SERIAL, approved=True, apk_path=None) == "installed"


def test_rx_75_runtime_no_longer_hardcodes_fixture_driver() -> None:
    source = (Path(__file__).parents[2] / "src" / "aiqa" / "worker" / "runtime.py").read_text(
        encoding="utf-8"
    )
    assert "FixtureInstallDriver" not in source
    assert "http_apk_provider" in source and "http_app_build_fetcher" in source
