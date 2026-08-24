from __future__ import annotations

"""Bounded U3D base-mesh decoder used by the interactive PDF viewer.

The file/block layout follows ECMA-363 (4th edition). The arithmetic decoding
state and CLOD base-mesh field order are a Python adaptation of the Intel U3D
Sample Software, Copyright (c) 1999-2006 Intel Corporation, licensed under the
Apache License 2.0. See licenses/Apache-2.0.txt and THIRD_PARTY_NOTICES.md.
"""

import hashlib
import struct
from collections import defaultdict
from dataclasses import dataclass
from typing import Callable, Iterable

import numpy as np


class U3DDecodeError(RuntimeError):
    """Raised when a U3D stream cannot be decoded safely."""


class U3DDecodeCancelled(U3DDecodeError):
    """Raised when an in-progress preview decode is cancelled."""


@dataclass(frozen=True)
class U3DMesh:
    name: str
    positions: np.ndarray
    normals: np.ndarray
    indices: np.ndarray
    color: tuple[float, float, float, float]
    primitive: str = "triangles"


@dataclass(frozen=True)
class U3DScene:
    meshes: tuple[U3DMesh, ...]
    resource_count: int
    instance_count: int
    source_faces: int
    rendered_faces: int
    proxy_instances: int
    progressive_resources: int
    units: float

    @property
    def omitted_faces(self) -> int:
        return max(0, self.source_faces - self.rendered_faces)


@dataclass(frozen=True)
class _Block:
    block_type: int
    payload: memoryview


@dataclass(frozen=True)
class _Material:
    diffuse: bool
    specular: bool
    texture_layers: int


@dataclass(frozen=True)
class _Declaration:
    exclude_normals: bool
    materials: tuple[_Material, ...]


@dataclass(frozen=True)
class _Node:
    name: str
    resource: str
    parent_name: str
    local_transform: tuple[float, ...]


_FILE_HEADER = 0x00443355
_MODIFIER_CHAIN = 0xFFFFFF14
_MODEL_NODE = 0xFFFFFF22
_CLOD_DECLARATION = 0xFFFFFF31
_CLOD_BASE_MESH = 0xFFFFFF3B
_CLOD_PROGRESSIVE = 0xFFFFFF3C

_PROFILE_NO_COMPRESSION = 0x00000004
_PROFILE_UNITS_SCALE = 0x00000008

_STATIC_CONTEXT_BASE = 0x00000400
_MAX_CONTEXT = _STATIC_CONTEXT_BASE + 0x00003FFF
_BASE_SHADING_CONTEXT = 1

_MAX_STREAM_BYTES = 512 * 1024 * 1024
_MAX_BLOCKS = 250_000
_MAX_RESOURCES = 100_000
_MAX_NODES = 250_000
_MAX_ELEMENTS_PER_RESOURCE = 50_000_000
_MAX_MATERIALS = 65_536
_MAX_NAME_BYTES = 1_048_576

_MASK32 = 0xFFFFFFFF
_HALF_MASK = 0x80008000
_NOT_HALF_MASK = 0x7FFF7FFF
_QUARTER_MASK = 0x40004000
_NOT_THREE_QUARTER_MASK = 0x3FFF3FFF
_REVERSE_NIBBLE = (0, 8, 4, 12, 2, 10, 6, 14, 1, 9, 5, 13, 3, 11, 7, 15)
_READ_COUNT = (4, 3, 2, 2, 1, 1, 1, 1, 0, 0, 0, 0, 0, 0, 0, 0)
_FAST_NOT_MASK = (0xFFFFFFFF, 0x7FFF7FFF, 0x3FFF3FFF, 0x1FFF1FFF, 0x0FFF0FFF)
_IDENTITY = (
    1.0,
    0.0,
    0.0,
    0.0,
    0.0,
    1.0,
    0.0,
    0.0,
    0.0,
    0.0,
    1.0,
    0.0,
    0.0,
    0.0,
    0.0,
    1.0,
)


def _align4(value: int) -> int:
    return (value + 3) & ~3


def _decode_name(raw: bytes) -> str:
    return raw.decode("utf-8", "replace").rstrip("\0")


class _RawReader:
    def __init__(self, data: memoryview) -> None:
        self.data = data
        self.offset = 0

    def _take(self, size: int) -> memoryview:
        end = self.offset + size
        if size < 0 or end > len(self.data):
            raise U3DDecodeError("The U3D block ends before all declared fields were read.")
        value = self.data[self.offset:end]
        self.offset = end
        return value

    def u16(self) -> int:
        return int(struct.unpack_from("<H", self._take(2), 0)[0])

    def u32(self) -> int:
        return int(struct.unpack_from("<I", self._take(4), 0)[0])

    def f32(self) -> float:
        return float(struct.unpack_from("<f", self._take(4), 0)[0])

    def f64(self) -> float:
        return float(struct.unpack_from("<d", self._take(8), 0)[0])

    def string(self) -> str:
        size = self.u16()
        if size > _MAX_NAME_BYTES:
            raise U3DDecodeError("A U3D object name exceeds the safety limit.")
        return _decode_name(bytes(self._take(size)))


def _iter_blocks(data: memoryview, start: int = 0, end: int | None = None) -> Iterable[_Block]:
    limit = len(data) if end is None else min(end, len(data))
    offset = start
    count = 0
    while offset + 12 <= limit:
        block_type, data_size, metadata_size = struct.unpack_from("<III", data, offset)
        offset += 12
        data_end = offset + int(data_size)
        next_offset = offset + _align4(int(data_size)) + _align4(int(metadata_size))
        if data_end > limit or next_offset > limit:
            raise U3DDecodeError("A U3D block declares data beyond the end of the stream.")
        yield _Block(int(block_type), data[offset:data_end])
        count += 1
        if count > _MAX_BLOCKS:
            raise U3DDecodeError("The U3D stream contains too many blocks.")
        offset = next_offset


def _modifier_content_offset(payload: memoryview) -> int:
    reader = _RawReader(payload)
    name_length = reader.u16()
    if name_length > _MAX_NAME_BYTES:
        raise U3DDecodeError("A U3D modifier-chain name exceeds the safety limit.")
    reader._take(name_length)
    reader.u32()  # chain type
    attributes = reader.u32()
    if attributes & 0x01:
        reader._take(16)
    if attributes & 0x02:
        reader._take(24)
    reader.offset += (-((2 + name_length) & 3)) & 3
    reader.u32()  # nested modifier count
    return reader.offset


def _walk_blocks(data: memoryview) -> Iterable[_Block]:
    seen = 0

    def walk(blocks: Iterable[_Block], depth: int) -> Iterable[_Block]:
        nonlocal seen
        if depth > 8:
            raise U3DDecodeError("U3D modifier chains are nested too deeply.")
        for block in blocks:
            seen += 1
            if seen > _MAX_BLOCKS:
                raise U3DDecodeError("The U3D stream contains too many nested blocks.")
            yield block
            if block.block_type == _MODIFIER_CHAIN:
                start = _modifier_content_offset(block.payload)
                yield from walk(_iter_blocks(block.payload, start), depth + 1)

    yield from walk(_iter_blocks(data), 0)


class _DynamicHistogram:
    _ELEPHANT = 0x1FFF
    _MAX_SYMBOL = 0xFFFF

    def __init__(self) -> None:
        self.counts = [1]
        self.total = 1

    def frequency(self, symbol: int) -> int:
        return self.counts[symbol] if 0 <= symbol < len(self.counts) else 0

    def cumulative(self, symbol: int) -> int:
        if symbol <= 0:
            return 0
        return sum(self.counts[: min(symbol, len(self.counts))])

    def symbol_at(self, cumulative_frequency: int) -> int:
        running = 0
        for symbol, count in enumerate(self.counts):
            if count and cumulative_frequency < running + count:
                return symbol
            running += count
        return 0

    def add(self, symbol: int) -> None:
        if symbol < 0 or symbol > self._MAX_SYMBOL:
            return
        if self.total >= self._ELEPHANT:
            self.counts = [count >> 1 for count in self.counts]
            self.counts[0] += 1
            self.total = sum(self.counts)
        if symbol >= len(self.counts):
            self.counts.extend([0] * (symbol + 1 - len(self.counts)))
        self.counts[symbol] += 1
        self.total += 1


class _ArithmeticReader:
    """Intel U3D 16-bit arithmetic decoder adapted for Python."""

    def __init__(self, data: memoryview, no_compression: bool) -> None:
        raw = bytes(data)
        raw += b"\0" * ((-len(raw)) & 3)
        raw += b"\0" * 8
        self.words = struct.unpack(f"<{len(raw) // 4}I", raw)
        self.word_index = 0
        self.bit_offset = 0
        self.local = int(self.words[0])
        self.local_next = int(self.words[1])
        self.high = 0xFFFF
        self.low = 0
        self.code = 0
        self.underflow = 0
        self.no_compression = no_compression
        self.contexts: dict[int, _DynamicHistogram] = {}

    def _advance(self) -> None:
        self.word_index += 1
        if self.word_index + 1 >= len(self.words):
            raise U3DDecodeError("The arithmetic-coded U3D block is truncated.")
        self.local = int(self.words[self.word_index])
        self.local_next = int(self.words[self.word_index + 1])

    def _position(self) -> int:
        return (self.word_index << 5) + self.bit_offset

    def _seek(self, position: int) -> None:
        self.word_index = position >> 5
        self.bit_offset = position & 31
        if self.word_index + 1 >= len(self.words):
            raise U3DDecodeError("The arithmetic decoder sought beyond its block.")
        self.local = int(self.words[self.word_index])
        self.local_next = int(self.words[self.word_index + 1])

    def _read_bit(self) -> int:
        result = (self.local >> self.bit_offset) & 1
        self.bit_offset += 1
        if self.bit_offset >= 32:
            self.bit_offset -= 32
            self._advance()
        return result

    def _read_15_bits(self) -> int:
        result = (self.local >> self.bit_offset) & _MASK32
        if self.bit_offset > 17:
            result |= (self.local_next << (32 - self.bit_offset)) & _MASK32
        result = (result << 1) & _MASK32
        result = (
            _REVERSE_NIBBLE[(result >> 12) & 0xF]
            | (_REVERSE_NIBBLE[(result >> 8) & 0xF] << 4)
            | (_REVERSE_NIBBLE[(result >> 4) & 0xF] << 8)
            | (_REVERSE_NIBBLE[result & 0xF] << 12)
        )
        self.bit_offset += 15
        if self.bit_offset >= 32:
            self.bit_offset -= 32
            self._advance()
        return result

    def _fill_code(self) -> None:
        saved_position = self._position()
        self.code = self._read_bit()
        self.bit_offset += self.underflow
        while self.bit_offset >= 32:
            self.bit_offset -= 32
            self._advance()
        self.code = ((self.code << 15) | self._read_15_bits()) & _MASK32
        self._seek(saved_position)

    def _renormalize(self, state: int, bit_count: int) -> None:
        masked = state & _HALF_MASK
        while masked == 0 or masked == _HALF_MASK:
            state = (((state & _NOT_HALF_MASK) << 1) | 1) & _MASK32
            masked = state & _HALF_MASK
            bit_count += 1
        saved_bits = masked
        if bit_count:
            bit_count += self.underflow
            self.underflow = 0
        masked = state & _QUARTER_MASK
        new_underflow = 0
        while masked == 0x40000000:
            state = ((state & _NOT_THREE_QUARTER_MASK) << 1) & _MASK32
            state |= 1
            masked = state & _QUARTER_MASK
            new_underflow += 1
        self.underflow += new_underflow
        state |= saved_bits
        self.low = state >> 16
        self.high = state & 0xFFFF
        self.bit_offset += bit_count
        while self.bit_offset >= 32:
            self.bit_offset -= 32
            self._advance()

    def _static_symbol(self, context: int) -> int:
        self._fill_code()
        symbol_count = context - _STATIC_CONTEXT_BASE
        if symbol_count <= 0:
            raise U3DDecodeError("The U3D stream uses an invalid static context.")
        arithmetic_range = self.high + 1 - self.low
        cumulative = (
            symbol_count * (1 + self.code - self.low) - 1
        ) // arithmetic_range
        if cumulative < 0 or cumulative >= symbol_count:
            raise U3DDecodeError("A U3D static symbol is outside its declared context.")
        symbol = cumulative + 1
        low = self.low
        high = low - 1 + arithmetic_range * symbol // symbol_count
        low = low + arithmetic_range * (symbol - 1) // symbol_count
        state = ((low << 16) | high) & _MASK32
        bit_count = _READ_COUNT[((low >> 12) ^ (high >> 12)) & 0xF]
        state = ((state & _FAST_NOT_MASK[bit_count]) << bit_count) & _MASK32
        state |= (1 << bit_count) - 1
        second_count = _READ_COUNT[((state >> 12) ^ (state >> 28)) & 0xF]
        state = ((state & _FAST_NOT_MASK[second_count]) << second_count) & _MASK32
        state |= (1 << second_count) - 1
        self._renormalize(state, bit_count + second_count)
        return symbol

    def _dynamic_symbol(self, context: int) -> int:
        self._fill_code()
        histogram = self.contexts.setdefault(context, _DynamicHistogram())
        arithmetic_range = self.high + 1 - self.low
        cumulative = (
            histogram.total * (1 + self.code - self.low) - 1
        ) // arithmetic_range
        symbol = histogram.symbol_at(cumulative)
        symbol_cumulative = histogram.cumulative(symbol)
        symbol_frequency = histogram.frequency(symbol)
        if symbol_frequency <= 0:
            raise U3DDecodeError("A U3D dynamic symbol has zero frequency.")
        low = self.low
        high = low - 1 + arithmetic_range * (
            symbol_cumulative + symbol_frequency
        ) // histogram.total
        low = low + arithmetic_range * symbol_cumulative // histogram.total
        histogram.add(symbol)
        state = ((low << 16) | high) & _MASK32
        bit_count = _READ_COUNT[((low >> 12) ^ (high >> 12)) & 0xF]
        state = ((state & _FAST_NOT_MASK[bit_count]) << bit_count) & _MASK32
        state |= (1 << bit_count) - 1
        self._renormalize(state, bit_count)
        return symbol

    def _symbol(self, context: int) -> int:
        if context == 0:
            return self._static_symbol(_STATIC_CONTEXT_BASE + 256)
        if context > _STATIC_CONTEXT_BASE:
            return self._static_symbol(context)
        return self._dynamic_symbol(context)

    def u8(self) -> int:
        if self.high == 0xFFFF and self.low == 0 and self.underflow == 0:
            result = self.local >> self.bit_offset
            if self.bit_offset > 24:
                result |= self.local_next << (32 - self.bit_offset)
            self.bit_offset += 8
            if self.bit_offset >= 32:
                self.bit_offset -= 32
                self._advance()
            return result & 0xFF
        symbol = self._static_symbol(_STATIC_CONTEXT_BASE + 256) - 1
        return (_REVERSE_NIBBLE[symbol & 0xF] << 4) | _REVERSE_NIBBLE[symbol >> 4]

    def u16(self) -> int:
        return self.u8() | (self.u8() << 8)

    def u32(self) -> int:
        return self.u16() | (self.u16() << 16)

    def f32(self) -> float:
        return float(struct.unpack("<f", struct.pack("<I", self.u32()))[0])

    def string(self) -> str:
        size = self.u16()
        if size > _MAX_NAME_BYTES:
            raise U3DDecodeError("A U3D object name exceeds the safety limit.")
        return _decode_name(bytes(self.u8() for _ in range(size)))

    def compressed_u32(self, context: int) -> int:
        if self.no_compression:
            return self.u32()
        if context and context < _MAX_CONTEXT:
            symbol = self._symbol(context)
            if symbol:
                return symbol - 1
            value = self.u32()
            if context <= _STATIC_CONTEXT_BASE:
                self.contexts.setdefault(context, _DynamicHistogram()).add(value + 1)
            return value
        return self.u32()


def _block_name(payload: memoryview) -> str:
    return _RawReader(payload).string()


def _read_header(payload: memoryview) -> tuple[int, float]:
    reader = _RawReader(payload)
    reader.u32()  # format version
    profile = reader.u32()
    reader.u32()  # declaration size
    reader._take(8)  # complete file size
    reader.u32()  # character encoding
    units = reader.f64() if profile & _PROFILE_UNITS_SCALE else 1.0
    if not np.isfinite(units) or units <= 0:
        units = 1.0
    return profile, units


def _read_declaration(payload: memoryview, no_compression: bool) -> _Declaration:
    reader = _ArithmeticReader(payload, no_compression)
    reader.string()
    reader.u32()  # chain index
    exclude_normals = bool(reader.u32() & 1)
    maximum = tuple(reader.u32() for _ in range(7))
    if any(value > _MAX_ELEMENTS_PER_RESOURCE for value in maximum[:6]):
        raise U3DDecodeError("A U3D mesh declaration exceeds the element safety limit.")
    material_count = maximum[6]
    if material_count > _MAX_MATERIALS:
        raise U3DDecodeError("A U3D mesh declares too many materials.")
    materials: list[_Material] = []
    for _ in range(material_count):
        attributes = reader.u32()
        texture_layers = reader.u32()
        if texture_layers > 8:
            raise U3DDecodeError("A U3D material declares more than eight texture layers.")
        for _ in range(texture_layers):
            dimension = reader.u32()
            if dimension < 1 or dimension > 4:
                raise U3DDecodeError("A U3D texture coordinate has an invalid dimension.")
        reader.u32()  # original shading identifier
        materials.append(
            _Material(bool(attributes & 1), bool(attributes & 2), texture_layers)
        )
    return _Declaration(exclude_normals, tuple(materials))


def _base_counts_and_bounds(
    payload: memoryview,
) -> tuple[tuple[int, int, int, int, int, int], tuple[np.ndarray, np.ndarray]]:
    reader = _RawReader(payload)
    reader.string()
    reader.u32()
    counts = tuple(reader.u32() for _ in range(6))
    if any(value > _MAX_ELEMENTS_PER_RESOURCE for value in counts):
        raise U3DDecodeError("A U3D base mesh exceeds the element safety limit.")
    position_count = counts[1]
    if position_count:
        byte_count = position_count * 3 * 4
        if reader.offset + byte_count > len(payload):
            raise U3DDecodeError("A U3D base mesh has a truncated position array.")
        positions = np.frombuffer(
            payload,
            dtype="<f4",
            count=position_count * 3,
            offset=reader.offset,
        ).reshape((-1, 3))
        minimum = np.asarray(positions.min(axis=0), dtype=np.float32)
        maximum = np.asarray(positions.max(axis=0), dtype=np.float32)
    else:
        minimum = np.zeros(3, dtype=np.float32)
        maximum = np.zeros(3, dtype=np.float32)
    return counts, (minimum, maximum)  # type: ignore[return-value]


def _read_model_node(payload: memoryview) -> _Node:
    reader = _RawReader(payload)
    name = reader.string()
    parent_count = reader.u32()
    if parent_count > 64:
        raise U3DDecodeError("A U3D node has too many parents.")
    parent_name = ""
    transform = _IDENTITY
    for parent_index in range(parent_count):
        candidate_name = reader.string()
        candidate_transform = tuple(reader.f32() for _ in range(16))
        if parent_index == 0:
            parent_name = candidate_name
            transform = candidate_transform
    resource = reader.string()
    return _Node(name, resource, parent_name, transform)


def _world_transforms(nodes: list[_Node]) -> dict[str, np.ndarray]:
    by_name = {node.name: node for node in nodes if node.name}
    cache: dict[str, np.ndarray] = {}
    identity = np.eye(4, dtype=np.float64)

    def resolve(name: str, visiting: set[str] | None = None) -> np.ndarray:
        if name in cache:
            return cache[name]
        node = by_name.get(name)
        if node is None:
            return identity
        active = set() if visiting is None else visiting
        if name in active:
            return identity
        active.add(name)
        local = np.asarray(node.local_transform, dtype=np.float64).reshape((4, 4), order="F")
        parent = identity if not node.parent_name else resolve(node.parent_name, active)
        world = parent @ local
        cache[name] = world
        active.remove(name)
        return world

    for node in nodes:
        resolve(node.name)
    return cache


def _sampled_faces(
    payload: memoryview,
    declaration: _Declaration,
    no_compression: bool,
    keep_faces: int,
    cancelled: Callable[[], bool],
) -> tuple[np.ndarray, np.ndarray, int]:
    reader = _ArithmeticReader(payload, no_compression)
    reader.string()
    reader.u32()
    face_count, position_count, normal_count, diffuse_count, specular_count, tex_count = (
        reader.u32() for _ in range(6)
    )
    if any(
        value > _MAX_ELEMENTS_PER_RESOURCE
        for value in (
            face_count,
            position_count,
            normal_count,
            diffuse_count,
            specular_count,
            tex_count,
        )
    ):
        raise U3DDecodeError("A U3D base mesh exceeds the element safety limit.")
    positions = np.empty((position_count, 3), dtype=np.float32)
    for index in range(position_count):
        positions[index] = (reader.f32(), reader.f32(), reader.f32())
    for _ in range(normal_count * 3 + diffuse_count * 4 + specular_count * 4 + tex_count * 4):
        reader.f32()

    keep_faces = max(0, min(face_count, keep_faces))
    selected = np.empty((keep_faces, 3), dtype=np.uint32)
    selected_count = 0
    accumulator = 0
    materials = declaration.materials
    fallback_material = _Material(False, False, 0)
    for face_index in range(face_count):
        if face_index % 2048 == 0 and cancelled():
            raise U3DDecodeCancelled("U3D decoding was cancelled.")
        material_index = reader.compressed_u32(_BASE_SHADING_CONTEXT)
        material = materials[material_index] if material_index < len(materials) else fallback_material
        triangle = [0, 0, 0]
        for corner in range(3):
            position = reader.compressed_u32(_STATIC_CONTEXT_BASE + position_count)
            if position >= position_count:
                raise U3DDecodeError("A U3D face references a position outside its mesh.")
            triangle[corner] = position
            if not declaration.exclude_normals:
                reader.compressed_u32(_STATIC_CONTEXT_BASE + normal_count)
            if material.diffuse:
                reader.compressed_u32(_STATIC_CONTEXT_BASE + diffuse_count)
            if material.specular:
                reader.compressed_u32(_STATIC_CONTEXT_BASE + specular_count)
            for _ in range(material.texture_layers):
                reader.compressed_u32(_STATIC_CONTEXT_BASE + tex_count)
        accumulator += keep_faces
        if accumulator >= face_count and selected_count < keep_faces:
            selected[selected_count] = triangle
            selected_count += 1
            accumulator -= face_count
    return positions, selected[:selected_count], face_count


def _part_color(name: str) -> tuple[float, float, float, float]:
    palette = (
        (0.25, 0.45, 0.72, 1.0),
        (0.48, 0.58, 0.70, 1.0),
        (0.56, 0.50, 0.38, 1.0),
        (0.34, 0.56, 0.52, 1.0),
        (0.52, 0.48, 0.63, 1.0),
        (0.62, 0.61, 0.57, 1.0),
    )
    index = hashlib.blake2s(name.encode("utf-8", "replace"), digest_size=1).digest()[0]
    return palette[index % len(palette)]


def _mesh_for_instances(
    name: str,
    positions: np.ndarray,
    faces: np.ndarray,
    transforms: list[np.ndarray],
) -> U3DMesh:
    expanded_parts: list[np.ndarray] = []
    triangles = positions[faces]
    for transform in transforms:
        linear = np.asarray(transform[:3, :3], dtype=np.float32)
        translation = np.asarray(transform[:3, 3], dtype=np.float32)
        expanded_parts.append(triangles @ linear.T + translation)
    expanded = np.ascontiguousarray(np.concatenate(expanded_parts, axis=0), dtype=np.float32)
    edges_a = expanded[:, 1] - expanded[:, 0]
    edges_b = expanded[:, 2] - expanded[:, 0]
    face_normals = np.cross(edges_a, edges_b)
    lengths = np.linalg.norm(face_normals, axis=1)
    valid = lengths > 1e-12
    face_normals[valid] /= lengths[valid, np.newaxis]
    face_normals[~valid] = (0.0, 0.0, 1.0)
    normals = np.ascontiguousarray(np.repeat(face_normals[:, np.newaxis, :], 3, axis=1).reshape((-1, 3)))
    flat_positions = np.ascontiguousarray(expanded.reshape((-1, 3)), dtype=np.float32)
    indices = np.arange(len(flat_positions), dtype=np.uint32)
    return U3DMesh(name, flat_positions, normals, indices, _part_color(name))


def _proxy_mesh(
    names: list[str],
    bounds: dict[str, tuple[np.ndarray, np.ndarray]],
    occurrences: dict[str, list[np.ndarray]],
) -> tuple[U3DMesh | None, int]:
    edge_pairs = np.asarray(
        (
            (0, 1),
            (1, 3),
            (3, 2),
            (2, 0),
            (4, 5),
            (5, 7),
            (7, 6),
            (6, 4),
            (0, 4),
            (1, 5),
            (2, 6),
            (3, 7),
        ),
        dtype=np.uint8,
    )
    parts: list[np.ndarray] = []
    instance_count = 0
    for name in names:
        minimum, maximum = bounds[name]
        if not np.all(np.isfinite(minimum)) or not np.all(np.isfinite(maximum)):
            continue
        corners = np.asarray(
            (
                (minimum[0], minimum[1], minimum[2]),
                (maximum[0], minimum[1], minimum[2]),
                (minimum[0], maximum[1], minimum[2]),
                (maximum[0], maximum[1], minimum[2]),
                (minimum[0], minimum[1], maximum[2]),
                (maximum[0], minimum[1], maximum[2]),
                (minimum[0], maximum[1], maximum[2]),
                (maximum[0], maximum[1], maximum[2]),
            ),
            dtype=np.float32,
        )
        for transform in occurrences[name]:
            linear = np.asarray(transform[:3, :3], dtype=np.float32)
            translation = np.asarray(transform[:3, 3], dtype=np.float32)
            world = corners @ linear.T + translation
            parts.append(world[edge_pairs].reshape((-1, 3)))
            instance_count += 1
    if not parts:
        return None, 0
    positions = np.ascontiguousarray(np.concatenate(parts, axis=0), dtype=np.float32)
    normals = np.zeros_like(positions, dtype=np.float32)
    normals[:, 2] = 1.0
    return (
        U3DMesh(
            "Undecoded part outlines",
            positions,
            normals,
            np.arange(len(positions), dtype=np.uint32),
            (0.52, 0.58, 0.67, 0.34),
            "lines",
        ),
        instance_count,
    )


def decode_u3d_scene(
    data: bytes,
    *,
    max_triangles: int = 1_000_000,
    progress: Callable[[int, str], None] | None = None,
    cancelled: Callable[[], bool] | None = None,
) -> U3DScene:
    """Decode a bounded, representative U3D CLOD base-mesh preview.

    Large assemblies are ranked by their expanded triangle contribution and
    decoded up to ``max_triangles``. This keeps interactive GPU memory bounded
    while preserving the most visually significant parts of the model.
    """

    if not data or len(data) > _MAX_STREAM_BYTES:
        raise U3DDecodeError("The U3D stream is empty or exceeds the 512 MB safety limit.")
    if max_triangles < 1 or max_triangles > 10_000_000:
        raise U3DDecodeError("The U3D preview triangle limit is invalid.")
    notify = progress or (lambda _percent, _message: None)
    is_cancelled = cancelled or (lambda: False)
    notify(1, "Inspecting U3D blocks...")
    view = memoryview(data)
    try:
        first_block = next(iter(_iter_blocks(view)))
    except StopIteration as exc:
        raise U3DDecodeError("The embedded stream has no U3D blocks.") from exc
    if first_block.block_type != _FILE_HEADER:
        raise U3DDecodeError("The embedded stream does not have a valid U3D file header.")
    profile, units = _read_header(first_block.payload)
    no_compression = bool(profile & _PROFILE_NO_COMPRESSION)

    declarations: dict[str, memoryview] = {}
    bases: dict[str, memoryview] = {}
    order: list[str] = []
    nodes: list[_Node] = []
    progressive_names: set[str] = set()
    for block in _walk_blocks(view):
        if is_cancelled():
            raise U3DDecodeCancelled("U3D decoding was cancelled.")
        if block.block_type in {_CLOD_DECLARATION, _CLOD_BASE_MESH, _CLOD_PROGRESSIVE}:
            name = _block_name(block.payload)
            if not name:
                continue
            if name not in order:
                order.append(name)
            if block.block_type == _CLOD_DECLARATION:
                declarations.setdefault(name, block.payload)
            elif block.block_type == _CLOD_BASE_MESH:
                bases.setdefault(name, block.payload)
            else:
                progressive_names.add(name)
        elif block.block_type == _MODEL_NODE:
            if len(nodes) >= _MAX_NODES:
                raise U3DDecodeError("The U3D scene contains too many model nodes.")
            nodes.append(_read_model_node(block.payload))
    paired_names = [name for name in order if name in declarations and name in bases]
    if not paired_names:
        raise U3DDecodeError(
            "The U3D model has no supported CLOD base meshes. Point/line-only or progressive-only models are not yet supported."
        )
    if len(paired_names) > _MAX_RESOURCES:
        raise U3DDecodeError("The U3D scene contains too many mesh resources.")

    notify(4, "Reading the U3D model tree...")
    worlds = _world_transforms(nodes)
    occurrences: dict[str, list[np.ndarray]] = defaultdict(list)
    for node in nodes:
        if node.resource in bases:
            occurrences[node.resource].append(worlds.get(node.name, np.eye(4, dtype=np.float64)))
    identity = np.eye(4, dtype=np.float64)
    counts: dict[str, tuple[int, int, int, int, int, int]] = {}
    bounds: dict[str, tuple[np.ndarray, np.ndarray]] = {}
    ranked: list[tuple[int, str]] = []
    source_faces = 0
    instance_count = 0
    for name in paired_names:
        base_counts, base_bounds = _base_counts_and_bounds(bases[name])
        counts[name] = base_counts
        bounds[name] = base_bounds
        transforms = occurrences.get(name)
        if not transforms:
            occurrences[name] = [identity]
            transforms = occurrences[name]
        contribution = base_counts[0] * len(transforms)
        source_faces += contribution
        instance_count += len(transforms)
        ranked.append((contribution, name))
    ranked.sort(key=lambda item: item[0], reverse=True)

    selected: list[tuple[str, int]] = []
    remaining = max_triangles
    for contribution, name in ranked:
        if remaining <= 0:
            break
        face_count = counts[name][0]
        occurrence_count = len(occurrences[name])
        keep_per_instance = min(face_count, remaining // occurrence_count)
        if keep_per_instance < 1 and remaining >= occurrence_count:
            keep_per_instance = 1
        if keep_per_instance < 1:
            continue
        selected.append((name, keep_per_instance))
        remaining -= keep_per_instance * occurrence_count
    if not selected:
        raise U3DDecodeError("The U3D preview limit is too small for this model.")

    total_bytes = sum(len(bases[name]) for name, _ in selected)
    processed_bytes = 0
    meshes: list[U3DMesh] = []
    rendered_faces = 0
    for selected_index, (name, keep_faces) in enumerate(selected):
        if is_cancelled():
            raise U3DDecodeCancelled("U3D decoding was cancelled.")
        percent = 5 + int(88 * processed_bytes / max(1, total_bytes))
        notify(percent, f"Decoding U3D mesh {selected_index + 1:,} of {len(selected):,}...")
        declaration = _read_declaration(declarations[name], no_compression)
        positions, faces, _ = _sampled_faces(
            bases[name], declaration, no_compression, keep_faces, is_cancelled
        )
        processed_bytes += len(bases[name])
        if not len(faces) or not len(positions):
            continue
        transforms = occurrences[name]
        meshes.append(_mesh_for_instances(name, positions, faces, transforms))
        rendered_faces += len(faces) * len(transforms)
    selected_names = {name for name, _ in selected}
    proxy, proxy_instances = _proxy_mesh(
        [name for name in paired_names if name not in selected_names],
        bounds,
        occurrences,
    )
    if proxy is not None:
        meshes.append(proxy)
    if not meshes:
        raise U3DDecodeError("The U3D base meshes contain no renderable triangles.")
    notify(100, "U3D preview ready")
    return U3DScene(
        meshes=tuple(meshes),
        resource_count=len(paired_names),
        instance_count=instance_count,
        source_faces=source_faces,
        rendered_faces=rendered_faces,
        proxy_instances=proxy_instances,
        progressive_resources=len(progressive_names),
        units=units,
    )
