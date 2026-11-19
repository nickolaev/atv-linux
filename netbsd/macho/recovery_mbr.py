#!/usr/bin/env python3
"""Copy the verified recovery MBR entries into a new small GPT image.

The first 40 sectors of the source and destination are metadata, not a
partition. Only the destination's 512-byte MBR is modified.
"""
import struct
import sys
import uuid
from pathlib import Path


def compose(source, destination):
    if len(source) != 512 or len(destination) != 512 or source[510:] != b'\x55\xaa' or destination[510:] != b'\x55\xaa':
        raise ValueError('invalid MBR')
    def entry(buf, number):
        off = 446 + 16 * number
        return (buf[off + 4], *struct.unpack_from('<II', buf, off + 8))
    if entry(source, 0) != (0xee, 1, 39) or entry(source, 1) != (0xda, 40, 62461):
        raise ValueError('source does not have expected Apple TV hybrid entries')
    if entry(destination, 0)[0:2] != (0xee, 1) or any(destination[462:510]):
        raise ValueError('destination is not a protective single-entry MBR')
    # Preserve the destination boot code and signature; adopt only the two
    # entries relevant to its single recovery partition.
    result = bytearray(destination)
    result[446:478] = source[446:478]
    result[478:510] = bytes(32)
    return bytes(result)


if __name__ == '__main__':
    if len(sys.argv) != 3:
        sys.exit('usage: recovery_mbr.py SOURCE_IMAGE NEW_DESTINATION_IMAGE')
    try:
        source = Path(sys.argv[1])
        destination = Path(sys.argv[2])
        if not source.is_file() or not destination.is_file() or source.resolve() == destination.resolve():
            raise ValueError('expected distinct regular image files')
        if destination.is_symlink() or destination.stat().st_size != 64 * 1024 * 1024:
            raise ValueError('destination must be a new 64 MiB regular image')
        with source.open('rb') as src, destination.open('r+b') as dst:
            source_mbr, dest_mbr = src.read(512), dst.read(512)
            header = dst.read(512)
            if header[:8] != b'EFI PART' or struct.unpack_from('<Q', header, 72)[0] != 2:
                raise ValueError('destination has no expected primary GPT')
            dst.seek(1024)
            partition = dst.read(128)
            if (partition[:16] != uuid.UUID('5265636f-7665-11aa-aa11-00306543ecac').bytes_le or
                    struct.unpack_from('<QQ', partition, 32) != (40, 62500)):
                raise ValueError('destination lacks the expected recovery partition')
            result = compose(source_mbr, dest_mbr)
            dst.seek(0)
            dst.write(result)
    except (ValueError, OSError, struct.error) as error:
        sys.exit(str(error))
