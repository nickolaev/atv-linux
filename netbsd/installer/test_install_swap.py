import os
from pathlib import Path
import subprocess
import tempfile
import unittest


class InstallSwapTest(unittest.TestCase):
    def run_wedges(self, wedges, fail_activation=False):
        script = Path(__file__).with_name('install.sh').read_text()
        start = script.index('swapdk=$(printf')
        end = script.index('newfs -O 1', start)
        fragment = script[start:end].replace(
            '(cd /dev && sh MAKEDEV "$rootdk" "$espdk" "$swapdk")', ':'
        )
        with tempfile.TemporaryDirectory() as directory:
            temp = Path(directory)
            swapctl = temp / 'swapctl'
            swapctl.write_text('#!/bin/sh\nprintf "%s\\n" "$*" >> "$SWAP_LOG"\n'
                               '[ "$1" != -a ] || [ "${FAIL_ACTIVATION:-0}" = 0 ]\n')
            swapctl.chmod(0o755)
            env = os.environ.copy()
            env.update(PATH=f'{directory}:' + env['PATH'], SWAP_LOG=str(temp / 'calls'),
                       WEDGES=wedges, FAIL_ACTIVATION='1' if fail_activation else '0')
            result = subprocess.run(['sh', '-c',
                                     'set -eu\nwedges=$WEDGES\nrootdk=dk3\nespdk=dk1\n' + fragment],
                                    env=env, capture_output=True, text=True)
            calls = (temp / 'calls').read_text() if (temp / 'calls').exists() else ''
            return result, calls

    def test_valid_swap_is_activated(self):
        result, calls = self.run_wedges('dk2: atv-swap, 2097152 blocks at 260096, type: swap')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(calls.splitlines(), ['-a /dev/dk2', '-lk'])

    def test_wrong_geometry_or_duplicate_are_rejected(self):
        good = 'dk2: atv-swap, 2097152 blocks at 260096, type: swap'
        for wedges in ('dk2: atv-swap, 1 blocks at 260096, type: swap',
                       good + '\ndk4: atv-swap, 2097152 blocks at 9, type: swap'):
            with self.subTest(wedges=wedges):
                result, calls = self.run_wedges(wedges)
                self.assertNotEqual(result.returncode, 0)
                self.assertEqual(calls, '')

    def test_failed_activation_stops_install(self):
        result, calls = self.run_wedges(
            'dk2: atv-swap, 2097152 blocks at 260096, type: swap', True)
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(calls.splitlines(), ['-a /dev/dk2'])


if __name__ == '__main__':
    unittest.main()
