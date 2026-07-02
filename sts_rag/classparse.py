"""Small Java .class parser for Slay the Spire metadata extraction.

This is intentionally not a decompiler. It reads constant pools and method bytecode just
deeply enough to recover enum references, literal constructor arguments, and simple field
assignments such as ``baseDamage = 8``.
"""

from __future__ import annotations

from dataclasses import dataclass
import struct
from typing import Iterable


CPEntry = tuple


@dataclass(frozen=True)
class MethodInfo:
    name: str
    descriptor: str
    code: bytes | None = None


@dataclass(frozen=True)
class ParsedClass:
    pool: list[CPEntry | None]
    this_class: str
    super_class: str
    methods: tuple[MethodInfo, ...]

    def utf(self, index: int | None) -> str | None:
        return _utf(self.pool, index)

    def class_name(self, index: int | None) -> str | None:
        return _class_name(self.pool, index)

    def member_ref(self, index: int) -> tuple[str, str, str] | None:
        return _member_ref(self.pool, index)


@dataclass(frozen=True)
class BytecodeEvent:
    kind: str
    offset: int
    value: int | str | tuple[str, str, str] | None
    opcode: int


def parse_class(data: bytes) -> ParsedClass:
    if data[:4] != b"\xca\xfe\xba\xbe":
        raise ValueError("not a .class file")
    idx = 8
    pool, idx = _read_cp(data, idx)
    idx += 2  # access flags
    this_idx = _u2(data, idx)
    idx += 2
    super_idx = _u2(data, idx)
    idx += 2
    this_class = _class_name(pool, this_idx) or ""
    super_class = _class_name(pool, super_idx) or ""

    interfaces_count = _u2(data, idx)
    idx += 2 + interfaces_count * 2
    idx = _skip_members(data, idx)  # fields
    methods, idx = _read_methods(data, idx, pool)
    return ParsedClass(pool=pool, this_class=this_class, super_class=super_class, methods=tuple(methods))


def utf8_strings(pool: list[CPEntry | None]) -> list[str]:
    return [e[1] for e in pool if e and e[0] == "Utf8"]


def string_constants(pool: list[CPEntry | None]) -> list[str]:
    out: list[str] = []
    for entry in pool:
        if entry and entry[0] == "String":
            value = _utf(pool, entry[1])
            if value is not None:
                out.append(value)
    return out


def integer_constants(pool: list[CPEntry | None]) -> list[int]:
    return [e[1] for e in pool if e and e[0] == "Integer"]


def field_refs(pool: list[CPEntry | None]) -> list[tuple[str, str, str]]:
    return _member_refs(pool, tags={9})


def method_refs(pool: list[CPEntry | None]) -> list[tuple[str, str, str]]:
    return _member_refs(pool, tags={10, 11})


def enum_field_args(pool: list[CPEntry | None], owner_suffix: str) -> set[str]:
    return {
        name
        for owner, name, _desc in field_refs(pool)
        if owner and owner.split("/")[-1].endswith(owner_suffix) and name != "$VALUES"
    }


def bytecode_events(parsed: ParsedClass, code: bytes) -> list[BytecodeEvent]:
    events: list[BytecodeEvent] = []
    i = 0
    while i < len(code):
        offset = i
        op = code[i]
        i += 1

        if op == 0x02:
            events.append(BytecodeEvent("int", offset, -1, op))
        elif 0x03 <= op <= 0x08:
            events.append(BytecodeEvent("int", offset, op - 0x03, op))
        elif op == 0x10:
            if i + 1 > len(code):
                break
            events.append(BytecodeEvent("int", offset, _s1(code[i]), op))
            i += 1
        elif op == 0x11:
            if i + 2 > len(code):
                break
            events.append(BytecodeEvent("int", offset, _s2(code, i), op))
            i += 2
        elif op == 0x12:
            if i + 1 > len(code):
                break
            cp_index = code[i]
            i += 1
            _append_ldc_event(events, parsed, cp_index, offset, op)
        elif op in (0x13, 0x14):
            if i + 2 > len(code):
                break
            cp_index = _u2(code, i)
            i += 2
            _append_ldc_event(events, parsed, cp_index, offset, op)
        elif op in (0xB2, 0xB3, 0xB4, 0xB5):
            if i + 2 > len(code):
                break
            ref_index = _u2(code, i)
            i += 2
            ref = parsed.member_ref(ref_index)
            if ref:
                events.append(BytecodeEvent("field", offset, ref, op))
        elif op in (0xB6, 0xB7, 0xB8):
            if i + 2 > len(code):
                break
            ref_index = _u2(code, i)
            i += 2
            ref = parsed.member_ref(ref_index)
            if ref:
                events.append(BytecodeEvent("method", offset, ref, op))
        elif op == 0xB9:
            if i + 4 > len(code):
                break
            ref_index = _u2(code, i)
            i += 4
            ref = parsed.member_ref(ref_index)
            if ref:
                events.append(BytecodeEvent("method", offset, ref, op))
        elif op == 0xBA:
            if i + 4 > len(code):
                break
            i += 4
        elif op == 0xAA:
            i = _skip_tableswitch(code, offset + 1)
        elif op == 0xAB:
            i = _skip_lookupswitch(code, offset + 1)
        elif op == 0xC4:
            if i + 1 > len(code):
                break
            wide_op = code[i]
            i += 1
            extra = 4 if wide_op == 0x84 else 2
            if i + extra > len(code):
                break
            i += extra
        else:
            extra = _OPERAND_LENGTHS.get(op, 0)
            if i + extra > len(code):
                break
            i += extra
        if i > len(code):
            break
    return events


def method_events(parsed: ParsedClass, method_name: str | None = None) -> list[BytecodeEvent]:
    out: list[BytecodeEvent] = []
    for method in parsed.methods:
        if method.code is None:
            continue
        if method_name is not None and method.name != method_name:
            continue
        out.extend(bytecode_events(parsed, method.code))
    return out


def literal_before(events: list[BytecodeEvent], index: int, *, max_events: int = 12) -> int | None:
    start = max(0, index - max_events)
    for event in reversed(events[start:index]):
        if event.kind == "int" and isinstance(event.value, int):
            return event.value
    return None


def first_constructor_int_arg(parsed: ParsedClass, owner_suffix: str) -> int | None:
    """Best-effort literal int argument before a superclass constructor call."""
    for method in parsed.methods:
        if method.name != "<init>" or method.code is None:
            continue
        events = bytecode_events(parsed, method.code)
        for idx, event in enumerate(events):
            if event.kind != "method" or event.opcode != 0xB7:
                continue
            owner, name, _desc = event.value  # type: ignore[misc]
            if name == "<init>" and owner.endswith(owner_suffix):
                value = literal_before(events, idx)
                if value is not None:
                    return value
    return None


def assigned_literals(parsed: ParsedClass, field_names: Iterable[str]) -> dict[str, int]:
    wanted = set(field_names)
    found: dict[str, int] = {}
    for method in parsed.methods:
        if method.code is None:
            continue
        events = bytecode_events(parsed, method.code)
        for idx, event in enumerate(events):
            if event.kind != "field" or event.opcode != 0xB5:
                continue
            _owner, name, _desc = event.value  # type: ignore[misc]
            if name not in wanted or name in found:
                continue
            value = literal_before(events, idx)
            if value is not None:
                found[name] = value
    return found


def upgrade_literals(parsed: ParsedClass) -> dict[str, int]:
    methods = {
        "upgradeDamage": "upgrade_damage",
        "upgradeBlock": "upgrade_block",
        "upgradeMagicNumber": "upgrade_magic_number",
        "upgradeBaseCost": "upgrade_cost",
    }
    found: dict[str, int] = {}
    for method in parsed.methods:
        if method.name != "upgrade" or method.code is None:
            continue
        events = bytecode_events(parsed, method.code)
        for idx, event in enumerate(events):
            if event.kind != "method":
                continue
            _owner, name, _desc = event.value  # type: ignore[misc]
            key = methods.get(name)
            if not key or key in found:
                continue
            value = literal_before(events, idx)
            if value is not None:
                found[key] = value
    return found


def _append_ldc_event(
    events: list[BytecodeEvent],
    parsed: ParsedClass,
    cp_index: int,
    offset: int,
    op: int,
) -> None:
    entry = parsed.pool[cp_index] if 0 <= cp_index < len(parsed.pool) else None
    if not entry:
        return
    if entry[0] == "Integer":
        events.append(BytecodeEvent("int", offset, entry[1], op))
    elif entry[0] == "String":
        value = parsed.utf(entry[1])
        events.append(BytecodeEvent("string", offset, value, op))


def _read_cp(data: bytes, idx: int) -> tuple[list[CPEntry | None], int]:
    cp_count = _u2(data, idx)
    idx += 2
    pool: list[CPEntry | None] = [None] * cp_count
    i = 1
    while i < cp_count:
        tag = data[idx]
        idx += 1
        if tag == 1:
            ln = _u2(data, idx)
            idx += 2
            pool[i] = ("Utf8", data[idx:idx + ln].decode("utf-8", "replace"))
            idx += ln
        elif tag == 3:
            pool[i] = ("Integer", struct.unpack_from(">i", data, idx)[0])
            idx += 4
        elif tag == 4:
            pool[i] = ("Float", struct.unpack_from(">f", data, idx)[0])
            idx += 4
        elif tag == 5:
            pool[i] = ("Long", struct.unpack_from(">q", data, idx)[0])
            idx += 8
            i += 1
        elif tag == 6:
            pool[i] = ("Double", struct.unpack_from(">d", data, idx)[0])
            idx += 8
            i += 1
        elif tag in (7, 8, 16, 19, 20):
            pool[i] = (_tag_name(tag), _u2(data, idx))
            idx += 2
        elif tag in (9, 10, 11, 12, 17, 18):
            pool[i] = (tag, (_u2(data, idx), _u2(data, idx + 2)))
            idx += 4
        elif tag == 15:
            pool[i] = ("MethodHandle", (data[idx], _u2(data, idx + 1)))
            idx += 3
        else:
            raise ValueError(f"unknown constant-pool tag {tag} at slot {i}")
        i += 1
    return pool, idx


def _skip_members(data: bytes, idx: int) -> int:
    count = _u2(data, idx)
    idx += 2
    for _ in range(count):
        idx += 6
        idx = _skip_attributes(data, idx)
    return idx


def _read_methods(data: bytes, idx: int, pool: list[CPEntry | None]) -> tuple[list[MethodInfo], int]:
    count = _u2(data, idx)
    idx += 2
    methods: list[MethodInfo] = []
    for _ in range(count):
        idx += 2
        name = _utf(pool, _u2(data, idx)) or ""
        idx += 2
        descriptor = _utf(pool, _u2(data, idx)) or ""
        idx += 2
        attr_count = _u2(data, idx)
        idx += 2
        code: bytes | None = None
        for _attr in range(attr_count):
            attr_name = _utf(pool, _u2(data, idx)) or ""
            idx += 2
            attr_len = _u4(data, idx)
            idx += 4
            if attr_name == "Code":
                code = _read_code(data[idx:idx + attr_len])
            idx += attr_len
        methods.append(MethodInfo(name=name, descriptor=descriptor, code=code))
    return methods, idx


def _read_code(data: bytes) -> bytes:
    idx = 4
    code_len = _u4(data, idx)
    idx += 4
    return data[idx:idx + code_len]


def _skip_attributes(data: bytes, idx: int) -> int:
    count = _u2(data, idx)
    idx += 2
    for _ in range(count):
        idx += 2
        attr_len = _u4(data, idx)
        idx += 4 + attr_len
    return idx


def _member_refs(pool: list[CPEntry | None], tags: set[int]) -> list[tuple[str, str, str]]:
    out: list[tuple[str, str, str]] = []
    for index, entry in enumerate(pool):
        if entry and entry[0] in tags:
            ref = _member_ref(pool, index)
            if ref:
                out.append(ref)
    return out


def _member_ref(pool: list[CPEntry | None], index: int) -> tuple[str, str, str] | None:
    if index <= 0 or index >= len(pool):
        return None
    entry = pool[index]
    if not entry or entry[0] not in (9, 10, 11):
        return None
    owner = _class_name(pool, entry[1][0])
    name_type = pool[entry[1][1]]
    if not owner or not name_type or name_type[0] != 12:
        return None
    name = _utf(pool, name_type[1][0])
    descriptor = _utf(pool, name_type[1][1])
    if name is None or descriptor is None:
        return None
    return owner, name, descriptor


def _utf(pool: list[CPEntry | None], index: int | None) -> str | None:
    if not index or index >= len(pool):
        return None
    entry = pool[index]
    return entry[1] if entry and entry[0] == "Utf8" else None


def _class_name(pool: list[CPEntry | None], index: int | None) -> str | None:
    if not index or index >= len(pool):
        return None
    entry = pool[index]
    return _utf(pool, entry[1]) if entry and entry[0] == "Class" else None


def _tag_name(tag: int) -> str | int:
    return {7: "Class", 8: "String", 16: "MethodType", 19: "Module", 20: "Package"}.get(tag, tag)


def _skip_tableswitch(code: bytes, idx: int) -> int:
    idx += (4 - (idx % 4)) % 4
    if idx + 12 > len(code):
        return len(code)
    low = _s4(code, idx + 4)
    high = _s4(code, idx + 8)
    return idx + 12 + max(0, high - low + 1) * 4


def _skip_lookupswitch(code: bytes, idx: int) -> int:
    idx += (4 - (idx % 4)) % 4
    if idx + 8 > len(code):
        return len(code)
    pairs = _s4(code, idx + 4)
    return idx + 8 + max(0, pairs) * 8


def _u2(data: bytes, idx: int) -> int:
    return struct.unpack_from(">H", data, idx)[0]


def _u4(data: bytes, idx: int) -> int:
    return struct.unpack_from(">I", data, idx)[0]


def _s1(value: int) -> int:
    return value - 256 if value > 127 else value


def _s2(data: bytes, idx: int) -> int:
    return struct.unpack_from(">h", data, idx)[0]


def _s4(data: bytes, idx: int) -> int:
    return struct.unpack_from(">i", data, idx)[0]


_OPERAND_LENGTHS = {
    0x00: 0, 0x01: 0, 0x09: 0, 0x0A: 0, 0x0B: 0, 0x0C: 0, 0x0D: 0, 0x0E: 0,
    0x0F: 0, 0x15: 1, 0x16: 1, 0x17: 1, 0x18: 1, 0x19: 1, 0x1A: 0, 0x1B: 0,
    0x1C: 0, 0x1D: 0, 0x1E: 0, 0x1F: 0, 0x20: 0, 0x21: 0, 0x22: 0, 0x23: 0,
    0x24: 0, 0x25: 0, 0x26: 0, 0x27: 0, 0x28: 0, 0x29: 0, 0x2A: 0, 0x2B: 0,
    0x2C: 0, 0x2D: 0, 0x2E: 0, 0x2F: 0, 0x30: 0, 0x31: 0, 0x32: 0, 0x33: 0,
    0x34: 0, 0x35: 0, 0x36: 1, 0x37: 1, 0x38: 1, 0x39: 1, 0x3A: 1, 0x3B: 0,
    0x3C: 0, 0x3D: 0, 0x3E: 0, 0x3F: 0, 0x40: 0, 0x41: 0, 0x42: 0, 0x43: 0,
    0x44: 0, 0x45: 0, 0x46: 0, 0x47: 0, 0x48: 0, 0x49: 0, 0x4A: 0, 0x4B: 0,
    0x4C: 0, 0x4D: 0, 0x4E: 0, 0x4F: 0, 0x50: 0, 0x51: 0, 0x52: 0, 0x53: 0,
    0x54: 0, 0x55: 0, 0x56: 0, 0x57: 0, 0x58: 0, 0x59: 0, 0x5A: 0, 0x5B: 0,
    0x5C: 0, 0x5D: 0, 0x5E: 0, 0x5F: 0, 0x60: 0, 0x61: 0, 0x62: 0, 0x63: 0,
    0x64: 0, 0x65: 0, 0x66: 0, 0x67: 0, 0x68: 0, 0x69: 0, 0x6A: 0, 0x6B: 0,
    0x6C: 0, 0x6D: 0, 0x6E: 0, 0x6F: 0, 0x70: 0, 0x71: 0, 0x72: 0, 0x73: 0,
    0x74: 0, 0x75: 0, 0x76: 0, 0x77: 0, 0x78: 0, 0x79: 0, 0x7A: 0, 0x7B: 0,
    0x7C: 0, 0x7D: 0, 0x7E: 0, 0x7F: 0, 0x80: 0, 0x81: 0, 0x82: 0, 0x83: 0,
    0x84: 2, 0x85: 0, 0x86: 0, 0x87: 0, 0x88: 0, 0x89: 0, 0x8A: 0, 0x8B: 0,
    0x8C: 0, 0x8D: 0, 0x8E: 0, 0x8F: 0, 0x90: 0, 0x91: 0, 0x92: 0, 0x93: 0,
    0x94: 0, 0x95: 0, 0x96: 0, 0x97: 0, 0x98: 0, 0x99: 2, 0x9A: 2, 0x9B: 2,
    0x9C: 2, 0x9D: 2, 0x9E: 2, 0x9F: 2, 0xA0: 2, 0xA1: 2, 0xA2: 2, 0xA3: 2,
    0xA4: 2, 0xA5: 2, 0xA6: 2, 0xA7: 2, 0xA8: 2, 0xA9: 1, 0xAC: 0, 0xAD: 0,
    0xAE: 0, 0xAF: 0, 0xB0: 0, 0xB1: 0, 0xBC: 1, 0xBD: 2, 0xBE: 0, 0xBF: 0,
    0xC0: 2, 0xC1: 2, 0xC2: 0, 0xC3: 0, 0xC5: 3, 0xC6: 2, 0xC7: 2, 0xC8: 4,
    0xC9: 4,
}
