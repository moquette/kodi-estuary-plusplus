#!/usr/bin/env python3
"""Extract PNGs from a Kodi XBT texture bundle. No third-party dependencies.

    bench/xbt-extract.py <Textures.xbt> <output-dir>

Why this exists: Kodi resource add-ons ship their artwork compiled into a single
`Textures.xbt`, so "use the official package" means decoding that bundle. The
usual tools are unavailable here: `python-lzo` will not install (PEP 668, and it
needs liblzo2 headers that are not present), and no TexturePacker binary ships
inside Kodi22.app. So the LZO1X decompressor is implemented below rather than
imported, and the standard library writes the PNGs.

The output is verifiable rather than trusted: every frame must decompress to
exactly width * height * 4 bytes, and the script fails loudly if any does not.

Bundle layout, from Kodi's XBTFReader:
    "XBTF"            4 bytes
    version           1 byte
    file count        uint32
    per file:
        path          256 bytes, NUL padded
        loop          uint32
        frame count   uint32
        per frame:
            width, height, format   3 x uint32
            packed size             uint64
            unpacked size           uint64
            duration                uint32
            offset                  uint64

Format 16 is A8R8G8B8, which is BGRA in memory order on little-endian, so the
channels are swizzled to RGBA before the PNG is written. Getting that wrong
produces images that look correct in outline but have red and blue swapped.
"""

import struct
import sys
import zlib
from pathlib import Path

XBT_FMT_A8R8G8B8 = 16


def lzo1x_decompress(src: bytes, expected: int) -> bytearray:
    """Pure-Python LZO1X decompressor.

    Follows the reference lzo1x_decompress control flow: an instruction byte
    selects either a literal run or a back-reference (distance, length) copy.
    Back-references may overlap the output written so far, so copies are done
    byte at a time rather than by slicing.
    """
    out = bytearray()
    ip = 0
    n = len(src)

    def literals(count: int) -> None:
        nonlocal ip
        out.extend(src[ip : ip + count])
        ip += count

    def long_length(t: int, bits: int) -> int:
        """Lengths above the field width are encoded as a run of zero bytes."""
        nonlocal ip
        if t != 0:
            return t
        length = 0
        while src[ip] == 0:
            length += 255
            ip += 1
        length += bits + src[ip]
        ip += 1
        return length

    first = True
    state = 0

    if src[ip] > 17:
        t = src[ip] - 17
        ip += 1
        literals(t)
        state = min(t, 4)
    else:
        first = False

    while ip < n:
        t = src[ip]
        ip += 1

        if t < 16:
            if state == 0:
                t = long_length(t, 15) + 3
                literals(t)
                state = 4
                continue
            elif state < 4:
                # short match, distance 1..2048
                dist = (t >> 2) + (src[ip] << 2) + 1
                ip += 1
                pos = len(out) - dist
                for _ in range(2):
                    out.append(out[pos])
                    pos += 1
                state = t & 3
                if state:
                    literals(state)
                continue
            else:
                dist = (t >> 2) + (src[ip] << 2) + 1
                ip += 1
                pos = len(out) - dist
                for _ in range(3):
                    out.append(out[pos])
                    pos += 1
                state = t & 3
                if state:
                    literals(state)
                continue

        if t >= 64:
            length = (t >> 5) - 1
            dist = ((t >> 2) & 7) + (src[ip] << 3) + 1
            ip += 1
            length += 2
        elif t >= 32:
            length = long_length(t & 31, 31) + 2
            d = struct.unpack_from("<H", src, ip)[0]
            ip += 2
            dist = (d >> 2) + 1
        else:  # 16..31
            length = long_length(t & 7, 7) + 2
            h = (t & 8) << 11
            d = struct.unpack_from("<H", src, ip)[0]
            ip += 2
            dist = h + (d >> 2) + 16384
            if dist == 16384:
                break  # end of stream marker
        pos = len(out) - dist
        if pos < 0:
            raise ValueError(f"back-reference before start: dist={dist}")
        for _ in range(length):
            out.append(out[pos])
            pos += 1
        state = d & 3 if t < 64 else (struct.unpack_from("<B", src, ip - 1)[0] & 3)
        state = 0 if len(out) >= expected else state
        trailing = t & 3 if t >= 64 else (d & 3)
        if trailing:
            literals(trailing)
        state = trailing

    return out


def write_png(path: Path, width: int, height: int, rgba: bytes) -> None:
    """Minimal PNG writer. zlib is in the standard library, so nothing else is."""
    raw = bytearray()
    stride = width * 4
    for y in range(height):
        raw.append(0)  # filter type 0, None
        raw.extend(rgba[y * stride : (y + 1) * stride])

    def chunk(tag: bytes, data: bytes) -> bytes:
        return (
            struct.pack(">I", len(data))
            + tag
            + data
            + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF)
        )

    png = b"\x89PNG\r\n\x1a\n"
    png += chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 6, 0, 0, 0))
    png += chunk(b"IDAT", zlib.compress(bytes(raw), 9))
    png += chunk(b"IEND", b"")
    path.write_bytes(png)


def main() -> int:
    if len(sys.argv) != 3:
        print("usage: xbt-extract.py <Textures.xbt> <output-dir>", file=sys.stderr)
        return 2
    src = Path(sys.argv[1])
    dest = Path(sys.argv[2])
    dest.mkdir(parents=True, exist_ok=True)

    d = src.read_bytes()
    if d[:4] != b"XBTF":
        print(f"not an XBT bundle: {src}", file=sys.stderr)
        return 1

    off = 5
    (count,) = struct.unpack_from("<I", d, off)
    off += 4

    entries = []
    for _ in range(count):
        path = d[off : off + 256].split(b"\x00")[0].decode()
        off += 256
        _loop, frames = struct.unpack_from("<II", d, off)
        off += 8
        for _ in range(frames):
            w, h, fmt = struct.unpack_from("<III", d, off)
            off += 12
            packed, unpacked = struct.unpack_from("<QQ", d, off)
            off += 16
            (_dur,) = struct.unpack_from("<I", d, off)
            off += 4
            (foff,) = struct.unpack_from("<Q", d, off)
            off += 8
            entries.append((path, w, h, fmt, packed, unpacked, foff))

    print(f"  {len(entries)} textures in {src.name}")
    ok = 0
    failed = []
    for path, w, h, fmt, packed, unpacked, foff in entries:
        if fmt != XBT_FMT_A8R8G8B8:
            failed.append((path, f"unsupported format {fmt}"))
            continue
        blob = d[foff : foff + packed]
        try:
            raw = (
                lzo1x_decompress(blob, unpacked)
                if packed != unpacked
                else bytearray(blob)
            )
        except Exception as exc:
            failed.append((path, f"decompress failed: {exc}"))
            continue
        if len(raw) != unpacked or unpacked != w * h * 4:
            failed.append((path, f"got {len(raw)} bytes, expected {unpacked}"))
            continue
        # A8R8G8B8 is BGRA in little-endian memory order.
        rgba = bytearray(len(raw))
        rgba[0::4] = raw[2::4]
        rgba[1::4] = raw[1::4]
        rgba[2::4] = raw[0::4]
        rgba[3::4] = raw[3::4]
        write_png(dest / Path(path).name, w, h, bytes(rgba))
        ok += 1

    print(f"  extracted {ok}/{len(entries)}")
    if failed:
        print(f"  FAILED {len(failed)}:")
        for p, why in failed[:8]:
            print(f"    {p}: {why}")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
