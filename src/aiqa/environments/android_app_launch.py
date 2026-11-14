"""One bounded MAIN/LAUNCHER command for a frozen selected package."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path, PureWindowsPath
import math
import re
import subprocess

_PACKAGE = re.compile(r'[A-Za-z][A-Za-z0-9_]*(?:\.[A-Za-z][A-Za-z0-9_]*)+')
_SERIAL = re.compile(r'[A-Za-z0-9][A-Za-z0-9._:-]{0,127}')


class AppLaunchRejected(ValueError):
    pass


class AppLaunchUnknown(RuntimeError):
    """A command may have reached the device. Never automatically start it again."""


@dataclass(frozen=True, slots=True)
class AppLaunchReceipt:
    package: str
    activity: str


class AndroidAppLauncher:
    def __init__(self, adb_path, serial, *, run=None, timeout=20.0):
        path=Path(adb_path)
        if path.name.lower() not in {'adb','adb.exe'} or not (path.is_absolute() or PureWindowsPath(str(path)).is_absolute()):
            raise AppLaunchRejected('absolute ADB path required')
        if type(serial) is not str or _SERIAL.fullmatch(serial) is None:
            raise AppLaunchRejected('registered serial required')
        if type(timeout) not in (int,float) or not math.isfinite(timeout) or not 0<timeout<=30:
            raise AppLaunchRejected('launch deadline invalid')
        self.adb_path,self.serial,self.timeout=path,serial,float(timeout)
        self.run=run or _run
        self.native_calls=0

    def launch(self, package, *, before_native_send):
        if type(package) is not str or len(package)>255 or _PACKAGE.fullmatch(package) is None:
            raise AppLaunchRejected('selected package invalid')
        if not callable(before_native_send):
            raise AppLaunchRejected('native fence required')
        argv=(str(self.adb_path),'-s',self.serial,'shell','am','start','-W',
              '-a','android.intent.action.MAIN','-c','android.intent.category.LAUNCHER',package)
        before_native_send()
        self.native_calls+=1
        try:
            result=self.run(argv,self.timeout)
        except (OSError,subprocess.TimeoutExpired) as exc:
            raise AppLaunchUnknown('app launch outcome unavailable') from exc
        text=result.stdout.decode('utf-8',errors='replace') if isinstance(result.stdout,bytes) else str(result.stdout)
        text=text.replace('\r\n','\n')
        statuses=re.findall(r'(?m)^Status:[ \t]*(\w+)[ \t]*$',text)
        activities=re.findall(r'(?m)^Activity:[ \t]*([A-Za-z0-9_.$]+/[A-Za-z0-9_.$]+)[ \t]*$',text)
        if result.returncode!=0 or statuses!=['ok'] or len(activities)!=1 or activities[0].split('/')[0]!=package:
            raise AppLaunchUnknown('selected app launch was not confirmed')
        try:
            window=self.run((str(self.adb_path),'-s',self.serial,'shell','dumpsys','window'),min(self.timeout,10.0))
        except (OSError,subprocess.TimeoutExpired) as exc:
            raise AppLaunchUnknown('foreground confirmation unavailable') from exc
        text=window.stdout.decode('utf-8',errors='replace') if isinstance(window.stdout,bytes) else str(window.stdout)
        focused=re.findall(r'(?m)mCurrentFocus=Window\{[^\r\n]*?\bu[0-9]+[ \t]+([A-Za-z0-9_.$]+)/[A-Za-z0-9_.$]+',text)
        if window.returncode!=0 or focused!=[package]:
            raise AppLaunchUnknown('selected app is not the visible foreground')
        return AppLaunchReceipt(package,activities[0])


def _run(argv, timeout):
    from aiqa.environments.android_observation import _run_bounded
    return _run_bounded(list(argv),timeout=timeout)
