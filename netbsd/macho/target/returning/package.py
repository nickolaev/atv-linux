#!/usr/bin/env python3
"""Package a returning high-segment diagnostic, not a NetBSD boot image.

This modifies only a new Mach-O file. The original Linux loader resumes after
the diagnostic returns; Apple firmware's handling of the additional segment
is untested. Never use an ordinary non-returning hardware payload here.
"""
import struct
import sys
import zlib
from pathlib import Path

HERE = Path(__file__).resolve().parent
MACHO = HERE.parents[1]
sys.path.insert(0, str(MACHO))
sys.path.insert(0, str(MACHO / 'map_probe'))
sys.path.insert(0, str(HERE.parents[3] / 'image'))
from patch_probe import EXPECTED_ENTRY
from package import archive_has_capture, newc_entry
from embed_boot_menu import find_initrd

LIMIT = 1 << 32
HOOK = 0x600
BASE = 0x02000000
ORIGINAL_END = 0x02afd000
NAME = b'atv-loader-diag.bin'
STATUS_SIZE = 48
ABI = b'ATV1_RETURN_DIAG_V1'
MARKERS = (0xfeedc0de, 0xfeedface, 0xfeedbeef, 0xfeedbabe)


def macho(blob):
    if len(blob) < 28:
        raise ValueError('truncated Mach-O')
    magic, cpu, subtype, typ, count, length, flags = struct.unpack_from('<7I', blob)
    if (magic, cpu, subtype, typ) != (0xfeedface, 7, 3, 2) or 28 + length > len(blob):
        raise ValueError('expected bounded i386 Mach-O executable')
    pos, end, segments, entry = 28, 28 + length, [], None
    for _ in range(count):
        if pos + 8 > end:
            raise ValueError('truncated Mach-O command')
        cmd, size = struct.unpack_from('<II', blob, pos)
        if size < 8 or pos + size > end:
            raise ValueError('invalid Mach-O command')
        if cmd == 1:
            if size < 56:
                raise ValueError('truncated segment')
            name = blob[pos+8:pos+24].rstrip(b'\0')
            vm, vmsize, off, filesz, maxprot, initprot, nsects, _ = struct.unpack_from('<8I', blob, pos+24)
            if (56 + 68*nsects > size or vm + vmsize > LIMIT or
                    off + filesz > len(blob) or filesz > vmsize):
                raise ValueError('invalid Mach-O segment bounds')
            for index in range(nsects):
                section = pos + 56 + 68*index
                secsize, secoff = struct.unpack_from('<II', blob, section+36)
                if secsize and secoff and secoff + secsize > len(blob):
                    raise ValueError('section outside Mach-O file')
                if secsize and secoff and secoff < 0x1000 and secoff + secsize > end:
                    raise ValueError('section overlaps Mach-O header padding')
            segments.append((name, vm, vmsize, off, filesz, maxprot, initprot))
        elif cmd == 5:
            if size < 80 or entry is not None:
                raise ValueError('invalid thread entry')
            entry = struct.unpack_from('<I', blob, pos+56)[0]
        pos += size
    if pos != end or entry is None:
        raise ValueError('invalid command table or missing entry')
    return count, length, end, segments, entry


def elf_load(blob):
    if len(blob) < 52 or blob[:7] != b'\x7fELF\x01\x01\x01':
        raise ValueError('expected little-endian i386 shim ELF')
    h = struct.unpack_from('<16sHHIIIIIHHHHHH', blob)
    if h[1:3] != (2, 3) or h[4] != BASE + HOOK or h[9] != 32 or h[5] + h[9]*h[10] > len(blob):
        raise ValueError('unexpected shim ELF header')
    loads = [struct.unpack_from('<8I', blob, h[5] + i*32) for i in range(h[10])]
    loads = [p for p in loads if p[0] == 1]
    if len(loads) != 1:
        raise ValueError('shim must have one load segment')
    _, off, va, _, filesz, memsz, flags, _ = loads[0]
    if (va != BASE + HOOK or filesz != memsz or not filesz or not flags & 1 or
            off + filesz > len(blob) or filesz > 0x1000-HOOK):
        raise ValueError('invalid or oversized returning shim')
    payload = bytearray(blob[off:off+filesz])
    for marker in MARKERS:
        if payload.count(struct.pack('<I', marker)) != 1:
            raise ValueError('shim marker missing or not unique')
    return payload


def package(original, shim, high):
    count, length, end, segs, entry = macho(original)
    if end != 0x4cc or entry != 0x02001000 or original[0x1000:0x1010] != EXPECTED_ENTRY:
        raise ValueError('unexpected original loader entry/layout')
    if end + 56 > HOOK or any(original[end:0x1000]):
        raise ValueError('loader header padding is not empty')
    mapped = [s for s in segs if s[0] != b'__PAGEZERO' and s[2]]
    if not mapped or min(s[1] for s in mapped) != BASE or max(s[1]+s[2] for s in mapped) != ORIGINAL_END:
        raise ValueError('unexpected original loader footprint')
    text = [s for s in mapped if s[0] == b'__TEXT']
    if len(text) != 1 or text[0][1] != BASE or text[0][3] != 0:
        raise ValueError('unexpected original text mapping')
    for i, a in enumerate(mapped):
        if any(a[1] < b[1]+b[2] and b[1] < a[1]+a[2] for b in mapped[i+1:]):
            raise ValueError('overlapping original segments')

    _, _, _, high_segs, high_entry = macho(high)
    hs = [s for s in high_segs if s[0] != b'__PAGEZERO' and s[2]]
    if len(hs) != 1 or hs[0][0] != b'__TEXT':
        raise ValueError('diagnostic payload must contain one text segment')
    _, hva, hvsize, hoff, hsize, _, hprot = hs[0]
    if (hva % 4096 or hvsize != ((hsize + 4095) & ~4095) or hoff != 0 or hsize != len(high) or
            not hprot & 4 or not hva <= high_entry < hva+hsize or
            high.count(ABI) != 1 or
            any(hva < s[1]+s[2] and s[1] < hva+hvsize for s in mapped)):
        raise ValueError('invalid, overlapping, or non-returning diagnostic payload')
    if hva + hvsize >= LIMIT:
        raise ValueError('diagnostic payload end overflows')

    offset, size = find_initrd(original)
    decompressor = zlib.decompressobj(31)
    try:
        data = decompressor.decompress(original[offset:offset+size]) + decompressor.flush()
    except zlib.error as error:
        raise ValueError('invalid initrd gzip') from error
    if not decompressor.eof or not decompressor.unused_data or any(decompressor.unused_data):
        raise ValueError('initrd must have gzip followed by zero padding')
    if archive_has_capture(data, NAME):
        raise ValueError('diagnostic status filename already exists')
    used = size - len(decompressor.unused_data)
    aligned = (used+3) & ~3
    record, record_off = newc_entry(NAME, bytes(STATUS_SIZE), 0x41545610)
    trailer, _ = newc_entry(b'TRAILER!!!', b'', 0x41545611)
    if aligned + len(record) + len(trailer) > size:
        raise ValueError('diagnostic status archive does not fit initrd')
    status_offset = offset + aligned + record_off
    if status_offset + STATUS_SIZE > text[0][4]:
        raise ValueError('diagnostic record is outside original mapped text')
    status_pa = BASE + status_offset
    if status_pa + STATUS_SIZE > BASE + text[0][2]:
        raise ValueError('diagnostic record exceeds virtual text')

    code = elf_load(shim)
    for marker, value in zip(MARKERS, (status_pa, hva, hva+hvsize, high_entry)):
        code = code.replace(struct.pack('<I', marker), struct.pack('<I', value), 1)
    fileoff = (len(original)+4095) & ~4095
    if fileoff + len(high) >= LIMIT:
        raise ValueError('diagnostic file exceeds 32-bit Mach-O bounds')
    out = bytearray(original)
    out[offset+aligned:offset+aligned+len(record)+len(trailer)] = record + trailer
    command = struct.pack('<II16s8I', 1, 56, b'__ATVDIAG', hva, hvsize,
                          fileoff, len(high), 7, 7, 0, 0)
    out[end:end+56] = command
    struct.pack_into('<II', out, 16, count+1, length+56)
    out[HOOK:HOOK+len(code)] = code
    out[0x1008:0x100d] = b'\xe9' + struct.pack('<i', BASE+HOOK-(0x02001008+5))
    out.extend(bytes(fileoff-len(out)))
    out.extend(high)
    return bytes(out), status_pa


def main():
    if len(sys.argv) != 5:
        sys.exit('usage: package.py MENU_MACHO SHIM_ELF RETURNING_HIGH_MACHO NEW_MACHO')
    try:
        result, status = package(*(Path(arg).read_bytes() for arg in sys.argv[1:4]))
        with Path(sys.argv[4]).open('xb') as stream:
            stream.write(result)
        print(f'Returning diagnostic status: 0x{status:08x}; {STATUS_SIZE} bytes')
    except (OSError, ValueError, struct.error) as error:
        sys.exit(str(error))


if __name__ == '__main__':
    main()
