"""Bounded raw local XML for hierarchy consumers. This tree is not sanitized evidence."""
import re
from xml.etree import ElementTree as ET

MAX_XML_BYTES=1048576
MAX_NODES=4096
MAX_DEPTH=64


class AndroidHierarchyRejected(ValueError):pass


def read_hierarchy_xml(raw:bytes,*,rotation:int|None=None):
    try:return _read(raw,rotation)
    except (ValueError,TypeError,UnicodeError,ET.ParseError,RecursionError):pass
    del raw,rotation
    raise AndroidHierarchyRejected('hierarchy_invalid')


def _read(raw,rotation):
    if type(raw) is not bytes or not 0<len(raw)<=MAX_XML_BYTES:raise ValueError()
    if rotation is not None and (type(rotation) is not int or rotation not in {0,90,180,270}):raise ValueError()
    text=raw.decode('utf-8')
    if '\x00' in text or re.search(r'<!\s*(?:DOCTYPE|ENTITY)\b',text,re.IGNORECASE):raise ValueError()
    declaration=re.match(r'^\ufeff?\s*<\?xml\s+[^?]*?encoding\s*=\s*[\"\']([^\"\']+)',text)
    if declaration and declaration[1].lower() not in {'utf-8','utf8'}:raise ValueError()
    parser=ET.XMLPullParser(events=('start','end'));root=None;depth=nodes=0
    def consume():
        nonlocal root,depth,nodes
        for event,element in parser.read_events():
            if event=='end':depth-=1;continue
            depth+=1
            if depth>MAX_DEPTH:raise ValueError()
            if depth==1:
                if root is not None or element.tag!='hierarchy':raise ValueError()
                root=element;turn=element.attrib.get('rotation')
                if turn not in {'0','1','2','3'} or (rotation is not None and int(turn)*90!=rotation):raise ValueError()
            else:
                nodes+=1
                if element.tag!='node' or nodes>MAX_NODES:raise ValueError()
    for start in range(0,len(text),8192):parser.feed(text[start:start+8192]);consume()
    parser.close();consume()
    if root is None or depth!=0:raise ValueError()
    return root
