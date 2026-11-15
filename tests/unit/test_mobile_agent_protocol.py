import sys,json
from pathlib import Path
from types import SimpleNamespace
import pytest


def test_pure_protocol_preserves_parent_absolute_imports_and_projection(monkeypatch):
    from aiqa.adapters.mobile_agent_upstream import load_protocol,upstream_action
    from aiqa.contracts.actions import CaptureGeometry
    marker=SimpleNamespace(parent_marker=True);monkeypatch.setitem(sys.modules,'utils',marker)
    cwd=Path.cwd();p=load_protocol()
    raw=p.parse_action('Action: Tap.\n<tool_call>\n{"name":"mobile_use","arguments":{"action":"click","coordinate":[500,750]}}\n</tool_call>')
    a=upstream_action(p,raw,CaptureGeometry(1080,2400,1080,2400,'identity',0,(0,0,1080,2400)))
    assert (a.x,a.y)==(540,1800) and Path.cwd()==cwd and sys.modules['utils'] is marker
    assert '# Tools' in p.SYSTEM_PROMPT


def test_packet_limits_reject_duplicate_keys_and_overflow():
    from io import BytesIO
    from aiqa.worker.mobile_agent_ipc import read_packet,write_packet,MAX_PACKET
    with pytest.raises(ValueError):read_packet(BytesIO(b'{"x":1,"x":2}\n'))
    with pytest.raises(ValueError):read_packet(BytesIO(b'x'*(MAX_PACKET+1)+b'\n'))
    stream=BytesIO();write_packet(stream,{'v':1,'value':'safe'});stream.seek(0)
    assert read_packet(stream)=={'v':1,'value':'safe'}


@pytest.mark.parametrize('tamper',['missing','changed_runner'])
def test_pure_protocol_rejects_unverified_source(tmp_path,tamper):
    import shutil
    from aiqa.adapters.mobile_agent_upstream import load_protocol
    root=tmp_path/'source'
    if tamper=='changed_runner':
        shutil.copytree('third_party/mobile_agent',root)
        with (root/'upstream/run_gui_owl_1_5_for_mobile.py').open('ab') as stream:stream.write(b'\n# changed')
    with pytest.raises(ValueError,match='protocol unavailable or changed'):load_protocol(root=root)


@pytest.mark.parametrize('loader_name',['load_protocol','load_upstream'])
def test_verified_source_ignores_a_mismatched_timestamp_cache(tmp_path,loader_name):
    import importlib._bootstrap_external as cache,shutil
    from aiqa.adapters import mobile_agent_upstream as module
    root=tmp_path/'source';shutil.copytree('third_party/mobile_agent',root)
    source=root/'upstream/utils.py'
    code=compile("raise RuntimeError('unverified cache executed')",str(source),'exec')
    destination=Path(cache.cache_from_source(str(source)));destination.parent.mkdir(exist_ok=True)
    destination.write_bytes(cache._code_to_timestamp_pyc(code,int(source.stat().st_mtime),source.stat().st_size))
    loaded=getattr(module,loader_name)(root=root)
    assert '# Tools' in loaded.SYSTEM_PROMPT


@pytest.mark.parametrize('loader_name',['load_protocol','load_upstream'])
def test_loader_executes_the_verified_buffer_not_a_later_reread(tmp_path,monkeypatch,loader_name):
    import shutil
    from aiqa.adapters import mobile_agent_upstream as module
    root=tmp_path/'source';shutil.copytree('third_party/mobile_agent',root)
    verify=module._source_root
    def change_after_verify(*args,**kwargs):
        verified=verify(*args,**kwargs)
        (root/'upstream/utils.py').write_text("raise RuntimeError('unverified reread executed')",encoding='utf-8')
        return verified
    monkeypatch.setattr(module,'_source_root',change_after_verify)
    loaded=getattr(module,loader_name)(root=root)
    assert '# Tools' in loaded.SYSTEM_PROMPT
