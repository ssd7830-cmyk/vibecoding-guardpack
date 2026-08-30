import struct
import zipfile
from pathlib import Path


CLEAR_UTF8_FLAG = True
target = Path("release.zip")
with zipfile.ZipFile(target, "w", zipfile.ZIP_DEFLATED) as archive:
    archive.write("source/안내.txt", "배포/안내.txt")

if CLEAR_UTF8_FLAG:
    data = bytearray(target.read_bytes())
    cursor = 0
    while cursor + 30 <= len(data) and data[cursor:cursor + 4] == b"PK\x03\x04":
        flags = struct.unpack_from("<H", data, cursor + 6)[0] & ~0x800
        struct.pack_into("<H", data, cursor + 6, flags)
        name_len, extra_len = struct.unpack_from("<HH", data, cursor + 26)
        compressed_size = struct.unpack_from("<I", data, cursor + 18)[0]
        cursor += 30 + name_len + extra_len + compressed_size
    central = data.find(b"PK\x01\x02")
    while central >= 0 and central + 46 <= len(data):
        flags = struct.unpack_from("<H", data, central + 8)[0] & ~0x800
        struct.pack_into("<H", data, central + 8, flags)
        name_len, extra_len, comment_len = struct.unpack_from("<HHH", data, central + 28)
        central += 46 + name_len + extra_len + comment_len
        if data[central:central + 4] != b"PK\x01\x02":
            break
    target.write_bytes(data)
print("BUILD_RELEASE_OK")
