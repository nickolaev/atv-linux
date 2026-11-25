import os
from pathlib import Path
import pty
import select
import subprocess
import tempfile
import time
import unittest


class PasswordPromptTest(unittest.TestCase):
    def test_fast_password_input_is_not_echoed(self):
        source = Path(__file__).with_name('install-session').read_text()
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / 'state').mkdir()
            (root / 'bin').mkdir()
            for name, body in {
                'tmux': 'exit 0',
                'getent': 'exit 1',
                'pwhash': 'cat >/dev/null; echo dummy-hash',
            }.items():
                path = root / 'bin' / name
                path.write_text('#!/bin/sh\n' + body + '\n')
                path.chmod(0o755)
            install = root / 'install'
            install.write_text('#!/bin/sh\ncp "$4" "$ACCOUNT_CAPTURE"\n')
            install.chmod(0o755)
            source = source.replace('PATH=/sbin:/bin:/usr/sbin:/usr/bin',
                                    'PATH=' + str(root / 'bin') + ':/sbin:/bin:/usr/sbin:/usr/bin')
            source = source.replace('state=/var/db/atv-installer', 'state=' + str(root / 'state'))
            source = source.replace('/var/run/atv-account.XXXXXXXX', str(root / 'atv-account.XXXXXXXX'))
            source = source.replace('/usr/atv-installer/bin/install.sh', str(install))
            script = root / 'session'
            script.write_text(source)
            master, slave = pty.openpty()
            process = subprocess.Popen(['sh', str(script)], stdin=slave, stdout=slave, stderr=slave,
                                       env={**os.environ, 'ACCOUNT_CAPTURE': str(root / 'capture')})
            os.close(slave)
            output = bytearray()
            def expect(marker):
                deadline = time.monotonic() + 5
                while marker not in output:
                    if time.monotonic() > deadline:
                        self.fail('prompt did not appear: ' + repr(marker))
                    ready, _, _ = select.select([master], [], [], 0.2)
                    if ready:
                        output.extend(os.read(master, 4096))
            try:
                expect(b'Username: ')
                os.write(master, b'alex\n')
                expect(b'Administrator password: ')
                os.write(master, b'first-secret\n')
                expect(b'Confirm password: ')
                os.write(master, b'first-secret\n')
                expect(b'Root password: ')
                os.write(master, b'second-secret\nsecond-secret\n')
                expect(b'Press Enter to close')
                os.write(master, b'\n')
                self.assertEqual(process.wait(timeout=5), 0)
                self.assertNotIn(b'first-secret', output)
                self.assertNotIn(b'second-secret', output)
                self.assertEqual((root / 'capture').read_text(), 'alex\ndummy-hash\ndummy-hash\n')
                self.assertEqual(list(root.glob('atv-account.*')), [])
            finally:
                if process.poll() is None:
                    process.kill()
                    process.wait()
                os.close(master)


if __name__ == '__main__':
    unittest.main()
