"""Selected native hierarchy facts remain bounded, private and inconclusive when absent."""
from dataclasses import FrozenInstanceError
from xml.sax.saxutils import quoteattr
import pytest

PACKAGE='com.example.app'
RESOURCE=PACKAGE+':id/query'


def node(*,resource=RESOURCE,package=PACKAGE,text='Ready & <safe>',**attrs):
    values={'resource-id':resource,'package':package,'text':text,'password':'false',
            'enabled':'true','checked':'false','selected':'false','focused':'false',**attrs}
    return '<node '+ ' '.join(k+'='+quoteattr(v) for k,v in values.items() if v is not None)+'/>'


def xml(*nodes,rotation='0'):
    return ('<?xml version="1.0" encoding="UTF-8"?><hierarchy rotation="'+rotation+'">'+''.join(nodes)+'</hierarchy>').encode('utf-8')


def parse(raw=None,**changes):
    from aiqa.environments.android_hierarchy import parse_android_hierarchy
    return parse_android_hierarchy(xml(node()) if raw is None else raw,**{'package':PACKAGE,'resource_ids':(RESOURCE,), 'rotation':0,**changes})


def test_explicit_target_facts_are_frozen_without_inventing_visibility_or_value():
    result=parse();target=result.targets[0]
    assert result.rotation==0 and target.resource_id==RESOURCE and target.status=='available'
    assert target.text=='Ready & <safe>' and target.enabled is True and target.checked is False
    assert target.visible is None and not hasattr(target,'value')
    assert 'Ready' not in repr(result)
    with pytest.raises((FrozenInstanceError,AttributeError)):target.text='changed'


def test_nested_unicode_and_selected_package_are_read_without_copying_other_content():
    parent='<node package="'+PACKAGE+'">'+node(text='안녕하세요')+node(resource=PACKAGE+':id/private',text='UNSELECTED_CANARY')+'</node>'
    raw=xml(parent,node(package='other.app',text='FOREIGN_CANARY'))
    result=parse(raw);assert result.targets[0].text=='안녕하세요'
    assert len(result.targets)==1 and 'CANARY' not in repr(result)


@pytest.mark.parametrize('nodes,status',[((), 'missing'),((node(),node()),'ambiguous'),
    ((node(package='other.app'),),'missing'),((node(password='true',text='PASSWORD_CANARY'),),'redacted'),
    ((node(password=None),),'unavailable'),((node(password='False'),),'unavailable'),
    ((node(enabled='yes'),),'unavailable'),((node(text='x'*4097),),'unavailable')])
def test_ambiguous_missing_or_private_target_never_becomes_available(nodes,status):
    target=parse(xml(*nodes)).targets[0]
    assert target.status==status and target.text is None and target.enabled is None and target.visible is None
    assert 'CANARY' not in repr(target)


def test_duplicate_requests_are_deduplicated_without_hiding_duplicate_device_nodes():
    assert len(parse(resource_ids=(RESOURCE,RESOURCE)).targets)==1
    assert parse(xml(node(),node()),resource_ids=(RESOURCE,RESOURCE)).targets[0].status=='ambiguous'


def test_only_explicit_boolean_flags_are_returned():
    target=parse(xml(node(**{'visible-to-user':'true','focused':'true','selected':None,'checked':None}))).targets[0]
    assert target.visible is True and target.focused is True and target.checked is None and target.selected is None


@pytest.mark.parametrize('rotation',['0','1','2','3'])
def test_xml_quarter_turn_matches_exact_requested_degrees(rotation):
    assert parse(xml(node(),rotation=rotation),rotation=int(rotation)*90).rotation==int(rotation)*90


@pytest.mark.parametrize('raw',[b'',b'\xff',b'<hierarchy rotation="0">',b'<other rotation="0"/>',
    xml(node(),rotation='1'),xml(node(),rotation='01'),xml('<unexpected/>'),
    b'<hierarchy rotation="0"/><hierarchy rotation="0"/>',
    b'<!DOCTYPE hierarchy [<!ENTITY secret SYSTEM "file:///CANARY">]><hierarchy rotation="0"/>',
    b'<!DOCTYPE hierarchy [<!ENTITY a "aaaa">]><hierarchy rotation="0">&a;</hierarchy>',
    b'x'*(1048576+1),('<hierarchy rotation="0">'+'<node>'*65+'</node>'*65+'</hierarchy>').encode(),
    xml(*['<node/>' for _ in range(4097)])])
def test_invalid_or_excessive_xml_has_a_fixed_nonsensitive_error(raw):
    from aiqa.environments.android_hierarchy import AndroidHierarchyRejected
    with pytest.raises(AndroidHierarchyRejected) as raised:parse(raw)
    assert str(raised.value)=='hierarchy_invalid' and 'CANARY' not in repr(raised.value)


@pytest.mark.parametrize('changes',[{'package':'com.example.app;cmd'}, {'package':'-package'},
    {'resource_ids':('other.app:id/query',)}, {'resource_ids':[RESOURCE]},
    {'resource_ids':(RESOURCE,)*257},{'rotation':True},{'rotation':45}])
def test_target_and_rotation_input_are_explicit(changes):
    from aiqa.environments.android_hierarchy import AndroidHierarchyRejected
    with pytest.raises(AndroidHierarchyRejected):parse(**changes)


@pytest.mark.parametrize('declaration',['encoding="utf-16"','encoding = "UTF-16"','encoding="iso-8859-1"'])
def test_conflicting_xml_encoding_is_not_used_to_reinterpret_utf8_bytes(declaration):
    from aiqa.environments.android_hierarchy import AndroidHierarchyRejected
    raw=('<?xml version="1.0" '+declaration+'?>'+xml(node(text='한글')).decode().split('?>',1)[1]).encode('utf-8')
    with pytest.raises(AndroidHierarchyRejected):parse(raw)


def test_exact_limits_and_utf8_text_budget_keep_valid_observations():
    assert parse(xml(*(['<node/>']*4095+[node()]))).targets[0].status=='available'
    nested='<node>'*62+node()+'</node>'*62
    assert parse(xml(nested)).targets[0].status=='available'
    assert parse(xml(node(text='한'*1365))).targets[0].status=='available'
    assert parse(xml(node(text='한'*1366))).targets[0].status=='unavailable'


def test_xml_cannot_resolve_external_entities_or_open_files(monkeypatch):
    from aiqa.environments.android_hierarchy import AndroidHierarchyRejected
    import builtins
    opened=[]
    def open_file(*args,**kwargs):opened.append(1);raise AssertionError('unexpected file IO')
    monkeypatch.setattr(builtins,'open',open_file)
    with pytest.raises(AndroidHierarchyRejected):parse(b'<!DOCTYPE hierarchy SYSTEM "file:///PRIVATE_CANARY"><hierarchy rotation="0"/>')
    assert opened==[]


@pytest.mark.parametrize('encoding',['utf-16-le','utf-16-be','utf-32-le','utf-32-be'])
def test_bomless_non_utf8_xml_cannot_bypass_the_encoding_guard(encoding):
    from aiqa.environments.android_hierarchy import AndroidHierarchyRejected
    with pytest.raises(AndroidHierarchyRejected):parse('<hierarchy rotation="0"/>'.encode(encoding))


def test_rejected_input_is_not_retained_on_the_public_decoder_exception():
    from aiqa.environments.android_hierarchy import AndroidHierarchyRejected,parse_android_hierarchy
    raw=b'<hierarchy rotation="0"/>'+b'PRIVATE_INPUT_CANARY'+b'\xff'
    with pytest.raises(AndroidHierarchyRejected) as raised:parse_android_hierarchy(raw,package=PACKAGE,resource_ids=(RESOURCE,),rotation=0)
    assert raised.value.__context__ is None
    frame=raised.value.__traceback__
    while frame:
        if frame.tb_frame.f_code.co_name=='parse_android_hierarchy':assert 'raw' not in frame.tb_frame.f_locals
        frame=frame.tb_next
