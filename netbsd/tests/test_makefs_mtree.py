import io
import os
from pathlib import Path
import subprocess
import tarfile
import tempfile
import unittest


class MakefsMtreeTest(unittest.TestCase):
    def test_release_hardlink_retains_setuid_mode(self):
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            root = base / 'root'
            sets = base / 'sets'
            (root / 'usr/bin').mkdir(parents=True)
            sets.mkdir()
            (root / 'usr/bin/passwd').write_bytes(b'x')
            os.link(root / 'usr/bin/passwd', root / 'usr/bin/yppasswd')
            for name in ('base', 'etc', 'kern-GENERIC', 'modules'):
                with tarfile.open(sets / (name + '.tgz'), 'w:gz') as archive:
                    if name == 'base':
                        entry = tarfile.TarInfo('./usr/bin/passwd')
                        entry.mode, entry.size = 0o4555, 1
                        archive.addfile(entry, io.BytesIO(b'x'))
                        entry = tarfile.TarInfo('./usr/bin/yppasswd')
                        entry.mode, entry.type = 0o4555, tarfile.LNKTYPE
                        entry.linkname = './usr/bin/passwd'
                        archive.addfile(entry)
            output = base / 'root.mtree'
            script = Path(__file__).resolve().parents[1] / 'image-integration/makefs-mtree.py'
            subprocess.run(['python3', str(script), str(root), str(sets), str(output)], check=True)
            lines = output.read_text().splitlines()
            for name in ('passwd', 'yppasswd'):
                line = next(line for line in lines if line.startswith('./usr/bin/' + name + ' '))
                self.assertIn('mode=4555', line)


if __name__ == '__main__':
    unittest.main()
