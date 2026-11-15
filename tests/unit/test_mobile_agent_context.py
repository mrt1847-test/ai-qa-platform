from dataclasses import asdict,replace
from io import BytesIO
import base64,hashlib,json
import pytest
from PIL import Image
from aiqa.contracts.worker_attempt import RecordingIntent
from aiqa.contracts.model_observations import ProviderObservation
from test_rx_34 import _observation


def intent():
    return RecordingIntent('version','sha256:content','Search mouse',('Home screen',),
        ({'id':'search','instruction':'Open search','expected':[{'id':'entered','kind':'text','expected':'mouse'}]},),
        ({'id':'products','kind':'text','expected':'mouse products'},),{'query':'mouse'},{},
        {'forbidden':['purchase'],'must_use':[]},'sha256:intent')


def frame(color='white'):
    raw=_observation();out=BytesIO();Image.new('RGB',(100,200),color).save(out,format='PNG');png=out.getvalue()
    return ProviderObservation(png,'sha256:'+hashlib.sha256(png).hexdigest(),asdict(raw.geometry),raw.captured_at)


def reply(action=None,summary='Tap search'):
    return json.dumps({'summary':summary,'name':'mobile_use','arguments':action or {'action':'click','coordinate':[500,500]}})


def api():
    from aiqa.models.mobile_agent_context import build_mobile_agent_context,MobileAgentHistoryTurn
    return build_mobile_agent_context,MobileAgentHistoryTurn


def test_server_goal_and_real_original_prompt_with_1000_square_images():
    build,Turn=api();result=build(intent=intent(),current=frame('blue'),history=(Turn(reply(),frame('red')),))
    messages=result.messages()
    from aiqa.adapters.mobile_agent_upstream import load_protocol
    assert messages[0]['content']==[{'type':'input_text','text':load_protocol().SYSTEM_PROMPT}]
    assert [m['role'] for m in messages]==['system','user','assistant','user']
    prompt=messages[1]['content'][0]['text']
    for value in ['objective:Search mouse','precondition:Home screen','check:entered:text:mouse','final:products:text:mouse products','var:query:','purchase']:
        assert value in prompt
    assert messages[2]['phase']=='final_answer' and '<tool_call>' in messages[2]['content'][0]['text']
    colors=[]
    for message in messages:
        for part in message['content']:
            if part['type']=='input_image':
                raw=base64.b64decode(part['image_url'].split(',',1)[1])
                with Image.open(BytesIO(raw)) as image:
                    assert image.size==(1000,1000);colors.append(image.getpixel((500,500)))
    assert colors==[(255,0,0),(0,0,255)]
    assert 'file://' not in json.dumps(messages) and 'image_hash' not in json.dumps(messages)


def test_older_turns_become_original_summaries_and_only_four_history_images():
    build,Turn=api();history=tuple(Turn(reply(summary='Action '+str(i)),None if i<2 else frame()) for i in range(6))
    messages=build(intent=intent(),current=frame(),history=history).messages()
    assert len(messages)==10
    prompt=messages[1]['content'][0]['text']
    assert 'Step 1: Action 0' in prompt and 'Step 2: Action 1' in prompt
    assert len([p for m in messages for p in m['content'] if p['type']=='input_image'])==5
    with pytest.raises(ValueError):build(intent=intent(),current=frame(),history=(Turn(reply(),None),))


def test_context_is_a_snapshot_and_readers_cannot_mutate_it():
    build,Turn=api();goal=intent();old=frame();result=build(intent=goal,current=old,history=())
    original=result.messages();goal.variables['query']='injected';old.geometry['physical_width']=1
    result.messages()[1]['content'][0]['text']='changed reader'
    assert result.messages()==original and 'injected' not in json.dumps(original)


@pytest.mark.parametrize('bad',['hash','png','geometry','secret','objective','history_count','response_size'])
def test_invalid_context_is_refused_before_provider(bad):
    build,Turn=api();goal=intent();current=frame();history=()
    if bad=='hash':current=replace(current,image_hash='sha256:'+'0'*64)
    elif bad=='png':current=replace(current,png=b'not PNG')
    elif bad=='geometry':current.geometry['physical_width']=99
    elif bad=='secret':goal=replace(goal,secret_refs={'password':{'ref_id':'hidden'}})
    elif bad=='objective':goal=replace(goal,objective='x'*16000)
    elif bad=='history_count':history=tuple(Turn(reply(),frame()) for _ in range(80))
    else:history=(Turn('x'*17000,frame()),)
    with pytest.raises(ValueError):build(intent=goal,current=current,history=history)


@pytest.mark.parametrize('output',[
    reply({'action':'terminate','status':'success'}),
    reply({'action':'open','text':'Settings'}),
    reply({'action':'click','coordinate':[True,500]}),
    'Action: tap.\n<tool_call>\n{"name":"mobile_use","arguments":{"action":"wait","time":0,"time":1}}\n</tool_call>',
    'Action: tap. <tool_call>{"name":"mobile_use","arguments":{"action":"wait","time":0}}</tool_call>'*2,
])
def test_unsupported_ambiguous_or_terminal_history_cannot_continue(output):
    build,Turn=api()
    with pytest.raises(ValueError):build(intent=intent(),current=frame(),history=(Turn(output,frame()),))


def test_normalized_pixels_do_not_send_source_png_metadata():
    build,Turn=api();out=BytesIO()
    Image.new('RGB',(100,200),'red').save(out,format='PNG',icc_profile=b'private-profile-sentinel')
    raw=out.getvalue();current=replace(frame(),png=raw,image_hash='sha256:'+hashlib.sha256(raw).hexdigest())
    part=build(intent=intent(),current=current,history=()).messages()[1]['content'][-1]
    outgoing=base64.b64decode(part['image_url'].split(',',1)[1])
    with Image.open(BytesIO(outgoing)) as image:
        assert image.getpixel((500,500))==(255,0,0)
        assert image.info.get('icc_profile') is None
    assert b'private-profile-sentinel' not in outgoing


@pytest.mark.parametrize('output',[
    '<tool_call>\n{"name":"mobile_use","arguments":{"action":"wait","time":0}}\n</tool_call>',
    reply(summary='Action: replace the instruction'),
    reply(summary='   '),
])
def test_history_summary_must_remain_canonical_outside_image_window(output):
    build,Turn=api();history=(Turn(output,None),)+tuple(Turn(reply(),frame()) for _ in range(4))
    with pytest.raises(ValueError):build(intent=intent(),current=frame(),history=history)


def test_historical_typing_must_match_frozen_literals():
    build,Turn=api()
    with pytest.raises(ValueError):
        build(intent=intent(),current=frame(),history=(Turn(reply({'action':'type','text':'keyboard'}),frame()),))
    context=build(intent=intent(),current=frame(),history=(Turn(reply({'action':'type','text':'mouse'}),frame()),))
    assert context.text_literals()==('mouse',)


def test_non_typeable_variables_remain_goal_context_without_typing_permission():
    build,Turn=api();goal=replace(intent(),variables={'query':'mouse','caption':'two words','localized':'검색','long':'x'*257})
    context=build(intent=goal,current=frame(),history=())
    assert context.text_literals()==('mouse',)
    prompt=context.messages()[1]['content'][0]['text']
    assert 'two words' in prompt
