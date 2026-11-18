#!/usr/bin/env python3
"""Non-privileged tests for input validation and the no-overwrite contract."""
import pathlib
import struct
import subprocess
import tempfile
import unittest


SCRIPT = pathlib.Path(__file__).resolve().parents[1] / "build.sh"


class PreflightTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = pathlib.Path(self.temp.name)
        self.asd = self.root / "System"
        original = self.asd / "Library/CoreServices/ASD.acm/Contents/MacOS/ASD"
        original.parent.mkdir(parents=True)
        original.write_bytes(b"diagnostic")
        self.release = self.root / "release"
        efi = self.release / "EFI/boot/bootia32.efi"
        efi.parent.mkdir(parents=True)
        efi.write_bytes(b"refind")
        (self.release / "ASD").write_bytes(b"replacement")
        (self.release / "GopShimDxe.efi").write_bytes(b"gop")
        self.output = self.root / "test.img"
        self.kernel = self.root / "netbsd-INSTALL"
        ident = b"\x7fELF\x01\x01\x01" + bytes(9)
        header = struct.pack("<16sHHIIIIIHHHHHH", ident, 2, 3, 1, 0xc0100000,
                             52, 0, 0, 52, 32, 1, 0, 0, 0)
        segment = struct.pack("<8I", 1, 0x1000, 0xc0100000, 0x100000,
                              4, 4, 5, 0x1000)
        self.kernel.write_bytes((header + segment).ljust(0x1000, b"\0") + b"code")
        self.loader = self.root / "bootia32.efi"
        pe = bytearray(256)
        pe[:2] = b"MZ"
        struct.pack_into("<I", pe, 60, 64)
        pe[64:68] = b"PE\0\0"
        struct.pack_into("<H", pe, 68, 0x14c)
        struct.pack_into("<H", pe, 88, 0x10b)
        struct.pack_into("<H", pe, 156, 10)
        self.loader.write_bytes(pe)

    def tearDown(self):
        self.temp.cleanup()

    def run_check(self, *extra):
        return subprocess.run(
            ["bash", str(SCRIPT), "--asd-system", str(self.asd), "--atv1sm",
             str(self.release), "--output", str(self.output), "--check", *extra],
            capture_output=True, text=True, check=False,
        )

    def test_valid_input_does_not_create_image(self):
        result = self.run_check()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertFalse(self.output.exists())

    def netbsd_args(self):
        return ("--netbsd-kernel", str(self.kernel), "--netbsd-efi", str(self.loader))

    def test_netbsd_inputs_pass_without_creating_image(self):
        result = self.run_check(*self.netbsd_args())
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertFalse(self.output.exists())

    def test_autoboot_requires_netbsd_inputs(self):
        result = self.run_check("--autoboot")
        self.assertNotEqual(result.returncode, 0)
        self.assertIn("--autoboot requires", result.stderr)
        self.assertFalse(self.output.exists())

    def test_autoboot_netbsd_inputs_pass_without_creating_image(self):
        result = self.run_check("--autoboot", *self.netbsd_args())
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertFalse(self.output.exists())

    def test_netbsd_inputs_must_be_supplied_together(self):
        for flag, path in (("--netbsd-kernel", self.kernel), ("--netbsd-efi", self.loader)):
            with self.subTest(flag=flag):
                self.assertNotEqual(self.run_check(flag, str(path)).returncode, 0)

    def test_wrong_architecture_efi_is_rejected(self):
        pe = bytearray(self.loader.read_bytes())
        struct.pack_into("<H", pe, 68, 0x8664)
        self.loader.write_bytes(pe)
        self.assertNotEqual(self.run_check(*self.netbsd_args()).returncode, 0)

    def test_wrong_kernel_or_truncated_efi_is_rejected(self):
        original = self.kernel.read_bytes()
        self.kernel.write_bytes(b"wrong kernel")
        self.assertNotEqual(self.run_check(*self.netbsd_args()).returncode, 0)
        self.kernel.write_bytes(original)
        self.loader.write_bytes(b"MZ")
        self.assertNotEqual(self.run_check(*self.netbsd_args()).returncode, 0)

    def test_netbsd_input_symlink_is_rejected(self):
        copy = self.root / "kernel-copy"
        self.kernel.rename(copy)
        self.kernel.symlink_to(copy)
        self.assertNotEqual(self.run_check(*self.netbsd_args()).returncode, 0)

    def test_existing_output_is_unchanged(self):
        self.output.write_bytes(b"keep")
        result = self.run_check()
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(self.output.read_bytes(), b"keep")

    def test_dangling_output_symlink_is_rejected(self):
        self.output.symlink_to(self.root / "missing")
        self.assertNotEqual(self.run_check().returncode, 0)
        self.assertTrue(self.output.is_symlink())

    def test_missing_release_payload_is_rejected(self):
        (self.release / "GopShimDxe.efi").unlink()
        self.assertNotEqual(self.run_check().returncode, 0)

    def test_input_symlink_is_rejected(self):
        (self.release / "EFI/boot/link").symlink_to(self.root / "elsewhere")
        self.assertNotEqual(self.run_check().returncode, 0)

    def test_invalid_sizes_are_rejected(self):
        for size in ("0", "127", "32769", "1x", "99999999999999999999"):
            with self.subTest(size=size):
                self.assertNotEqual(self.run_check("--size-mib", size).returncode, 0)

    def test_device_output_is_rejected(self):
        self.output = pathlib.Path("/dev/atv1sm-test-output")
        self.assertNotEqual(self.run_check().returncode, 0)


if __name__ == "__main__":
    unittest.main()
