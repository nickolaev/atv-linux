#!/usr/bin/env python3
"""Embed the menu in the known ATV bootloader's initial ramdisk.

The bootloader is a 32-bit Mach-O executable containing a gzip-compressed
newc archive in its __initrd section. Keep the section and Mach-O layout
unchanged; the shorter gzip stream is padded with zero bytes.
"""
import gzip
import hashlib
import shutil
import struct
import sys
from pathlib import Path

EXPECTED_SHA256 = "1a1d765ed42f6e806fc684e6f1f26a0706495c33f030552cad9cf38b525fde73"
ANCHOR = b'if [ "$ATVBOOT" == "auto" ]; then\n'


def align4(number):
    return (number + 3) & ~3


def find_initrd(blob):
    if len(blob) < 28:
        raise ValueError("Truncated Mach-O header")
    magic, _, _, _, count, command_bytes, _ = struct.unpack_from("<7I", blob)
    if magic != 0xFEEDFACE or 28 + command_bytes > len(blob):
        raise ValueError("Expected a valid 32-bit little-endian Mach-O")
    position = 28
    matches = []
    for _ in range(count):
        if position + 8 > 28 + command_bytes:
            raise ValueError("Truncated Mach-O command")
        command, size = struct.unpack_from("<II", blob, position)
        if size < 8 or position + size > 28 + command_bytes:
            raise ValueError("Invalid Mach-O command size")
        if command == 1:  # LC_SEGMENT
            if size < 56:
                raise ValueError("Truncated Mach-O segment")
            sections = struct.unpack_from("<I", blob, position + 48)[0]
            if 56 + sections * 68 > size:
                raise ValueError("Truncated Mach-O section table")
            for index in range(sections):
                section = position + 56 + index * 68
                name = blob[section:section + 16].split(b"\0", 1)[0]
                if name == b"__initrd":
                    length, offset = struct.unpack_from("<II", blob, section + 36)
                    if offset + length > len(blob):
                        raise ValueError("Ramdisk section extends beyond Mach-O")
                    matches.append((offset, length))
        position += size
    if position != 28 + command_bytes or len(matches) != 1:
        raise ValueError("Expected exactly one ramdisk section")
    return matches[0]


def add_menu_to_rcs(archive, menu):
    position = 0
    result = bytearray()
    replaced = 0
    while True:
        start = position
        if position + 110 > len(archive) or archive[position:position + 6] != b"070701":
            raise ValueError("Invalid or unsupported newc archive")
        header = bytearray(archive[position:position + 110])
        try:
            fields = [int(header[6 + i * 8:14 + i * 8], 16) for i in range(13)]
        except ValueError as error:
            raise ValueError("Invalid newc header") from error
        size, namesize = fields[6], fields[11]
        name_start = position + 110
        name_end = name_start + namesize
        if namesize < 1 or name_end > len(archive) or archive[name_end - 1] != 0:
            raise ValueError("Invalid newc filename")
        name = archive[name_start:name_end - 1]
        data_start = align4(name_end)
        data_end = data_start + size
        next_entry = align4(data_end)
        if next_entry > len(archive):
            raise ValueError("Truncated newc entry")
        if name in (b"etc/init.d/rcS", b"./etc/init.d/rcS"):
            original = archive[data_start:data_end]
            if original.count(ANCHOR) != 1:
                raise ValueError("Unexpected boot script; refusing to patch")
            injection = b'if [ "$ATVBOOT" = "menu" ]; then\n' + menu + b'\nfi\n\n'
            changed = original.replace(ANCHOR, injection + ANCHOR)
            header[54:62] = f"{len(changed):08x}".encode("ascii")
            result.extend(header)
            result.extend(archive[name_start:name_end])
            result.extend(b"\0" * (align4(len(result)) - len(result)))
            result.extend(changed)
            result.extend(b"\0" * (align4(len(result)) - len(result)))
            replaced += 1
        else:
            result.extend(archive[start:next_entry])
        position = next_entry
        if name == b"TRAILER!!!":
            result.extend(archive[position:])
            break
    if replaced != 1:
        raise ValueError("Expected exactly one boot script")
    result.extend(b"\0" * ((-len(result)) % 512))
    return bytes(result)


def main():
    if len(sys.argv) != 4:
        raise ValueError("Usage: embed_boot_menu.py MACH_KERNEL MENU_SCRIPT OUTPUT")
    source, menu_file, output = map(Path, sys.argv[1:])
    if source.resolve() == output.resolve():
        raise ValueError("Output must differ from input")
    blob = bytearray(source.read_bytes())
    if hashlib.sha256(blob).hexdigest() != EXPECTED_SHA256:
        raise ValueError("Unrecognized bootloader; refusing to patch")
    menu = menu_file.read_bytes()
    if not menu.startswith(b"#!/bin/sh\n") or b"\0" in menu:
        raise ValueError("Expected a POSIX shell menu script")
    offset, size = find_initrd(blob)
    archive = gzip.decompress(blob[offset:offset + size])
    modified = add_menu_to_rcs(archive, menu)
    compressed = gzip.compress(modified, compresslevel=9, mtime=0)
    if len(compressed) > size:
        raise ValueError("Modified ramdisk does not fit the existing Mach-O section")
    blob[offset:offset + size] = compressed + bytes(size - len(compressed))
    output.write_bytes(blob)
    shutil.copymode(source, output)
    print(f"Embedded menu in initrd ({len(compressed)} of {size} bytes)")


if __name__ == "__main__":
    try:
        main()
    except (OSError, ValueError, EOFError, struct.error) as error:
        print(f"Cannot embed boot menu: {error}", file=sys.stderr)
        sys.exit(1)
