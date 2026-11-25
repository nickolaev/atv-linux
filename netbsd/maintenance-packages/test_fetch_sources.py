import hashlib
import io
import os
from pathlib import Path
import subprocess
import tarfile
import tempfile
import unittest

SCRIPT = Path(__file__).with_name('fetch-sources.sh')


class FetchSourcesTest(unittest.TestCase):
    def test_installs_archives_and_rejects_bad_checksum(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            fixtures = base / 'fixtures'
            fixtures.mkdir()
            for archive, directory in [('pkgsrc.tar.gz', 'pkgsrc')]:
                with tarfile.open(fixtures / archive, 'w:gz') as tar:
                    data = b'# fixture\n'
                    info = tarfile.TarInfo(directory + '/Makefile')
                    info.size = len(data)
                    tar.addfile(info, io.BytesIO(data))
            digest = hashlib.sha512((fixtures / 'pkgsrc.tar.gz').read_bytes()).hexdigest()
            (fixtures / 'pkgsrc.tar.gz.SHA512').write_text('SHA512 (pkgsrc.tar.gz) = ' + digest + '\n')
            mock = base / 'bin'
            mock.mkdir()
            (mock / 'ftp').write_text('#!/bin/sh\ncase "$3" in\n*.SHA512) file=pkgsrc.tar.gz.SHA512;;\n*pkgsrc.tar.gz) file=pkgsrc.tar.gz;;\n*) file=wip.tar.gz;;\nesac\ncp "$FIXTURES/$file" "$2"\n')
            (mock / 'sha512').write_text('#!/bin/sh\nshasum -a 512 "$2" | cut -d " " -f 1\n')
            for file in mock.iterdir():
                file.chmod(0o755)
            source = SCRIPT.read_text().replace('PATH=/sbin:/bin:/usr/sbin:/usr/bin', 'PATH=' + str(mock) + ':/usr/bin:/bin')
            script = base / 'fetch.sh'
            script.write_text(source)
            env = os.environ.copy()
            env['FIXTURES'] = str(fixtures)
            root = base / 'root'
            (root / 'usr').mkdir(parents=True)
            subprocess.run(['sh', str(script), str(root)], env=env, check=True)
            self.assertTrue((root / 'usr/pkgsrc/Makefile').exists())
            result = subprocess.run(['sh', str(script), str(root)], env=env, capture_output=True)
            self.assertNotEqual(result.returncode, 0)
            badroot = base / 'badroot'
            (badroot / 'usr').mkdir(parents=True)
            (fixtures / 'pkgsrc.tar.gz.SHA512').write_text('SHA512 (pkgsrc.tar.gz) = bad\n')
            result = subprocess.run(['sh', str(script), str(badroot)], env=env, capture_output=True)
            self.assertNotEqual(result.returncode, 0)
            self.assertFalse((badroot / 'usr/pkgsrc').exists())


if __name__ == '__main__':
    unittest.main()
