"""Nonprivileged safety check for the test-only fixture builder."""
import pathlib
import subprocess
import tempfile
import unittest


class BuilderSafetyTest(unittest.TestCase):
    def test_existing_directory_is_not_modified(self):
        script = pathlib.Path(__file__).with_name('build_macho_fixture.sh')
        with tempfile.TemporaryDirectory() as tmp:
            base = pathlib.Path(tmp)
            kernel = base / 'kernel'
            kernel.write_bytes(b'kernel')
            output = base / 'existing'
            output.mkdir()
            sentinel = output / 'kernel.elf'
            sentinel.write_bytes(b'keep')
            result = subprocess.run(['sh', str(script), str(kernel), str(output)],
                                    capture_output=True, check=False)
            self.assertNotEqual(result.returncode, 0)
            self.assertEqual(sentinel.read_bytes(), b'keep')
            self.assertEqual(list(output.iterdir()), [sentinel])


if __name__ == '__main__':
    unittest.main()
