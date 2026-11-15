from types import SimpleNamespace
import pytest


@pytest.mark.parametrize('raw,want',[
 ({'input_tokens':100,'output_tokens':20,'cached_input_tokens':50,'reasoning_tokens':5},(100,20,50,5,120,'measured')),
 ({},(None,None,None,None,None,'unreported')),
 ({'input_tokens':100},(100,None,None,None,None,'unreported')),
 ({'input_tokens':False,'output_tokens':20,'cached_input_tokens':1,'reasoning_tokens':21},(None,20,None,None,None,'unreported')),
 ({'input_tokens':0,'output_tokens':0,'cached_input_tokens':0,'reasoning_tokens':0},(0,0,0,0,0,'measured')),
])
def test_measured_values_are_distinct_from_missing_and_reasoning_is_subset(raw,want):
    from aiqa.models.measurements import provider_measurements
    result=provider_measurements(SimpleNamespace(**raw))
    assert tuple(result[k] for k in ('input_tokens','output_tokens','cached_input_tokens','reasoning_tokens','total_tokens','measurement_status'))==want
