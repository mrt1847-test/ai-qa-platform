"""Field paths for editable assets. Domain validation remains authoritative."""
from decimal import Decimal, InvalidOperation
from aiqa.domain.environments import _origin

def environment_fields(body, require_name=True):
    errors={}
    if require_name and not str(body.get('name','')).strip(): errors['name']=['이름을 입력해 주세요.']
    target=body.get('target_kind')
    if target not in {'web','android'}: errors['target_kind']=['Web 또는 Android를 선택해 주세요.']
    viewport=body.get('viewport') or {}
    for key in ('width','height'):
        value=viewport.get(key) if type(viewport) is dict else None
        if type(value) is not int or value<1: errors['viewport.'+key]=['1 이상의 정수가 필요합니다.']
    limits=body.get('limits') or {}
    for key in ('timeout_seconds','max_actions'):
        value=limits.get(key) if type(limits) is dict else None
        if type(value) is not int or value<1: errors['limits.'+key]=['1 이상의 정수가 필요합니다.']
    for key in ('budget','currency'):
        if type(limits) is not dict or type(limits.get(key)) is not str or not limits[key].strip():
            errors['limits.'+key]=['값을 입력해 주세요.']
    if type(limits) is dict and isinstance(limits.get('budget'),str):
        try:
            amount=Decimal(limits['budget'])
            if not amount.is_finite() or amount<0: raise ValueError()
        except (InvalidOperation,ValueError): errors['limits.budget']=['0 이상의 금액이 필요합니다.']
    if not body.get('reset_policy'): errors['reset_policy']=['초기화 정책을 선택해 주세요.']
    if not body.get('locale'): errors['locale']=['로케일을 선택해 주세요.']
    allowlist=body.get('allowlist')
    if not isinstance(allowlist,list) or not allowlist: errors['allowlist']=['허용 대상을 입력해 주세요.']
    elif target=='web':
        try:
            origins={_origin(item) for item in allowlist}
            if body.get('start_url') and _origin(body['start_url']) not in origins:
                errors['start_url']=['시작 주소를 허용 주소 목록에 추가해 주세요.']
        except (ValueError,TypeError,AttributeError):
            errors['allowlist']=['HTTPS 또는 로컬 HTTP 주소를 입력해 주세요.']
    if target=='android' and not body.get('package'): errors['package']=['앱 패키지를 입력해 주세요.']
    return errors

def dataset_fields(body, require_name=True):
    errors={}
    if require_name and not str(body.get('name','')).strip(): errors['name']=['이름을 입력해 주세요.']
    schema=body.get('row_schema')
    columns=schema.get('columns') if type(schema) is dict else None
    if not isinstance(columns,list) or not columns:
        return {**errors,'columns':['열을 하나 이상 추가해 주세요.']}
    kinds={}; seen=set()
    for i,col in enumerate(columns):
        name=col.get('name') if type(col) is dict else None
        kind=col.get('type') if type(col) is dict else None
        if not isinstance(name,str) or not name.strip() or name in seen: errors[f'columns.{i}.name']=['열 이름은 비어 있거나 중복될 수 없습니다.']
        if kind not in ('string','int','bool'): errors[f'columns.{i}.type']=['문자·정수·참/거짓 중 선택해 주세요.']
        if isinstance(name,str): seen.add(name);kinds[name]=kind
    rows=body.get('rows')
    if not isinstance(rows,list) or not rows: return {**errors,'rows':['행을 하나 이상 추가해 주세요.']}
    row_ids=set()
    types={'string':str,'int':int,'bool':bool}
    for i,row in enumerate(rows):
        if type(row) is not dict: errors[f'rows.{i}']=['행 형식을 확인해 주세요.'];continue
        rid=row.get('id')
        if type(rid) is not str or not rid.strip() or rid in row_ids: errors[f'rows.{i}.id']=['행 ID는 비어 있거나 중복될 수 없습니다.']
        else: row_ids.add(rid)
        values=row.get('values')
        if type(values) is not dict: errors[f'rows.{i}']=['값이 필요합니다.'];continue
        if set(values)!=set(kinds): errors[f'rows.{i}']=['모든 열의 값을 확인해 주세요.']
        for name,kind in kinds.items():
            if type(values.get(name)) is not types.get(kind): errors[f'rows.{i}.values.{name}']=['선택한 열 타입에 맞는 값을 입력해 주세요.']
    return errors
