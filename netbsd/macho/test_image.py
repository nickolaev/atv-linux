#!/usr/bin/env python3
"""Exercise the image builder's non-privileged preflight and output safety."""
import pathlib
import struct
import subprocess
import tempfile
import unittest
from recovery_mbr import compose


SCRIPT = pathlib.Path(__file__).with_name("build-image.sh")


class ImagePreflightTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = pathlib.Path(self.temp.name)
        self.recovery = self.root / "recovery"
        self.recovery.mkdir()
        (self.recovery / "boot.efi").write_bytes(b"efi")
        (self.recovery / "BootLogo.png").write_bytes(b"logo")
        (self.recovery / "com.apple.Boot.plist").write_bytes(b"plist")
        kext = self.recovery / "System/Library/Extensions/KernelMemoryAccess.kext/Contents"
        (kext / "MacOS").mkdir(parents=True)
        (kext / "Info.plist").write_bytes(b"plist")
        (kext / "MacOS/KernelMemoryAccess").write_bytes(b"kext")
        self.kernel = self.root / "mach_kernel"
        self.kernel.write_bytes(b"macho")
        self.output = self.root / "output.img"

    def tearDown(self):
        self.temp.cleanup()

    def check(self, *extra):
        return subprocess.run(
            ["bash", str(SCRIPT), "--check", "--kernel", str(self.kernel),
             "--recovery", str(self.recovery), "--output", str(self.output), *extra],
            capture_output=True, text=True, check=False,
        )

    def test_valid_does_not_create_output(self):
        result = self.check()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertFalse(self.output.exists())

    def test_configurable_sizes_and_bounds(self):
        self.assertEqual(self.check('--image-mib', '128', '--recovery-mib', '96').returncode, 0)
        for image, recovery in [('64', '64'), ('64', '15'), ('0', '32'),
                                ('99999', '32'), ('64;false', '32')]:
            with self.subTest(image=image, recovery=recovery):
                self.assertNotEqual(self.check('--image-mib', image,
                                               '--recovery-mib', recovery).returncode, 0)
        self.assertFalse(self.output.exists())

    def test_existing_output_unchanged(self):
        self.output.write_bytes(b"keep")
        self.assertNotEqual(self.check().returncode, 0)
        self.assertEqual(self.output.read_bytes(), b"keep")

    def test_dangling_output_symlink(self):
        self.output.symlink_to(self.root / "missing")
        self.assertNotEqual(self.check().returncode, 0)

    def test_device_output_rejected(self):
        self.output = pathlib.Path("/dev/atv1-macho-test.img")
        self.assertNotEqual(self.check().returncode, 0)

    def test_missing_kext_rejected(self):
        (self.recovery / "System/Library/Extensions/KernelMemoryAccess.kext/Contents/Info.plist").unlink()
        self.assertNotEqual(self.check().returncode, 0)

    def test_system_symlink_rejected(self):
        (self.recovery / "System/link").symlink_to(self.root / "missing")
        self.assertNotEqual(self.check().returncode, 0)

    def test_kernel_symlink_rejected(self):
        original = self.root / "real-kernel"
        self.kernel.rename(original)
        self.kernel.symlink_to(original)
        self.assertNotEqual(self.check().returncode, 0)

    def test_hybrid_recovery_mbr(self):
        source = bytearray(512)
        dest = bytearray(512)
        source[510:] = dest[510:] = b'\x55\xaa'
        source[450], source[466] = 0xee, 0xda
        struct.pack_into('<II', source, 454, 1, 39)
        struct.pack_into('<II', source, 470, 40, 62461)
        dest[450] = 0xee
        struct.pack_into('<II', dest, 454, 1, 131071)
        result = compose(source, dest)
        self.assertEqual(result[446:478], source[446:478])
        self.assertEqual(result[478:510], bytes(32))
        self.assertEqual(dest[450], 0xee)
        source[466] = 0x83
        with self.assertRaises(ValueError):
            compose(source, dest)


if __name__ == "__main__":
    unittest.main()
