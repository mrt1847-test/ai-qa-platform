"""Observable recording decisions for a bounded manual model evaluation, not approval."""
from __future__ import annotations
from dataclasses import dataclass
import json,re
from aiqa.replay.android_plan import TypedAndroidAction


@dataclass(frozen=True,slots=True)
class RecordingDecision:
    screen: str
    progress: str
    action: str
    goal_status: str
    evidence: str


def _object(pairs):
    result={}
    for key,value in pairs:
        if key in result:raise ValueError('duplicate decision field')
        result[key]=value
    return result


def parse_decision(text):
    try:
        if type(text) is not str or len(text.encode('utf-8'))>8192:raise ValueError()
        raw=json.loads(text,object_pairs_hook=_object)
        if type(raw) is not dict or set(raw)!={'screen','progress','action','goal_status','evidence'}:raise ValueError()
        if any(type(v) is not str or not v.strip() or len(v.encode('utf-8'))>2048 for v in raw.values()):raise ValueError()
        if raw['goal_status'] not in {'in_progress','achieved','blocked'}:raise ValueError()
        if (raw['goal_status']=='in_progress')==(raw['action'].strip()=='finish()'):raise ValueError()
        return RecordingDecision(**raw)
    except (ValueError,TypeError,UnicodeError,RecursionError):
        raise ValueError('recording decision invalid') from None


def require_evaluation_action(action: TypedAndroidAction, *, foreground, package):
    """Only the selected app accepts coordinates; external/permission surfaces allow Back."""
    if type(foreground) is not str or not foreground:raise ValueError('foreground unavailable')
    if foreground!=package and action!=TypedAndroidAction('key',keycode=4):
        raise ValueError('external or permission surface: only Back is allowed')
    if action.kind=='text' and action.text!='mouse':raise ValueError('evaluation literal outside task')
    if action.kind=='key' and action.keycode not in {4,66}:raise ValueError('evaluation key outside task')
    if action.kind not in {'tap','swipe','text','key'}:raise ValueError('evaluation action unsupported')



def require_evaluation_target(serial,avd,package):
    if (type(serial) is not str or re.fullmatch(r'emulator-[0-9]{4,5}',serial) is None
        or not 1<=int(serial.split('-')[1])<=65535 or type(avd) is not str
        or re.fullmatch(r'[A-Za-z0-9_.-]{1,128}',avd) is None or package!='com.ebay.kr.gmarket'):
        raise ValueError('this manual task requires the named Gmarket emulator')


def require_current_frame(recorded,current,*,expected_foreground,current_foreground):
    if (recorded.geometry is None or current.geometry is None or recorded.geometry!=current.geometry
        or expected_foreground!=current_foreground):
        raise ValueError('evaluation frame or foreground changed before native send')
