"""Pure selected-target facts from native XML. Raw values remain local, never QA or sanitized evidence."""
from dataclasses import dataclass,field
import re
from aiqa.environments.android_hierarchy_xml import (AndroidHierarchyRejected,read_hierarchy_xml,MAX_XML_BYTES,MAX_NODES,MAX_DEPTH)

MAX_TEXT_BYTES=4096
MAX_TARGETS=256


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
    except (ValueError,TypeError,UnicodeError,RecursionError):
        pass
    # A suppressed exception still retains its context; raise after leaving it.
    del raw,package,resource_ids,rotation
    raise AndroidHierarchyRejected('hierarchy_invalid')


def validate_hierarchy_request(package,resource_ids):
    try:
        if (type(package) is not str or len(package)>255
            or re.fullmatch(r'[A-Za-z][A-Za-z0-9_]*(?:\.[A-Za-z][A-Za-z0-9_]*)+',package) is None
            or type(resource_ids) is not tuple or len(resource_ids)>MAX_TARGETS):raise ValueError()
        for resource in resource_ids:
            if (type(resource) is not str or len(resource)>512
                or re.fullmatch(re.escape(package)+r':id/[A-Za-z_][A-Za-z0-9_]{0,127}',resource) is None):raise ValueError()
        return tuple(sorted(set(resource_ids)))
    except (ValueError,TypeError,UnicodeError):pass
    del package,resource_ids
    raise AndroidHierarchyRejected('hierarchy_invalid')


def _parse(raw,*,package,resource_ids,rotation):
    if type(rotation) is not int or rotation not in {0,90,180,270}:raise ValueError()
    resources=validate_hierarchy_request(package,resource_ids)
    root=read_hierarchy_xml(raw,rotation=rotation)
    matches={resource:[] for resource in resources}
    for element in root.iter('node'):
        resource=element.attrib.get('resource-id')
        if resource in matches and element.attrib.get('package')==package:
            values=matches[resource]
            if values:values[:]=[AndroidHierarchyTarget(resource,'ambiguous')]
            else:values.append(_target(resource,element.attrib))
    return AndroidHierarchy(rotation,tuple(values[0] if values else AndroidHierarchyTarget(resource,'missing') for resource,values in matches.items()))
