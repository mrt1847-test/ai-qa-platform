"""Pure image/coordinate metadata shared by management and execution workers."""
from __future__ import annotations
from dataclasses import dataclass
from aiqa.contracts.actions import CaptureGeometry


@dataclass(frozen=True, slots=True)
class ProviderObservation:
    png: bytes
    image_hash: str
    geometry: dict[str, object]
    captured_at: str


class ObservationRejected(ValueError):
    pass


def parse_geometry(raw):
    fields = {'physical_width','physical_height','model_width','model_height','transform','rotation','content_bounds'}
    if type(raw) is not dict or set(raw) != fields:
        raise ObservationRejected('observation_geometry')
    for name in ('physical_width','physical_height','model_width','model_height'):
        if type(raw[name]) is not int or not 1 <= raw[name] <= 16000:
            raise ObservationRejected('observation_geometry')
    bounds = raw['content_bounds']
    if (type(bounds) not in (list,tuple) or len(bounds) != 4 or any(type(v) is not int for v in bounds)
        or type(raw['rotation']) is not int or raw['rotation'] not in (0,90,180,270)
        or type(raw['transform']) is not str or raw['transform'] not in ('identity','scale')):
        raise ObservationRejected('observation_geometry')
    left,top,right,bottom = bounds
    if not (0 <= left < right <= raw['physical_width'] and 0 <= top < bottom <= raw['physical_height']):
        raise ObservationRejected('observation_geometry')
    if raw['transform'] == 'identity' and (raw['physical_width'],raw['physical_height']) != (raw['model_width'],raw['model_height']):
        raise ObservationRejected('observation_geometry')
    return CaptureGeometry(**{**raw,'content_bounds':tuple(bounds)})
