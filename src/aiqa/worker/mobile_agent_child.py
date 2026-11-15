"""Own-process Mobile-Agent child. It has no credentials, provider port, ADB, or network."""
from __future__ import annotations
import base64,socket,sys
from pathlib import Path
from aiqa.worker.mobile_agent_ipc import read_packet,write_packet


def main():
    def forbidden(*args,**kwargs):raise RuntimeError('child networking forbidden')
    socket.socket.connect=forbidden;socket.create_connection=forbidden
    config=read_packet(sys.stdin.buffer)
    if set(config)!={'v','op','root','instruction','max_steps'} or config['v']!=1 or config['op']!='init':return 2
    root=Path(config['root']).resolve()
    if not (root/'.aiqa-mobile-agent').is_file():return 2
    sequence=0
    def rpc(op,payload):
        nonlocal sequence
        sequence+=1
        write_packet(sys.__stdout__.buffer,{'v':1,'id':sequence,'op':op,'payload':payload})
        result=read_packet(sys.__stdin__.buffer)
        if result.get('id')!=sequence or result.get('ok') is not True:raise RuntimeError('parent declined operation')
        return result['result']
    try:
        from aiqa.adapters.mobile_agent_upstream import load_upstream,run_upstream
        class IO:
            def get_screenshot(self,path):
                value=rpc('capture',{'path':path})
                p=root/'upstream'/path;p.parent.mkdir(parents=True,exist_ok=True)
                p.write_bytes(base64.b64decode(value['png'],validate=True));return True
            def click(self,x,y):rpc('native',{'method':'click','args':[x,y]})
            def long_press(self,x,y):rpc('native',{'method':'long_press','args':[x,y]})
            def slide(self,x,y,x2,y2):rpc('native',{'method':'slide','args':[x,y,x2,y2]})
            def type(self,text):rpc('native',{'method':'type','args':[text]})
            def back(self):rpc('native',{'method':'back','args':[]})
        def predict(messages):return rpc('model',{'messages':messages})['content']
        receipt=run_upstream(load_upstream(),io=IO(),predict=predict,output=root/'upstream',
            instruction=config['instruction'],max_steps=config['max_steps'])
        import os
        receipt.update(network_disabled=True,credential_environment_names=[name for name in os.environ if 'KEY' in name.upper() or 'TOKEN' in name.upper()])
        rpc('done',receipt)
        return 0
    except Exception as exc:
        try:rpc('error',{'error_type':type(exc).__name__})
        except Exception:pass
        return 1


if __name__=='__main__':raise SystemExit(main())
