"""Tiny ISO BMFF envelopes for relay tests; not playable demo footage."""
import struct
def box(kind,body=b''):
    return struct.pack('>I4s',len(body)+8,kind)+body
INIT=box(b'ftyp',b'isom0000')+box(b'moov',box(b'avcC',b'\x01\x42\xc0\x1e'))
FRAME=box(b'moof',b'frame')+box(b'mdat',struct.pack('>I',2)+b'\x65\x88')
DELTA=box(b'moof',b'frame')+box(b'mdat',struct.pack('>I',2)+b'\x41\x88')
