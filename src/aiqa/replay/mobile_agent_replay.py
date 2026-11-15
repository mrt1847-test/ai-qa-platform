"""Replay pinned physical actions and their visible reference frames; never calls a model."""
from __future__ import annotations
import hashlib,json,time
from pathlib import Path
from aiqa.adapters.mobile_agent_android import MobileAgentAndroidAdapter
from aiqa.recording.mobile_agent_session import persist
from aiqa.recording.mobile_agent_frames import require_guarded_frame
from aiqa.replay.android_native_trace import parse_native_trace
from aiqa.worker.recording_reasoning import require_evaluation_action,require_current_frame


def load_replay_reference(source,expected_hash,pin_path,pin_hash,target):
    source,pin_path=Path(source),Path(pin_path)
    if source.stat().st_size>1_000_000:raise ValueError('replay source too large')
    raw=source.read_bytes()
    if hashlib.sha256(raw).hexdigest()!=expected_hash:raise ValueError('replay source changed')
    if pin_path.stat().st_size>65536:raise ValueError('replay pin too large')
    pin_raw=pin_path.read_bytes()
    if hashlib.sha256(raw).hexdigest()!=expected_hash or hashlib.sha256(pin_raw).hexdigest()!=pin_hash:raise ValueError('replay source changed')
    steps=parse_native_trace(raw.decode('utf-8'));pin=json.loads(pin_raw)
    if (type(pin) is not dict or set(pin)!={'schema','target','complete','source_sha256','steps'}
        or pin['schema']!='mobile-agent-recording-pin-v1' or pin['complete'] is not True
        or pin['source_sha256']!=expected_hash or pin['target']!=target
        or len(steps)>10 or len(pin['steps'])!=len(steps)):raise ValueError('recording pin incomplete or target differs')
    references=[]
    for index,(step,row) in enumerate(zip(steps,pin['steps'],strict=True),1):
        stem=f'step-{index:03d}'
        if (step.action_id!=stem or type(row) is not dict or set(row)!={'action_id','before_image','before_sha256','foreground','before_hierarchy_sha256'}
            or row['action_id']!=stem or row['before_image']!=stem+'-before.png'
            or row['foreground'] not in {target['package'],'com.google.android.permissioncontroller'}):raise ValueError('recording reference invalid')
        image=pin_path.parent/row['before_image']
        if image.stat().st_size>2_000_000:raise ValueError('recording reference too large')
        image_bytes=image.read_bytes()
        if hashlib.sha256(image_bytes).hexdigest()!=row['before_sha256']:raise ValueError('recording frame changed')
        hierarchy_path=pin_path.parent/(stem+'-before.xml')
        if hierarchy_path.stat().st_size>1_000_000:raise ValueError('hierarchy too large')
        hierarchy=hierarchy_path.read_bytes()
        if hashlib.sha256(hierarchy).hexdigest()!=row['before_hierarchy_sha256']:raise ValueError('hierarchy changed')
        references.append((image_bytes,row['foreground'],hierarchy.decode('utf-8')))
    return steps,tuple(references)


def replay_saved_trace(*,source,expected_hash,pin_path,pin_hash,target,capture,driver,output,package,sleep=time.sleep):
    steps,references=load_replay_reference(source,expected_hash,pin_path,pin_hash,target)
    if target['serial']!=driver.serial or target['package']!=package:raise ValueError('replay target differs')
    output=Path(output);output.mkdir(parents=True,exist_ok=False)
    report={'source_sha256':expected_hash,'recording_pin_sha256':pin_hash,'target':target,'model_calls':0,'healing':'OFF',
            'human_review':'pending','product_approval':False,'status':'replaying','steps':[]}
    deadline=time.monotonic()+240;adapter=MobileAgentAndroidAdapter()
    try:
        for index,(step,(reference,expected_foreground,reference_hierarchy)) in enumerate(zip(steps,references,strict=True),1):
            if time.monotonic()>=deadline:raise RuntimeError('replay deadline')
            before,foreground=capture();before=adapter.sanitize(before);geo=before.geometry
            stem=f'step-{index:03d}';persist(output/(stem+'-before.png'),before.png)
            persist(output/(stem+'-reference.png'),reference)
            if foreground!=expected_foreground or (geo.physical_width,geo.physical_height,geo.rotation)!=(step.width,step.height,step.rotation):raise ValueError('replay frame identity changed')
            require_evaluation_action(step.action,foreground=foreground,package=package)
            frame_guard=require_guarded_frame(reference,before.png,step.action,reference_hierarchy,before.dom)
            row={'action_id':step.action_id,'state':'planned','before_image':stem+'-before.png','frame_guard':frame_guard}
            report['steps'].append(row);persist(output/'report.json',report)
            def fence():
                if time.monotonic()>=deadline:raise RuntimeError('replay deadline')
                current,focus=capture();require_current_frame(before,current,expected_foreground=foreground,current_foreground=focus)
                require_evaluation_action(step.action,foreground=focus,package=package)
                try:require_guarded_frame(reference,current.png,step.action,reference_hierarchy,current.dom)
                except ValueError:
                    persist(output/(stem+'-drift-current.png'),current.png)
                    raise
                if time.monotonic()>=deadline:raise RuntimeError('replay deadline')
                row['state']='dispatch_started';persist(output/'report.json',report)
                if time.monotonic()>=deadline:raise RuntimeError('replay deadline')
            result=adapter._dispatch(driver,before,before,step.action,before_native_send=fence)
            if result.native_calls!=1 or result.outcome!='acknowledged':raise RuntimeError('replay unacknowledged')
            row.update(state='acknowledged_after_missing',argv=list(result.argv));persist(output/'report.json',report)
            after,_=capture();after=adapter.sanitize(after);persist(output/(stem+'-after.png'),after.png)
            row.update(state='observed',after_image=stem+'-after.png');persist(output/'report.json',report)
            sleep(2)
        final,_=capture();persist(output/'terminal.png',adapter.sanitize(final).png)
        report['status']='replayed_pending_observation'
        return report
    except Exception as exc:
        report.update(status='stopped',error_type=type(exc).__name__,reason=getattr(exc,'reason','replay_failed'))
        raise
    finally:persist(output/'report.json',report)
