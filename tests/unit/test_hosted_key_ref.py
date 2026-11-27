from uuid import uuid4

import pytest

from aiqa.api.settings import _selected_key_ref


@pytest.mark.parametrize('field', ['project_id', 'ref_id'])
@pytest.mark.parametrize('value', [1, [], {}, None, True])
def test_key_reference_rejects_non_string_uuid_as_validation(field, value):
    project = uuid4()
    ref = {'project_id': str(project), 'ref_id': str(uuid4()), 'revision': 1}
    ref[field] = value
    with pytest.raises(ValueError):
        _selected_key_ref(project, {'key_ref': ref})
