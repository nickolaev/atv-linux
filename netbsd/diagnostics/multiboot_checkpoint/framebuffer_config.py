#!/usr/bin/env python3
"""Derive safe visual checkpoint build flags from the signed Linux preflight."""
import argparse
from pathlib import Path
import re


def build_flags(report):
    values = {}
    for key, value in re.findall(r'^fb_(\w+)=(0x[0-9a-f]{8})$', report, re.MULTILINE):
        if key in values:
            raise ValueError(f'duplicate framebuffer field: {key}')
        values[key] = int(value, 16)
    if re.findall(r'^fb_id=(.*)$', report, re.MULTILINE) != ['nouveaufb']:
        raise ValueError('expected the live Nouveau framebuffer')
    if (values['type'], values['visual'], values['bits_per_pixel']) != (0, 2, 32):
        raise ValueError('expected packed 32-bit truecolor pixels')
    if values['grayscale'] or values['nonstd']:
        raise ValueError('expected standard color pixels')
    for channel in ('red', 'green', 'blue'):
        if (values[f'{channel}_length'], values[f'{channel}_msb_right']) != (8, 0):
            raise ValueError('unsupported RGB channel layout')
    if (values['green_offset'] != 8 or
            {values['red_offset'], values['blue_offset']} != {0, 16} or
            (values['transp_length'], values['transp_offset']) not in ((0, 0), (0, 24), (8, 24))):
        raise ValueError('expected RGB or BGR byte order')

    width, height = values['xres'], values['yres']
    xoffset, yoffset = values['xoffset'], values['yoffset']
    stride = values['line_length']
    if not (64 <= width <= 4096 and 64 <= height <= 4096 and
            xoffset + width <= values['xres_virtual'] and
            yoffset + height <= values['yres_virtual'] and
            (xoffset + width) * 4 <= stride and stride % 4 == 0):
        raise ValueError('unsupported visible framebuffer window or stride')

    origin = values['smem_start']
    first_pixel = origin + yoffset * stride + xoffset * 4
    visible_bytes = (height - 1) * stride + width * 4
    if (first_pixel + visible_bytes > origin + values['smem_len'] or
            visible_bytes > 64 * 1024 * 1024 or first_pixel % 4):
        raise ValueError('visible window is outside the framebuffer allocation')

    pci = re.search(r'^--- PCI VGA device and BARs ---\n0x10de\n0x01d7\n'
                    r'(?:0x[0-9a-f]+ ){2}0x[0-9a-f]+\n'
                    r'(0x[0-9a-f]+) (0x[0-9a-f]+) (0x[0-9a-f]+)\n',
                    report, re.MULTILINE)
    if pci is None:
        raise ValueError('missing Apple TV NVIDIA PCI aperture')
    bar_start, bar_end, bar_flags = (int(field, 16) for field in pci.groups())
    if not (bar_flags & 0x200 and 0x10000000 <= bar_start <= origin <= first_pixel and
            first_pixel + visible_bytes - 1 <= bar_end < 1 << 32):
        raise ValueError('visible window is outside GPU BAR1')

    ram = re.findall(r'^([0-9a-f]+)-([0-9a-f]+) : System RAM$', report, re.MULTILINE)
    if not any(int(start, 16) <= 0x01c00000 and int(end, 16) >= 0x01c0ffff
               for start, end in ram):
        raise ValueError('checkpoint load range is outside System RAM')

    return (f'-DATV_FB_BASE=0x{first_pixel:08x}', f'-DATV_FB_WIDTH={width}',
            f'-DATV_FB_HEIGHT={height}', f'-DATV_FB_STRIDE={stride}',
            f"-DATV_FB_RED_OFFSET={values['red_offset']}",
            f"-DATV_FB_GREEN_OFFSET={values['green_offset']}",
            f"-DATV_FB_BLUE_OFFSET={values['blue_offset']}")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('report', type=Path)
    args = parser.parse_args()
    try:
        print('\n'.join(build_flags(args.report.read_text())))
    except (OSError, KeyError, ValueError) as error:
        parser.exit(1, f'Unable to configure the visual checkpoint: {error}\n')


if __name__ == '__main__':
    main()
