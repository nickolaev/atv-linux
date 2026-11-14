#!/usr/bin/env python3
"""Non-privileged tests for input validation and the no-overwrite contract."""
import pathlib
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
