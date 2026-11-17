"""Pure selected-target facts from native XML. Raw values remain local, never QA or sanitized evidence."""
from dataclasses import dataclass,field
import re
from xml.etree import ElementTree as ET

MAX_XML_BYTES=1048576
MAX_NODES=4096
MAX_DEPTH=64
MAX_TEXT_BYTES=4096
MAX_TARGETS=256


class AndroidHierarchyRejected(ValueError):pass


@dataclass(frozen=True,slots=True)
class AndroidHierarchyTarget:
    resource_id:str
    status:str
    text:str|None=field(default=None,repr=False)
    enabled:bool|None=None
    checked:bool|None=None
    selected:bool|None=None
    focused:bool|None=None
    visible:bool|None=None


@dataclass(frozen=True,slots=True)
class AndroidHierarchy:
    rotation:int
    targets:tuple[AndroidHierarchyTarget,...]


def _target(resource,attrs):
    if attrs.get('password')=='true':return AndroidHierarchyTarget(resource,'redacted')
    if attrs.get('password')!='false':return AndroidHierarchyTarget(resource,'unavailable')
    flags=[]
    for name in ('enabled','checked','selected','focused','visible-to-user'):
        value=attrs.get(name)
        if value is not None and value not in {'true','false'}:return AndroidHierarchyTarget(resource,'unavailable')
        flags.append(None if value is None else value=='true')
    text=attrs.get('text')
    if text is not None and len(text.encode('utf-8'))>MAX_TEXT_BYTES:return AndroidHierarchyTarget(resource,'unavailable')
    return AndroidHierarchyTarget(resource,'available',text,*flags)


def parse_android_hierarchy(raw:bytes,*,package:str,resource_ids:tuple[str,...],rotation:int)->AndroidHierarchy:
    """No I/O/persistence; public failures retain no decoder context or input bytes."""
    try:
        return _parse(raw,package=package,resource_ids=resource_ids,rotation=rotation)
    except (ValueError,TypeError,UnicodeError,ET.ParseError,RecursionError):
        pass
    # A suppressed exception still retains its context; raise after leaving it.
    del raw,package,resource_ids,rotation
    raise AndroidHierarchyRejected('hierarchy_invalid')


def _parse(raw,*,package,resource_ids,rotation):
    if (type(raw) is not bytes or not 0<len(raw)<=MAX_XML_BYTES
        or type(package) is not str or len(package)>255
        or re.fullmatch(r'[A-Za-z][A-Za-z0-9_]*(?:\.[A-Za-z][A-Za-z0-9_]*)+',package) is None
        or type(resource_ids) is not tuple or len(resource_ids)>MAX_TARGETS
        or type(rotation) is not int or rotation not in {0,90,180,270}):raise ValueError()
    for resource in resource_ids:
        if (type(resource) is not str or len(resource)>512
            or re.fullmatch(re.escape(package)+r':id/[A-Za-z_][A-Za-z0-9_]{0,127}',resource) is None):raise ValueError()
    text=raw.decode('utf-8')
    if '\x00' in text:raise ValueError()
    if re.search(r'<!\s*(?:DOCTYPE|ENTITY)\b',text,re.IGNORECASE):raise ValueError()
    declaration=re.match(r'^\ufeff?\s*<\?xml\s+[^?]*?encoding\s*=\s*[\"\']([^\"\']+)',text)
    if declaration and declaration[1].lower() not in {'utf-8','utf8'}:raise ValueError()
    matches={resource:[] for resource in sorted(set(resource_ids))}
    parser=ET.XMLPullParser(events=('start','end'))
    depth=nodes=0;seen_root=closed=False
    def consume():
        nonlocal depth,nodes,seen_root,closed
        for event,element in parser.read_events():
            if event=='start':
                depth+=1
                if depth>MAX_DEPTH:raise ValueError()
                if depth==1:
                    if seen_root or element.tag!='hierarchy':raise ValueError()
                    seen_root=True
                    turn=element.attrib.get('rotation')
                    if turn not in {'0','1','2','3'} or int(turn)*90!=rotation:raise ValueError()
                else:
                    if element.tag!='node':raise ValueError()
                    nodes+=1
                    if nodes>MAX_NODES:raise ValueError()
                    resource=element.attrib.get('resource-id')
                    if resource in matches and element.attrib.get('package')==package:
                        values=matches[resource]
                        # More than one matching native node is ambiguous; retain no text.
                        if values:values[:]=[AndroidHierarchyTarget(resource,'ambiguous')]
                        else:values.append(_target(resource,element.attrib))
            else:
                depth-=1;closed=depth==0
                element.clear()
    for start in range(0,len(text),8192):
        parser.feed(text[start:start+8192]);consume()
    parser.close();consume()
    if not seen_root or not closed or depth!=0:raise ValueError()
    return AndroidHierarchy(rotation,tuple(values[0] if values else AndroidHierarchyTarget(resource,'missing') for resource,values in matches.items()))
