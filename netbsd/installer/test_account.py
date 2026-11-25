import os
from pathlib import Path
import subprocess
import tempfile
import unittest


class AccountSetupTest(unittest.TestCase):
    def test_password_account_without_public_key(self):
        script = Path(__file__).with_name('populate-root.sh').read_text()
        start = script.index('if [ -n "$account_file" ]; then')
        end = script.index('cat > "$root/etc/rc.local"', start)
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / 'etc').mkdir()
            (root / 'etc/rc.conf').write_text('')
            account = root / 'account'
            account.write_text('alex\n$userhash\n$roothash\n')
            mock = root / 'chroot'
            mock.write_text('#!/bin/sh\nprintf "%s\\n" "$*" >> "$CALLS"\n')
            mock.chmod(0o755)
            env = dict(os.environ, PATH=directory + ':' + os.environ['PATH'],
                       ROOT=str(root), ACCOUNT=str(account), CALLS=str(root / 'calls'))
            result = subprocess.run(['sh', '-c', 'set -eu\nroot=$ROOT\naccount_file=$ACCOUNT\nssh_key=\n' + script[start:end]],
                                    env=env, text=True, capture_output=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            calls = (root / 'calls').read_text()
            self.assertIn('useradd -m -G wheel -s /bin/sh -p $userhash alex', calls)
            self.assertIn('usermod -F alex', calls)
            self.assertIn('usermod -p $roothash root', calls)
            self.assertIn('sshd=YES', (root / 'etc/rc.conf').read_text())


if __name__ == '__main__':
    unittest.main()
