"""Read package identity from the same-install APK without external tools."""
from __future__ import annotations

import hashlib
import struct
import zipfile
from pathlib import Path


def _length8(data: bytes, offset: int) -> tuple[int, int]:
    value = data[offset]
    return (((value & 0x7f) << 8) | data[offset + 1], offset + 2) if value & 0x80 else (value, offset + 1)


def _length16(data: bytes, offset: int) -> tuple[int, int]:
    value = struct.unpack_from("<H", data, offset)[0]
    return (((value & 0x7fff) << 16) | struct.unpack_from("<H", data, offset + 2)[0], offset + 4) if value & 0x8000 else (value, offset + 2)


def read_apk_identity(apk_path: str) -> dict[str, object]:
    apk = Path(apk_path)
    with apk.open("rb") as stream:
        digest = hashlib.file_digest(stream, "sha256").hexdigest()
    with zipfile.ZipFile(apk) as archive:
        info = archive.getinfo("AndroidManifest.xml")
        if info.file_size > 1024 * 1024:
            raise ValueError("APK manifest exceeds identity limit")
        data = archive.read(info)
    if len(data) < 8:
        raise ValueError("APK manifest is truncated")
    kind, header, total = struct.unpack_from("<HHI", data)
    if kind != 3 or total != len(data):
        raise ValueError("APK manifest is not canonical binary XML")
    strings: list[str] = []
    offset = header
    while offset + 8 <= len(data):
        chunk, size, length = struct.unpack_from("<HHI", data, offset)
        if size < 8 or length < size or offset + length > len(data):
            raise ValueError("APK manifest chunk is invalid")
        if chunk == 1:
            count, flags, start = struct.unpack_from("<I", data, offset + 8)[0], struct.unpack_from("<I", data, offset + 16)[0], struct.unpack_from("<I", data, offset + 20)[0]
            if count > 65536 or size + count * 4 > length:
                raise ValueError("APK string pool is invalid")
            for index in range(count):
                at = offset + start + struct.unpack_from("<I", data, offset + size + index * 4)[0]
                if flags & 0x100:
                    _, at = _length8(data, at)
                    count_bytes, at = _length8(data, at)
                    value = data[at:at + count_bytes].decode("utf-8")
                else:
                    count_chars, at = _length16(data, at)
                    value = data[at:at + count_chars * 2].decode("utf-16-le")
                strings.append(value)
        elif chunk == 0x102:
            name = struct.unpack_from("<I", data, offset + 20)[0]
            if strings[name] == "manifest":
                attr_start, attr_size, count = struct.unpack_from("<HHH", data, offset + 24)
                if attr_size < 20 or 16 + attr_start + count * attr_size > length:
                    raise ValueError("APK manifest attributes are invalid")
                values: dict[str, object] = {}
                for index in range(count):
                    at = offset + 16 + attr_start + index * attr_size
                    name, raw = struct.unpack_from("<II", data, at + 4)
                    value_type, value = data[at + 15], struct.unpack_from("<I", data, at + 16)[0]
                    if raw != 0xffffffff:
                        values[strings[name]] = strings[raw]
                    elif value_type == 3:
                        values[strings[name]] = strings[value]
                    elif value_type in (0x10, 0x11):
                        values[strings[name]] = value
                code = values.get("versionCode")
                if not isinstance(code, int) or not isinstance(values.get("package"), str):
                    raise ValueError("APK package/versionCode identity is missing")
                return {"package_name": values["package"], "version_code": code,
                        "version_name": values.get("versionName", ""), "apk_sha256": digest}
        offset += length
    raise ValueError("APK manifest package identity is missing")
