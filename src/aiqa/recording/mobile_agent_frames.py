"""Deterministic visible-state guard, without a model or semantic success inference."""
from io import BytesIO
from PIL import Image,ImageChops


class FrameDrift(ValueError):
    reason='screen_drift'


def _rough_screen_changed(first,second):
    """A key has no point target. A coarse grid ignores a changed list or chip."""
    left=first.convert('RGB').resize((8,8),Image.BOX).tobytes()
    right=second.convert('RGB').resize((8,8),Image.BOX).tobytes()
    changed=sum((abs(left[i]-right[i])+abs(left[i+1]-right[i+1])+abs(left[i+2]-right[i+2]))/3>36 for i in range(0,len(left),3))
    return changed>32


def require_frame_pixels(reference,current,action):
    if action.kind=='text':return
    with Image.open(BytesIO(reference)) as first,Image.open(BytesIO(current)) as second:
        if first.size!=second.size:raise FrameDrift('screen dimensions changed')
        width,height=first.size
        if action.kind not in {'tap','swipe'}:
            if _rough_screen_changed(first,second):raise FrameDrift('recorded interaction area changed')
            return
        xs=[action.x]+([action.x2] if action.kind=='swipe' else [])
        ys=[action.y]+([action.y2] if action.kind=='swipe' else [])
        box=(max(0,min(xs)-48),max(0,min(ys)-48),min(width,max(xs)+49),min(height,max(ys)+49))
        diff=ImageChops.difference(first.convert('RGB').crop(box),second.convert('RGB').crop(box))
        # Permit tiny clock/caret/raster changes, reject substantive change in the interaction area.
        data=diff.tobytes();pixels=list(zip(data[0::3],data[1::3],data[2::3]));changed=sum(max(p)>20 for p in pixels)
        if changed>len(pixels)*0.01 or sum(sum(p) for p in pixels)>len(pixels)*3*1.5:
            raise FrameDrift('recorded interaction area changed')



def _anchor(xml,x,y):
    import re
    from aiqa.environments.android_hierarchy_xml import read_hierarchy_xml,AndroidHierarchyRejected
    if not xml or not xml.lstrip().startswith('<'):return None
    try:root=read_hierarchy_xml(xml.encode('utf-8'))
    except (AndroidHierarchyRejected,UnicodeError):pass
    else:return _anchor_nodes(root,x,y)
    del xml
    raise FrameDrift('hierarchy invalid')


def _anchor_nodes(root,x,y):
    import re
    nodes=list(root.iter('node'))
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
    if action.kind=='text':return {'kind':'unchecked'}
    if action.kind=='tap':
        expected=_anchor(reference_hierarchy,action.x,action.y)
        if expected is not None:
            actual=_anchor(current_hierarchy,action.x,action.y)
            if actual!=expected:raise FrameDrift('recorded resource target changed')
            return {'kind':'resource_id','target':expected}
    require_frame_pixels(reference,current,action)
    return {'kind':'pixels'}
