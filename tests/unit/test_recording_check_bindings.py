import copy
import pytest
from aiqa.recording.check_bindings import validate_bindings,BindingRejected

DEF={'steps':[{'id':'s1','instruction':'search','expected':[{'id':'c1','kind':'text','expected':'mouse'}]},
    {'id':'s2','instruction':'results','expected':[]}],'final_expected':[{'id':'final','kind':'state','expected':'visible'}]}
SETTINGS={'target_kind':'android','android_package':'com.example.app'}
ACTIONS=('a1','a2','a3')
PAYLOAD={'step_boundaries':[{'step_id':'s1','after_action_id':'a2'},{'step_id':'s2','after_action_id':'a3'}],
    'check_targets':[{'check_id':'c1','resource_id':'com.example.app:id/query'}]}


def test_source_step_and_native_boundary_are_explicit_and_detached():
    payload=copy.deepcopy(PAYLOAD)
    result=validate_bindings(payload,definition=DEF,settings=SETTINGS,action_ids=ACTIONS)
    payload['step_boundaries'][0]['after_action_id']='a1'
    assert result.to_document()==PAYLOAD


@pytest.mark.parametrize('damage',['extra','unknown_step','unknown_action','unknown_check','duplicate_step','duplicate_check','reverse','foreign_package','shell'])
def test_invalid_or_reordered_bindings_are_rejected(damage):
    raw=copy.deepcopy(PAYLOAD)
    if damage=='extra':raw['expected']='invented pass'
    elif damage=='unknown_step':raw['step_boundaries'][0]['step_id']='missing'
    elif damage=='unknown_action':raw['step_boundaries'][0]['after_action_id']='missing'
    elif damage=='unknown_check':raw['check_targets'][0]['check_id']='missing'
    elif damage=='duplicate_step':raw['step_boundaries'].append(raw['step_boundaries'][0])
    elif damage=='duplicate_check':raw['check_targets'].append(raw['check_targets'][0])
    elif damage=='reverse':raw['step_boundaries'][0]['after_action_id']='a3';raw['step_boundaries'][1]['after_action_id']='a1'
    elif damage=='foreign_package':raw['check_targets'][0]['resource_id']='other.app:id/query'
    else:raw['check_targets'][0]['resource_id']='com.example.app:id/query;reboot'
    with pytest.raises(BindingRejected):validate_bindings(raw,definition=DEF,settings=SETTINGS,action_ids=ACTIONS)


def test_partial_mapping_and_shared_native_boundary_are_supported():
    raw={'step_boundaries':[{'step_id':'s1','after_action_id':'a3'},{'step_id':'s2','after_action_id':'a3'}],'check_targets':[]}
    assert validate_bindings(raw,definition=DEF,settings=SETTINGS,action_ids=ACTIONS).to_document()==raw
