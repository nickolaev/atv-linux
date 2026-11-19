import os
from pathlib import Path
import subprocess
import tempfile
import unittest


SCRIPT = Path(__file__).with_name('bootstrap-target.sh')


class BootstrapTargetTest(unittest.TestCase):
    def test_installs_and_verifies_packages_in_target(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            root = base / 'target'
            (root / 'usr/sbin').mkdir(parents=True)
            (root / 'etc').mkdir()
            pkg_add = root / 'usr/sbin/pkg_add'
            pkg_add.touch(mode=0o755)
            mock = base / 'bin'
            mock.mkdir()
            chroot = mock / 'chroot'
            chroot.write_text('#!/bin/sh\nprintf "%s|%s\\n" "$PKG_PATH" "$*" >> "$CALLS"\n')
            chroot.chmod(0o755)
            source = SCRIPT.read_text().replace(
                'PATH=/sbin:/bin:/usr/sbin:/usr/bin',
                'PATH=' + str(mock) + ':/usr/bin:/bin:/usr/sbin:/sbin',
            )
            script = base / 'bootstrap.sh'
            script.write_text(source)
            env = os.environ.copy()
            env['CALLS'] = str(base / 'calls')
            subprocess.run(['sh', str(script), str(root)], env=env, check=True)
            calls = (base / 'calls').read_text()
            self.assertIn(f'{root} /usr/sbin/certctl rehash', calls)
            self.assertIn(f'{root} /usr/sbin/pkg_add pkgin pkg_chk', calls)
            self.assertIn(f'{root} /usr/sbin/pkg_info -e pkgin-[0-9]*', calls)
            self.assertIn(f'{root} /usr/sbin/pkg_info -e pkg_chk-[0-9]*', calls)
            self.assertIn('NetBSD/i386/11.1/All',
                          (root / 'usr/pkg/etc/pkgin/repositories.conf').read_text())
            self.assertTrue((root / 'etc/resolv.conf').is_file())

            chroot.write_text('#!/bin/sh\ncase "$2" in */pkg_add) exit 1;; esac\n')
            result = subprocess.run(['sh', str(script), str(root)], env=env,
                                    capture_output=True, text=True)
            self.assertNotEqual(result.returncode, 0)
            self.assertNotIn('installed and registered', result.stdout)

    def test_missing_target_fails(self):
        result = subprocess.run(['sh', str(SCRIPT), '/nonexistent-atv-target'],
                                capture_output=True)
        self.assertNotEqual(result.returncode, 0)


if __name__ == '__main__':
    unittest.main()
