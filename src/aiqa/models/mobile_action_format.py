"""Single upstream action schema, keeping original Mobile-Agent tool names and arguments."""
def obj(properties):return {'type':'object','properties':properties,'required':list(properties),'additionalProperties':False}
def enum(*values):return {'type':'string','enum':list(values)}
point={'type':'array','items':{'type':'number','minimum':0,'maximum':1000},'minItems':2,'maxItems':2}
variants=[]
for name,properties in (
    ('click',{'coordinate':point}),('long_press',{'coordinate':point}),
    ('swipe',{'coordinate':point,'coordinate2':point}),('type',{'text':enum('mouse')}),
    ('system_button',{'button':enum('Back')}),('wait',{'time':{'type':'number','minimum':0,'maximum':2}}),
    ('terminate',{'status':enum('success','failure')})):
    variants.append(obj({'action':enum(name),**properties}))
MOBILE_ACTION_FORMAT={'type':'json_schema','name':'mobile_agent_one_action','strict':True,
    'schema':obj({'summary':{'type':'string'},'name':enum('mobile_use'),'arguments':{'anyOf':variants}})}


def mobile_action_format_for(text_literals):
    """Keep typing confined to explicit frozen nonsecret input literals."""
    from copy import deepcopy
    if (type(text_literals) is not tuple or len(text_literals)>32
        or any(not is_native_text_literal(value) for value in text_literals)):
        raise ValueError('mobile text literals invalid')
    result=deepcopy(MOBILE_ACTION_FORMAT)
    choices=result['schema']['properties']['arguments']['anyOf']
    if not text_literals:
        choices[:]=[choice for choice in choices if choice['properties']['action']['enum']!=['type']]
    else:
        choice=next(choice for choice in choices if choice['properties']['action']['enum']==['type'])
        choice['properties']['text']=enum(*dict.fromkeys(text_literals))
    return result


def is_native_text_literal(value):
    from aiqa.replay.android_plan import build_typed_android_action,PlanRejected
    try:build_typed_android_action('text',width=1,height=1,rotation=0,text=value)
    except PlanRejected:return False
    return True
