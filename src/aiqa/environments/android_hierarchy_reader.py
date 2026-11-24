"""Shared explicit XML observation. No model, input gesture or remote evidence write."""
from dataclasses import dataclass,replace
from datetime import datetime,timezone
import math,re,subprocess,time
from aiqa.contracts.actions import CaptureGeometry
from aiqa.environments import android_observation as adb
from aiqa.environments.android_hierarchy import parse_android_hierarchy,validate_hierarchy_request,AndroidHierarchy
from aiqa.environments.android_hierarchy_xml import read_hierarchy_xml,AndroidHierarchyRejected,MAX_XML_BYTES

_SUFFIX=b'UI hierchary dumped to: /proc/self/fd/1'
_NOT_READY=frozenset((
    b'ERROR: null root node returned by UiTestAutomationBridge.',
    b'ERROR: could not get idle state.',
))
_TRANSIENT_OBSERVATION=frozenset({'geometry_unavailable','boot_incomplete','adb_read_failed','observation_timeout','capture_failed','capture_invalid','capture_unavailable'})


def _observation_reason(reason):
    return reason if reason in _TRANSIENT_OBSERVATION else 'target_unavailable'


class AndroidHierarchyReadError(ValueError):pass
class _Failure(Exception):pass


@dataclass(frozen=True,slots=True)
class AndroidHierarchyObservation:
    snapshot:AndroidHierarchy
    geometry:CaptureGeometry
    captured_at:str
    foreground:str


class AndroidHierarchyReader:
    def __init__(self,observer,*,package,checkpoint,extra_packages=(),command_timeout=15,total_timeout=30):
        if not isinstance(observer,adb.AndroidObservationProvider) or not callable(checkpoint):raise ValueError('explicit observer and checkpoint required')
        validate_hierarchy_request(package,())
        if type(extra_packages) is not tuple:raise ValueError('explicit packages required')
        for value in extra_packages:validate_hierarchy_request(value,())
        for value in (command_timeout,total_timeout):
            if type(value) not in (int,float) or not math.isfinite(value) or not 0<value<=90:raise ValueError('finite read deadlines required')
        self._identity=(str(observer.adb_path),observer.serial,observer.expected_avd)
        self.observer,self.package,self.checkpoint=observer,package,checkpoint
        self.packages=frozenset((package,*extra_packages));self.command_timeout,self.total_timeout=command_timeout,total_timeout

    def _check(self,deadline):
        try:allowed=self.checkpoint() is True
        except Exception:allowed=False
        if (str(self.observer.adb_path),self.observer.serial,self.observer.expected_avd)!=self._identity:raise _Failure('target_changed')
        if not allowed:raise _Failure('observation_not_allowed')
        if time.monotonic()>=deadline:raise _Failure('observation_timeout')
        return True

    def _collect(self,capture):
        deadline=time.monotonic()+self.total_timeout;self._check(deadline)
        observer=self.observer;gate=lambda:self._check(deadline)
        def run(*command,failure_reason='adb_read_failed'):
            self._check(deadline)
            result=adb._run_bounded([self._identity[0],'-s',self._identity[1],*command],timeout=min(self.command_timeout,deadline-time.monotonic()))
            self._check(deadline)
            if result.returncode:raise _Failure(failure_reason)
            return result.stdout
        def focus():
            raw=run('shell','dumpsys','window',failure_reason='foreground_unavailable')
            names=re.findall(r'mCurrentFocus=Window\{[^\r\n]*?\bu[0-9]+[ \t]+([A-Za-z0-9_.$]+)/[A-Za-z0-9_.$]+',raw.decode('utf-8'))
            if len(names)!=1:raise _Failure('foreground_unavailable')
            return names[0]
        before=observer.observe(capture=False,deadline=deadline,checkpoint=gate,command_timeout=self.command_timeout)
        if before.state!='ready' or before.geometry is None:raise _Failure(_observation_reason(before.reason))
        first=focus()
        if first not in self.packages:raise _Failure('foreground_outside_target')
        raw=run('exec-out','uiautomator','dump','/proc/self/fd/1',failure_reason='hierarchy_transition')
        if len(raw)>MAX_XML_BYTES+len(_SUFFIX)+4:raise _Failure('hierarchy_invalid')
        if raw.endswith(b'\r\n'):raw=raw[:-2]
        elif raw.endswith(b'\n'):raw=raw[:-1]
        if raw in {b'',_SUFFIX} or raw in _NOT_READY:raise _Failure('hierarchy_transition')
        if not raw.endswith(_SUFFIX):raise _Failure('hierarchy_invalid')
        xml=raw[:-len(_SUFFIX)]
        if xml.endswith(b'\r\n'):xml=xml[:-2]
        elif xml.endswith(b'\n'):xml=xml[:-1]
        read_hierarchy_xml(xml,rotation=before.geometry.rotation)
        captured=datetime.now(timezone.utc).isoformat()
        after=observer.observe(capture=capture,deadline=deadline,checkpoint=gate,command_timeout=self.command_timeout)
        if after.state!='ready' or after.geometry is None:raise _Failure(_observation_reason(after.reason))
        if (before.geometry,before.density)!=(after.geometry,after.density):raise _Failure('geometry_changed')
        if focus()!=first:raise _Failure('foreground_changed')
        self._check(deadline)
        if capture and (after.observation is None or not after.observation.capture_ok):raise _Failure('capture_unavailable')
        return xml,after,first,captured,deadline

    def _safe_project(self,capture,resources=()):
        reason='hierarchy_unavailable'
        try:return self._project(capture,resources)
        except _Failure as exc:reason=str(exc)
        except AndroidHierarchyRejected:reason='hierarchy_invalid'
        except adb._ReadFailure as exc:reason=exc.reason or reason
        except (subprocess.TimeoutExpired,OSError):reason='hierarchy_transition'
        except (UnicodeError,ValueError):reason='hierarchy_invalid'
        raise AndroidHierarchyReadError(reason)

    def _project(self,capture,resources):
        xml,after,foreground,captured,deadline=self._collect(capture)
        if capture:result=(replace(after.observation,dom=xml.decode('utf-8')),foreground)
        else:
            facts=parse_android_hierarchy(xml,package=self.package,resource_ids=resources,rotation=after.geometry.rotation)
            result=AndroidHierarchyObservation(facts,after.geometry,captured,foreground)
        self._check(deadline)
        return result

    def capture_once(self):
        """Legacy evaluation capture: local raw DOM, caller must sanitize before use."""
        return self._safe_project(True)

    def observe_targets(self,resource_ids):
        """Check-time observation only; no screenshot/model or assertion verdict."""
        resources=validate_hierarchy_request(self.package,resource_ids)
        return self._safe_project(False,resources)
