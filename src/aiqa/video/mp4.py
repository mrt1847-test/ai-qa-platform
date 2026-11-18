"""Inspect a complete AVC fragmented-MP4 chunk without decoding pixels."""
import struct

def starts_keyframe(data:bytes)->bool:
    offset=0
    while offset+8<=len(data):
        size,kind=struct.unpack_from('>I4s',data,offset)
        if size<8 or offset+size>len(data):return False
        if kind==b'mdat':
            end=offset+size;cursor=offset+8
            while cursor+4<=end:
                length=struct.unpack_from('>I',data,cursor)[0];cursor+=4
                if not length or cursor+length>end:return False
                nal=data[cursor]&31
                if nal in {1,5}:return nal==5
                cursor+=length
            return False
        offset+=size
    return False
