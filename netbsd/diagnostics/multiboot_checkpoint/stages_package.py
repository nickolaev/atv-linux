#!/usr/bin/env python3
"""Package the NetBSD 11.1/i386 kernel with guarded initialization hooks."""
import argparse
import hashlib
from pathlib import Path
import struct

from package import CHECKPOINT_ADDRESS, PAGE_SIZE, package, plan_elf


# Physical address and original complete instructions at each hook site.
# Pre-paging helpers resume directly after replaying displaced instructions.
# Post-paging helpers return to the high kernel mapping through the code alias.
STAGE_SITES = {
    'pre-multiboot': (0x0010006D, bytes.fromhex('e8 9a 59 02 00')),
    'pre-reloc': (0x00100075, bytes.fromhex('e9 61 01 00 00')),
    'pre-paging': (0x00100511, bytes.fromhex('0f 20 c0 0d 2b 00 05 80')),
    'post-paging': (0x00100522, bytes.fromhex('8b 0d a8 dd 4b c1')),
    'post-reloc': (0x0010056A, bytes.fromhex('e8 3a 58 02 00 e8 f2 65 02 00')),
    'after-gdt': (0x0010057B, bytes.fromhex('e8 10 c1 02 00')),
    'before-init386': (0x00100595, bytes.fromhex('e8 d2 cf 02 00')),
}
HIGH_MAPPING = 0xC0000000
POST_PAGING = {'post-paging', 'post-reloc', 'after-gdt', 'before-init386'}
INIT386 = 0xC012D56C
INIT386_TRAMPOLINE = 0xC0AC5C00
INIT386_TRAMPOLINE_OFFSET = 0x9C6C00
ALIAS_CLEANUP = bytes.fromhex('89 0a 0f 01 38')


def rel32(opcode, source, destination):
    return struct.pack('<Bi', opcode, destination - (source + 5))


def text_file_offset(segments, address, length):
    executable = [seg for seg in segments if seg['flags'] & 1 and
                  seg['physical_address'] <= address and
                  address + length <= seg['physical_address'] + seg['file_size']]
    if len(executable) != 1:
        raise ValueError(f'{address:#x} does not map to executable kernel file bytes')
    segment = executable[0]
    if segment['virtual_address'] - segment['physical_address'] != HIGH_MAPPING:
        raise ValueError(f'unexpected high kernel mapping at {address:#x}')
    return segment['file_offset'] + address - segment['physical_address']


def install_init386_trampoline(image, kernel, segments, helper):
    # Run in permanent kernel text so it can clear and invalidate the code
    # alias. Tail-jump leaves init386's original argument and return address.
    address = INIT386_TRAMPOLINE
    clear_alias = rel32(0xE8, address, helper) + ALIAS_CLEANUP
    patch = clear_alias + rel32(0xE9, address + len(clear_alias), INIT386)
    offset = text_file_offset(segments, address - HIGH_MAPPING, len(patch))
    if (offset != INIT386_TRAMPOLINE_OFFSET or
            kernel[offset:offset + len(patch)] != b'\xcc' * len(patch)):
        raise ValueError('unexpected init386 trampoline padding')
    image[offset:offset + len(patch)] = patch


def package_stages(kernel, checkpoint, hooks):
    if hooks.keys() != STAGE_SITES.keys():
        raise ValueError(f'supply one hook for each stage: {", ".join(STAGE_SITES)}')
    if len(set(hooks.values())) != len(hooks):
        raise ValueError('stage helpers must use distinct entry addresses')

    image = package(kernel, checkpoint, CHECKPOINT_ADDRESS)
    segments = plan_elf(kernel)['segments']
    for name, (address, original) in STAGE_SITES.items():
        destination = hooks[name]
        if not CHECKPOINT_ADDRESS < destination < CHECKPOINT_ADDRESS + len(checkpoint):
            raise ValueError(f'{name} helper must be inside the appended checkpoint')

        offset = text_file_offset(segments, address, len(original))
        if kernel[offset:offset + len(original)] != original:
            raise ValueError(f'unexpected kernel instructions at {name} ({address:#x})')

        if name in POST_PAGING:
            alias_offset = destination - CHECKPOINT_ADDRESS
            if alias_offset >= PAGE_SIZE:
                raise ValueError(f'{name} helper must be in the first checkpoint page')
            target_va = HIGH_MAPPING + alias_offset
            if name == 'before-init386':
                install_init386_trampoline(image, kernel, segments, target_va)
                target_va = INIT386_TRAMPOLINE
            branch = rel32(0xE8, HIGH_MAPPING + address, target_va)
        else:
            branch = rel32(0xE9, address, destination)
        tail = b'\x90' * (len(original) - len(branch))
        image[offset:offset + len(original)] = branch + tail
    return image


def parse_hook(value):
    try:
        name, address = value.split('=', 1)
        if name not in STAGE_SITES:
            raise ValueError(f'unknown stage {name}')
        return name, int(address, 0)
    except ValueError as error:
        raise argparse.ArgumentTypeError(f'expected STAGE=ADDRESS ({error})') from error


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('kernel', type=Path)
    parser.add_argument('checkpoint', type=Path, help='flat checkpoint linked at 0x01c00000')
    parser.add_argument('output', type=Path)
    parser.add_argument('--sha256', required=True, help='expected input kernel SHA-256')
    parser.add_argument('--hook', type=parse_hook, action='append', required=True)
    args = parser.parse_args()
    try:
        hooks = dict(args.hook)
        if len(hooks) != len(args.hook):
            raise ValueError('duplicate stage hook')
        kernel = args.kernel.read_bytes()
        if hashlib.sha256(kernel).hexdigest() != args.sha256.lower():
            raise ValueError('input kernel SHA-256 mismatch')
        image = package_stages(kernel, args.checkpoint.read_bytes(), hooks)
        with args.output.open('xb') as stream:
            stream.write(image)
    except (OSError, ValueError, struct.error) as error:
        parser.exit(1, f'Unable to package stage checkpoint: {error}\n')
    print(hashlib.sha256(image).hexdigest())


if __name__ == '__main__':
    main()
