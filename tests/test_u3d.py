from __future__ import annotations

import struct
import threading

import numpy as np

from PySide6.QtTest import QSignalSpy

from pdf_helper.three_d import _U3DDecoderWorker
from pdf_helper.u3d import decode_u3d_scene


FILE_HEADER = 0x00443355
MODIFIER_CHAIN = 0xFFFFFF14
CLOD_DECLARATION = 0xFFFFFF31
CLOD_BASE_MESH = 0xFFFFFF3B
PROFILE_NO_COMPRESSION = 0x00000004


def _u3d_string(value: str) -> bytes:
    encoded = value.encode("utf-8")
    return struct.pack("<H", len(encoded)) + encoded


def _block(block_type: int, payload: bytes) -> bytes:
    padding = b"\0" * ((-len(payload)) & 3)
    return struct.pack("<III", block_type, len(payload), 0) + payload + padding


def make_uncompressed_triangle_u3d() -> bytes:
    name = "Triangle"
    declaration = bytearray()
    declaration += _u3d_string(name)
    declaration += struct.pack("<I", 0)  # chain index
    declaration += struct.pack("<I", 1)  # exclude normals
    declaration += struct.pack("<7I", 1, 3, 0, 0, 0, 0, 1)
    declaration += struct.pack("<3I", 0, 0, 0)  # material
    declaration += struct.pack("<2I", 3, 3)  # minimum/final resolution
    declaration += struct.pack("<3I", 1000, 1000, 1000)
    declaration += struct.pack("<8f", 1.0, 1.0, 1.0, 1.0, 1.0, 0.9, 0.5, 0.01)
    declaration += struct.pack("<I", 0)  # no bones

    chain = bytearray()
    name_field = _u3d_string(name)
    chain += name_field
    chain += struct.pack("<2I", 1, 0)  # resource chain, no attributes
    chain += b"\0" * ((-len(name_field)) & 3)
    chain += struct.pack("<I", 1)
    chain += _block(CLOD_DECLARATION, bytes(declaration))

    base = bytearray()
    base += _u3d_string(name)
    base += struct.pack("<I", 0)
    base += struct.pack("<6I", 1, 3, 0, 0, 0, 0)
    base += struct.pack(
        "<9f",
        0.0,
        0.0,
        0.0,
        2.0,
        0.0,
        0.0,
        0.0,
        1.0,
        0.0,
    )
    base += struct.pack("<4I", 0, 0, 1, 2)  # material and position corners

    header = struct.pack("<IIIQI", 0, PROFILE_NO_COMPRESSION, 0, 0, 106)
    return b"".join(
        (
            _block(FILE_HEADER, header),
            _block(MODIFIER_CHAIN, bytes(chain)),
            _block(CLOD_BASE_MESH, bytes(base)),
        )
    )


def test_uncompressed_u3d_triangle_is_decoded_for_the_builtin_viewer() -> None:
    scene = decode_u3d_scene(make_uncompressed_triangle_u3d(), max_triangles=100)

    assert scene.resource_count == 1
    assert scene.instance_count == 1
    assert scene.source_faces == 1
    assert scene.rendered_faces == 1
    assert scene.proxy_instances == 0
    assert len(scene.meshes) == 1
    np.testing.assert_allclose(
        scene.meshes[0].positions,
        ((0.0, 0.0, 0.0), (2.0, 0.0, 0.0), (0.0, 1.0, 0.0)),
    )
    np.testing.assert_array_equal(scene.meshes[0].indices, (0, 1, 2))


def test_u3d_worker_decodes_without_an_external_viewer() -> None:
    worker = _U3DDecoderWorker(make_uncompressed_triangle_u3d(), threading.Event())
    decoded = QSignalSpy(worker.decoded)
    failed = QSignalSpy(worker.failed)

    worker.run()

    assert decoded.count() == 1
    assert failed.count() == 0
    scene = decoded.at(0)[0]
    assert scene.rendered_faces == 1
