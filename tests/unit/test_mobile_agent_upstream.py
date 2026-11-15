import json,subprocess
from pathlib import Path
import pytest
from test_rx_34 import _observation
from aiqa.contracts.actions import CaptureGeometry


def engine():
    from aiqa.adapters.mobile_agent_upstream import load_upstream,run_upstream,upstream_action
    return load_upstream,run_upstream,upstream_action


def test_real_upstream_main_builds_history_and_dispatches(tmp_path):
    load,run,convert=engine();u=load();seen=[];sent=[]
    class IO:
        def get_screenshot(self,path):Path(path).write_bytes(_observation().png);return True
        def click(self,x,y):sent.append((x,y))
    outputs=['Action: Tap search.\n<tool_call>\n{"name":"mobile_use","arguments":{"action":"click","coordinate":[500,500]}}\n</tool_call>',
             'Action: Done.\n<tool_call>\n{"name":"mobile_use","arguments":{"action":"terminate","status":"success"}}\n</tool_call>']
    def model(messages):seen.append(messages);return outputs[len(seen)-1]
    receipt=run(u,io=IO(),predict=model,output=tmp_path/'new',instruction='Find mouse',max_steps=3,sleep=lambda _:None)
    assert len(seen)==2 and len(sent)==1
    assert 'run_gui_owl_1_5_for_mobile.py' in receipt['main_file']
    assert receipt['upstream_commit']=='81fa28b564ef7a695521500bc15a0e1324b2b394'
    assert seen[0][0]['content'][0]['text']==u.SYSTEM_PROMPT
    assert seen[1][2]['role']=='assistant' and seen[1][2]['content'][0]['text']==outputs[0]
    assert receipt['main_invocations']==1


def test_normalized_upstream_coordinates_become_physical_once():
    load,_,convert=engine();u=load()
    geo=CaptureGeometry(1080,2400,1080,2400,'identity',0,(0,0,1080,2400))
    raw={'name':'mobile_use','arguments':{'action':'click','coordinate':[500,750]}}
    a=convert(u,raw,geo)
    assert (a.x,a.y)==(540,1800)
    assert raw['arguments']['coordinate']==[500,750]


@pytest.mark.parametrize('args',[{'action':'system_button','button':'Home'},{'action':'open','text':'Settings'},{'action':'key','text':'26'},{'action':'click','coordinate':[True,3]},{'action':'click','coordinate':[1001,2]}])
def test_unsupported_or_invalid_action_stops_before_native(args):
    load,_,convert=engine()
    with pytest.raises(ValueError):convert(load(),{'name':'mobile_use','arguments':args},_observation().geometry)


def test_source_tampering_prevents_import(tmp_path):
    load,_,_=engine()
    with pytest.raises(ValueError):load(root=tmp_path)


def test_manifest_cannot_drop_an_imported_source(tmp_path):
    import shutil
    load,_,_=engine();root=Path('third_party/mobile_agent');shutil.copytree(root,tmp_path/'copy')
    manifest=tmp_path/'copy/manifest.json';raw=json.loads(manifest.read_text());raw['files'].pop('utils.py');manifest.write_text(json.dumps(raw))
    with pytest.raises(ValueError):load(root=tmp_path/'copy')


def test_structured_luna_action_renders_for_original_parser():
    from aiqa.adapters.mobile_agent_upstream import render_reply
    load,_,_=engine();u=load()
    raw={'summary':'Tap search','name':'mobile_use','arguments':{'action':'click','coordinate':[440,57]}}
    text=render_reply(json.dumps(raw))
    assert u.parse_action(text)=={'name':'mobile_use','arguments':raw['arguments']}
    with pytest.raises(ValueError):render_reply(json.dumps(raw)+json.dumps(raw))
