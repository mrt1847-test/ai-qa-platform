"""Filter a capture in memory. The original bytes are not written by this module."""

from __future__ import annotations

from dataclasses import dataclass
import binascii
import struct
import zlib

from aiqa.contracts.actions import Observation


class RedactionError(ValueError):
    """The capture cannot be stored because filtering or the before-capture failed."""


@dataclass(frozen=True, slots=True)
class SanitizedCapture:
    png: bytes
    dom: str
    stdout: str
    messages: tuple[str, ...]


def filter_capture(observation: Observation, secrets: tuple[str, ...]) -> SanitizedCapture:
    """Validate the capture and discard reasoning; unprovable pixels fail closed."""

    if not observation.capture_ok or observation.geometry is None:
        raise RedactionError("before capture failed")
    _validate_png(observation.png, observation.geometry.physical_width, observation.geometry.physical_height)
    # Text replacement cannot prove that a pixel-rendered secret was removed.
    # Until a trusted pixel sanitizer can prove coverage, sensitive captures
    # must not reach the spool, model, or artifact API.
    if secrets:
        raise RedactionError("pixel redaction coverage is unavailable")
    return SanitizedCapture(observation.png, observation.dom, observation.stdout, tuple(observation.messages))


def _validate_png(png: bytes, width: int, height: int) -> None:
    if not png.startswith(b'\x89PNG\r\n\x1a\n') or len(png) > 5_000_000:
        raise RedactionError('invalid PNG')
    offset, header, ended = 8, None, False
    compressed = bytearray()
    try:
        while offset < len(png):
            size = struct.unpack_from('>I', png, offset)[0]
            kind = png[offset + 4:offset + 8]
            data = png[offset + 8:offset + 8 + size]
            crc = struct.unpack_from('>I', png, offset + 8 + size)[0]
            if binascii.crc32(kind + data) & 0xffffffff != crc:
                raise ValueError('CRC')
            if header is None and kind != b'IHDR':
                raise ValueError('header')
            if kind == b'IHDR':
                if header is not None or size != 13:
                    raise ValueError('header')
                header = struct.unpack('>IIBBBBB', data)
            elif kind == b'IDAT':
                compressed.extend(data)
            elif kind == b'IEND':
                if size:
                    raise ValueError('end')
                ended = True
            offset += size + 12
            if ended:
                break
        if header is None or not ended or offset != len(png):
            raise ValueError('incomplete PNG')
        w, h, bits, color, compression, filtering, interlace = header
        channels = {0: 1, 2: 3, 3: 1, 4: 2, 6: 4}.get(color)
        if (w, h) != (width, height) or w < 1 or h < 1 or w * h > 16_000_000:
            raise ValueError('geometry')
        if channels is None or bits not in {1, 2, 4, 8, 16} or compression or filtering or interlace:
            raise ValueError('unsupported PNG')
        if color in {2, 4, 6} and bits not in {8, 16} or color == 3 and bits == 16:
            raise ValueError('unsupported PNG')
        stride = (w * channels * bits + 7) // 8 + 1
        decoder = zlib.decompressobj()
        pixels = decoder.decompress(bytes(compressed), stride * h + 1)
        if len(pixels) != stride * h or not decoder.eof or decoder.unused_data:
            raise ValueError('pixels')
        if any(pixels[y * stride] > 4 for y in range(h)):
            raise ValueError('PNG filter')
    except (ValueError, struct.error, zlib.error) as exc:
        raise RedactionError('invalid PNG') from exc

