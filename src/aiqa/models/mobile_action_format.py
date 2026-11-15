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
