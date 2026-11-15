"""Bounded UTF-8 NDJSON used only by a parent worker and its own Mobile-Agent child."""
import json
MAX_PACKET=4*1024*1024


def _object(pairs):
    result={}
    for key,value in pairs:
        if key in result:raise ValueError('duplicate IPC field')
        result[key]=value
    return result


def read_packet(stream):
    raw=stream.readline(MAX_PACKET+1)
    if not raw:raise EOFError('IPC closed')
    if len(raw)>MAX_PACKET or not raw.endswith(b'\n'):raise ValueError('IPC packet too large or incomplete')
    try:data=json.loads(raw.decode('utf-8'),object_pairs_hook=_object)
    except (UnicodeError,json.JSONDecodeError,RecursionError):raise ValueError('IPC JSON invalid') from None
    if type(data) is not dict:raise ValueError('IPC object required')
    return data


def write_packet(stream,data):
    if type(data) is not dict:raise ValueError('IPC object required')
    raw=json.dumps(data,ensure_ascii=False,separators=(',',':'),allow_nan=False).encode('utf-8')+b'\n'
    if len(raw)>MAX_PACKET:raise ValueError('IPC packet too large')
    stream.write(raw);stream.flush()
