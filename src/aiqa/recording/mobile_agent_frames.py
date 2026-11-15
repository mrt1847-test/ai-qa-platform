"""Deterministic visible-state guard, without a model or semantic success inference."""
from io import BytesIO
from PIL import Image,ImageChops


class FrameDrift(ValueError):
    reason='screen_drift'


def require_frame_pixels(reference,current,action):
    with Image.open(BytesIO(reference)) as first,Image.open(BytesIO(current)) as second:
        if first.size!=second.size:raise FrameDrift('screen dimensions changed')
        width,height=first.size
        if action.kind in {'tap','swipe'}:
            xs=[action.x]+([action.x2] if action.kind=='swipe' else [])
            ys=[action.y]+([action.y2] if action.kind=='swipe' else [])
            box=(max(0,min(xs)-48),max(0,min(ys)-48),min(width,max(xs)+49),min(height,max(ys)+49))
        else:box=(0,0,width,height)
        diff=ImageChops.difference(first.convert('RGB').crop(box),second.convert('RGB').crop(box))
        # Permit tiny clock/caret/raster changes, reject substantive change in the interaction area.
        data=diff.tobytes();pixels=list(zip(data[0::3],data[1::3],data[2::3]));changed=sum(max(p)>20 for p in pixels)
        if changed>len(pixels)*0.01 or sum(sum(p) for p in pixels)>len(pixels)*3*1.5:
            raise FrameDrift('recorded interaction area changed')



def _anchor(xml,x,y):
    import re,xml.etree.ElementTree as ET
    if not xml or not xml.lstrip().startswith('<'):return None
    if len(xml.encode('utf-8'))>1_000_000 or '<!DOCTYPE' in xml or '<!ENTITY' in xml:raise FrameDrift('hierarchy invalid')
    try:root=ET.fromstring(xml)
    except ET.ParseError:raise FrameDrift('hierarchy invalid') from None
    nodes=list(root.iter('node'))
    if len(nodes)>5000:raise FrameDrift('hierarchy too large')
    hits=[]
    for node in nodes:
        if node.get('clickable')!='true' or node.get('enabled')!='true':continue
        match=re.fullmatch(r'\[(\d+),(\d+)\]\[(\d+),(\d+)\]',node.get('bounds',''))
        if not match:continue
        left,top,right,bottom=map(int,match.groups())
        if left<=x<right and top<=y<bottom:hits.append(node)
    if not hits:return None
    node=hits[-1];identity=node.get('resource-id','');package=node.get('package','')
    if not identity.startswith(package+':id/') or not package or sum(n.get('resource-id')==identity for n in nodes)!=1:return None
    return {k:node.get(k,'') for k in ('resource-id','package','class','bounds','text','content-desc')}


def require_guarded_frame(reference,current,action,reference_hierarchy='',current_hierarchy=''):
    if action.kind=='tap':
        expected=_anchor(reference_hierarchy,action.x,action.y)
        if expected is not None:
            actual=_anchor(current_hierarchy,action.x,action.y)
            if actual!=expected:raise FrameDrift('recorded resource target changed')
            return {'kind':'resource_id','target':expected}
    require_frame_pixels(reference,current,action)
    return {'kind':'pixels'}
